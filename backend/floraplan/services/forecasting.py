"""Сервис прогнозирования спроса (П-5, С-6, С-17; ПР 7-8, вариант использования «Построить прогноз спроса»).

1. История продаж «товар × точка» по дням (DailySales).
2. Подготовка данных: дни дефицита заменяются оценкой спроса, праздники и акции снимаются
   календарными коэффициентами (оценка по прошлым годам или заданные вручную).
3. Модель выбирается для каждого ряда по WAPE на отложенном периоде (или задана версией модели).
4. Прогноз умножается на коэффициенты будущих событий и поправку на погоду; P80/P95 —
   по распределению ошибок на отложенном периоде.
"""
import logging
import math
import multiprocessing
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..config import get_settings
from ..errors import DomainError
from ..models import (CalendarEvent, DailySales, Forecast, ForecastModel, ForecastRun, Location, Product,
                      StockoutDay, Weather)
from . import tsmodels as tm
from . import weather as wx

SALE_LOCATIONS = ("salon", "online")
log = logging.getLogger("floraplan.forecast")


@dataclass
class Data:
    start: date
    end: date                                   # последний день истории
    series: dict = field(default_factory=dict)  # (pid, lid) -> np.array продаж
    stockout: dict = field(default_factory=dict)  # (pid, lid) -> np.array bool
    group_of: dict = field(default_factory=dict)  # pid -> group_id

    @property
    def n(self) -> int:
        return (self.end - self.start).days + 1


def published_model(db: Session) -> ForecastModel:
    m = db.query(ForecastModel).filter(ForecastModel.status == "published").order_by(ForecastModel.version.desc()).first()
    if m is None:
        raise DomainError("Нет опубликованной версии модели прогноза")
    return m


def load(db: Session, start: date, end: date) -> Data:
    d = Data(start, end)
    prods = db.query(Product).filter(Product.active.is_(True)).all()
    d.group_of = {p.id: p.group_id for p in prods}
    locs = [x.id for x in db.query(Location).filter(Location.type.in_(SALE_LOCATIONS), Location.active.is_(True))]
    for pid in d.group_of:
        for lid in locs:
            d.series[(pid, lid)] = np.zeros(d.n)
            d.stockout[(pid, lid)] = np.zeros(d.n, dtype=bool)
    for r in db.query(DailySales.product_id, DailySales.location_id, DailySales.day, DailySales.qty).filter(
            DailySales.day >= start, DailySales.day <= end):
        k = (r.product_id, r.location_id)
        if k in d.series:
            d.series[k][(r.day - start).days] += max(0.0, r.qty)
    for r in db.query(StockoutDay).filter(StockoutDay.day >= start, StockoutDay.day <= end):
        k = (r.product_id, r.location_id)
        if k in d.stockout:
            d.stockout[k][(r.day - start).days] = True
    return d


# ---------------------------------------------------------------- календарные коэффициенты
def _occurrences(e: CalendarEvent, start: date, end: date) -> list[date]:
    if not e.recurring:
        return [e.date] if start <= e.date <= end else []
    out = []
    for y in range(start.year, end.year + 1):
        try:
            d = e.date.replace(year=y)
        except ValueError:      # 29 февраля
            continue
        if start <= d <= end:
            out.append(d)
    return out


def _baseline(arr: np.ndarray, i: int) -> float | None:
    """Обычный уровень дня: среднее того же дня недели за 4 предыдущие недели."""
    vals = [arr[i - 7 * k] for k in range(1, 5) if i - 7 * k >= 0]
    return float(np.mean(vals)) if len(vals) >= 2 else None


def event_coefficients(db: Session, data: Data, until: date) -> tuple[dict, list[dict]]:
    """Коэффициенты по (группа, день) на интервале [data.start, until]. Незаданные — оцениваются
    по истории группы: медиана отношения продаж в день события к обычному уровню."""
    events = db.query(CalendarEvent).all()
    groups = sorted(set(data.group_of.values()))
    gsum = {g: np.zeros(data.n) for g in groups}
    for (pid, _), arr in data.series.items():
        gsum[data.group_of[pid]] += arr
    coef = defaultdict(lambda: 1.0)
    info = []
    for e in events:
        target_groups = [e.group_id] if e.group_id else groups
        for g in target_groups:
            if g not in gsum:
                continue
            c = e.coefficient
            if c is None:
                ratios = []
                for d in _occurrences(e, data.start, data.end):
                    i = (d - data.start).days
                    b = _baseline(gsum[g], i)
                    if b and b > 0:
                        ratios.append(gsum[g][i] / b)
                c = float(np.clip(np.median(ratios), 0.2, 30)) if ratios else 1.0
            for d in _occurrences(e, data.start, until):
                coef[(g, d)] *= c
            info.append({"event": e.name, "date": e.date, "group_id": g, "coefficient": round(c, 2),
                         "estimated": e.coefficient is None})
    return coef, info


# ---------------------------------------------------------------- погода
def weather_betas(db: Session, data: Data, coef: dict) -> dict:
    """Чувствительность продаж группы к отклонению температуры от нормы: log-отношение продаж к обычному
    уровню против аномалии температуры. Учитывается, только если связь значима (|t| > 2, ≥ 60 дней)."""
    known = wx.known_days(db, data.start, data.end)
    if len(known) < 60:
        return {}
    temps = {w.day: w.temp for w in db.query(Weather).filter(Weather.day >= data.start, Weather.day <= data.end)}
    gsum = defaultdict(lambda: np.zeros(data.n))
    for (pid, _), arr in data.series.items():
        gsum[data.group_of[pid]] += arr
    out = {}
    for g, arr in gsum.items():
        xs, ys = [], []
        for i in range(28, data.n):
            d = data.start + timedelta(days=i)
            if d not in temps or coef[(g, d)] != 1.0:
                continue
            b = _baseline(arr, i)
            if not b or b <= 0:
                continue
            xs.append(temps[d] - wx.normal(d))
            ys.append(math.log((arr[i] + 1) / (b + 1)))
        if len(xs) < 60:
            continue
        x, y = np.array(xs), np.array(ys)
        x0 = x - x.mean()
        sxx = float(np.sum(x0 ** 2))
        if sxx <= 0:
            continue
        beta = float(np.sum(x0 * (y - y.mean())) / sxx)
        resid = y - y.mean() - beta * x0
        se = math.sqrt(float(np.sum(resid ** 2)) / max(len(x) - 2, 1) / sxx)
        if se > 0 and abs(beta / se) > 2:
            out[g] = float(np.clip(beta, -0.03, 0.03))
    return out


# ---------------------------------------------------------------- один ряд
def prepare(y: np.ndarray, stockout: np.ndarray, hist_coef: np.ndarray) -> np.ndarray:
    """Очистка истории: дни дефицита — не меньше обычного уровня; затем деление на коэффициенты событий."""
    y = y.astype(float).copy()
    for i in np.flatnonzero(stockout):
        b = _baseline(y, i)
        if b is not None and b > y[i]:
            y[i] = b
    return y / np.maximum(hist_coef, 1e-6)


def forecast_series(y: np.ndarray, h: int, params: dict, algorithm: str) -> dict:
    holdout = int(params.get("holdout", 28))
    cands = tm.candidates_for(y, algorithm)
    algo, test, f_test = tm.select(y, holdout, params, cands)
    try:
        f = tm.ALGOS[algo](y, h, params)
    except Exception:          # сбой модели на ряду — сезонная наивная
        algo, f = "seasonal_naive", tm.seasonal_naive(y, h)
    return {"algorithm": algo, "p50": np.clip(f, 0, None), "profile": tm.error_profile(test, f_test)}


# ---------------------------------------------------------------- расчёт по товарным группам (Р-1)
@dataclass
class GroupJob:
    """Ряды одной товарной группы с общими коэффициентами событий и погоды — единица параллельного расчёта."""
    hist_coef: np.ndarray
    fut_coef: np.ndarray
    weather: np.ndarray
    days: list
    params: dict
    algorithm: str
    series: list = field(default_factory=list)   # (pid, lid, продажи, дни дефицита)


def forecast_group(job: GroupJob) -> tuple[list[dict], dict]:
    """Прогноз всех рядов группы. Не обращается к БД, поэтому выполняется и в отдельном процессе."""
    rows, used = [], defaultdict(int)
    for pid, lid, y_raw, stockout in job.series:
        y = prepare(y_raw, stockout, job.hist_coef)
        first = int(np.argmax(y_raw > 0))          # ряд начинается с первой продажи
        res = forecast_series(y[first:], len(job.days), job.params, job.algorithm)
        used[res["algorithm"]] += 1
        p50 = res["p50"] * job.fut_coef * job.weather
        p80, p95 = tm.quantiles(p50, res["profile"])
        for i, d in enumerate(job.days):
            rows.append({"product_id": pid, "location_id": lid, "day": d, "p50": round(float(p50[i]), 3),
                         "p80": round(float(p80[i]), 3), "p95": round(float(p95[i]), 3),
                         "sigma": round(res["profile"]["sigma"], 4), "event_coef": round(float(job.fut_coef[i]), 4),
                         "algorithm": res["algorithm"]})
    return rows, dict(used)


def _workers(n_jobs: int) -> int:
    """Число процессов: FLORAPLAN_FORECAST_WORKERS, но не больше числа групп. 0 — половина логических
    процессоров (≈ число физических ядер: на гиперпоточных ядрах расчёт не ускоряется, а мешает)."""
    w = get_settings().forecast_workers or max(1, (os.cpu_count() or 1) // 2)
    return max(1, min(w, n_jobs))


def _map(fn, jobs: list, workers: int):
    if workers <= 1:
        return map(fn, jobs)
    try:
        # spawn, а не fork: сервер и планировщик многопоточные, fork в них может зависнуть
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
            return list(ex.map(fn, jobs))
    except (OSError, BrokenProcessPool) as e:   # процессы недоступны — считаем в одном
        log.warning("параллельный расчёт прогноза недоступен (%s), расчёт в одном процессе", e)
        return map(fn, jobs)


# ---------------------------------------------------------------- расчёт
def compute(db: Session, base: date, h: int, model: ForecastModel, history_days: int) -> tuple[list[dict], dict]:
    """Прогноз всех рядов на [base, base + h). История — до base − 1."""
    start = base - timedelta(days=history_days)
    data = load(db, start, base - timedelta(days=1))
    end_f = base + timedelta(days=h - 1)
    coef, info = event_coefficients(db, data, end_f)
    params = model.params or {}
    betas = weather_betas(db, data, coef) if params.get("use_weather", True) else {}
    temps = wx.temps(db, base, end_f)
    fut = [base + timedelta(days=i) for i in range(h)]
    hist_days = [data.start + timedelta(days=i) for i in range(data.n)]
    recent = 56
    jobs = {}
    for g in set(data.group_of.values()):
        jobs[g] = GroupJob(np.array([coef[(g, d)] for d in hist_days]),
                           np.array([coef[(g, d)] for d in fut]),
                           np.array([math.exp(betas.get(g, 0.0) * (temps[d] - wx.normal(d))) for d in fut]),
                           fut, params, model.algorithm)
    for (pid, lid), y_raw in data.series.items():
        if y_raw[-recent:].sum() <= 0:
            continue          # давно не продавался — прогноз не строится
        jobs[data.group_of[pid]].series.append((pid, lid, y_raw, data.stockout[(pid, lid)]))
    jobs = [j for j in jobs.values() if j.series]
    rows, used = [], defaultdict(int)
    workers = _workers(len(jobs))
    for part_rows, part_used in _map(forecast_group, jobs, workers):
        rows.extend(part_rows)
        for k, v in part_used.items():
            used[k] += v
    return rows, {"algorithms": dict(used), "events": info, "weather_betas": betas, "history_start": start,
                  "workers": workers}


def run(db: Session, base: date | None = None, trigger: str = "manual", user=None) -> ForecastRun:
    """Расчёт и сохранение прогноза (ежедневно в 03:00 или по запросу). При ошибке остаётся предыдущий
    прогноз, аналитик видит предупреждение в журнале (ПР 7-8, поток 4а)."""
    base = base or date.today()
    model = published_model(db)
    h = int(appsettings.get(db, "forecast_horizon"))
    r = ForecastRun(base_date=base, model_id=model.id, trigger=trigger, started_at=datetime.now())
    db.add(r)
    db.commit()
    t0 = time.time()
    try:
        rows, meta = compute(db, base, h, model, int(appsettings.get(db, "history_days")))
        db.commit()   # закончить читающую транзакцию: запись результата — в новой, без устаревшего снимка
        if rows:
            db.execute(insert(Forecast), [dict(x, run_id=r.id) for x in rows])
        r.series = len({(x["product_id"], x["location_id"]) for x in rows})
        r.status = "ok"
        algos = ", ".join(f"{tm_name(k)}: {v}" for k, v in sorted(meta["algorithms"].items()))
        r.message = (f"рядов {r.series}, горизонт {h} дн., {time.time() - t0:.1f} с, процессов {meta['workers']}; "
                     f"модели — {algos or 'нет'}")
        _cleanup(db, base)
    except Exception as e:
        db.rollback()
        r = db.get(ForecastRun, r.id)
        r.status = "failed"
        r.message = f"ошибка расчёта, действует предыдущий прогноз: {e}"
        audit.integration(db, "forecast", r.message, status="error")
    r.finished_at = datetime.now()
    audit.log(db, user, "Расчёт прогноза спроса", "forecast_run", r.id, r.message)
    db.commit()
    return r


def tm_name(code: str) -> str:
    from ..models import ALGORITHMS
    return ALGORITHMS.get(code, code)


def _cleanup(db: Session, base: date, keep_days: int = 400) -> None:
    old = [x.id for x in db.query(ForecastRun.id).filter(ForecastRun.base_date < base - timedelta(days=keep_days))]
    if old:
        db.execute(delete(Forecast).where(Forecast.run_id.in_(old)))
        db.execute(delete(ForecastRun).where(ForecastRun.id.in_(old)))


def current_run(db: Session) -> ForecastRun | None:
    return (db.query(ForecastRun).filter(ForecastRun.status == "ok")
            .order_by(ForecastRun.base_date.desc(), ForecastRun.id.desc()).first())


# ---------------------------------------------------------------- оценка версии модели (С-17)
def evaluate(db: Session, model: ForecastModel, holdout: int = 28, today: date | None = None) -> dict:
    """Ретро-прогноз: история до (сегодня − holdout), прогноз на holdout дней, сравнение с фактом
    по неделям и товарным группам — WAPE и bias недельного прогноза."""
    today = today or date.today()
    base = today - timedelta(days=holdout)
    rows, _ = compute(db, base, holdout, model, int(appsettings.get(db, "history_days")))
    group_of = {p.id: p.group_id for p in db.query(Product)}
    fc = defaultdict(float)
    for x in rows:
        fc[(group_of[x["product_id"]], (x["day"] - base).days // 7)] += x["p50"]
    act = defaultdict(float)
    locs = [x.id for x in db.query(Location).filter(Location.type.in_(SALE_LOCATIONS))]
    for r in db.query(DailySales).filter(DailySales.day >= base, DailySales.day < today,
                                         DailySales.location_id.in_(locs)):
        if r.product_id in group_of:
            act[(group_of[r.product_id], (r.day - base).days // 7)] += r.qty
    keys = sorted(set(fc) | set(act))
    weeks = holdout // 7
    keys = [k for k in keys if k[1] < weeks]
    a = [act[k] for k in keys]
    f = [fc[k] for k in keys]
    per_group = {}
    for g in sorted({k[0] for k in keys}):
        ks = [k for k in keys if k[0] == g]
        per_group[g] = {"wape": tm.wape([act[k] for k in ks], [fc[k] for k in ks]),
                        "actual": sum(act[k] for k in ks), "forecast": round(sum(fc[k] for k in ks), 1)}
    return {"wape": tm.wape(a, f), "bias": tm.bias(a, f), "period": [base, today - timedelta(days=1)],
            "groups": per_group}
