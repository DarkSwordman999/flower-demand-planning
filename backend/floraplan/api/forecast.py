"""Прогнозирование спроса (П-5, П-14, С-6, С-17): расчёт, просмотр, версии модели, погода."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..errors import DomainError, NotFound
from ..models import (ALGORITHMS, MODEL_STATUSES, DailySales, Forecast, ForecastModel, ForecastRun, Location, Product,
                      User, Weather)
from ..security import require
from ..services import forecasting as fs
from ..services import weather as wx

router = APIRouter(prefix="/api/forecast", tags=["Прогнозирование спроса"])
viewers = require("buyer", "analyst", "director", "florist", "shop_manager")
analysts = require("analyst")


def run_out(r: ForecastRun) -> dict:
    return {"id": r.id, "base_date": r.base_date, "started_at": r.started_at, "finished_at": r.finished_at,
            "status": r.status, "series": r.series, "message": r.message, "trigger": r.trigger, "model_id": r.model_id}


@router.post("/run", summary="Рассчитать прогноз сейчас")
def run_now(me: User = Depends(require("analyst", "buyer")), db: Session = Depends(get_db)):
    r = fs.run(db, trigger="manual", user=me)
    if r.status != "ok":
        raise DomainError(r.message, status=500)
    return run_out(r)


@router.get("/runs")
def runs(limit: int = 30, _: User = Depends(viewers), db: Session = Depends(get_db)):
    return [run_out(r) for r in db.query(ForecastRun).order_by(ForecastRun.id.desc()).limit(min(limit, 500))]


@router.get("/status")
def status(_: User = Depends(viewers), db: Session = Depends(get_db)):
    """Действующий прогноз и предупреждение, если он устарел (прогноз не рассчитан — используется прежний)."""
    cur = fs.current_run(db)
    last = db.query(ForecastRun).order_by(ForecastRun.id.desc()).first()
    warn = ""
    if cur is None:
        warn = "Прогноз ещё не рассчитан"
    elif cur.base_date < date.today():
        warn = f"Прогноз на сегодня не рассчитан — используется прогноз от {cur.base_date:%d.%m.%Y}"
    return {"current": run_out(cur) if cur else None, "last": run_out(last) if last else None, "warning": warn}


def _sale_locations(db: Session, location_id: int | None) -> list[int]:
    if location_id:
        return [location_id]
    return [x.id for x in db.query(Location).filter(Location.type.in_(fs.SALE_LOCATIONS))]


@router.get("/series", summary="Факт продаж и прогноз P50/P80/P95 по товару (и точке)")
def series(product_id: int, location_id: int | None = None, history: int = 56, _: User = Depends(viewers),
           db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None:
        raise NotFound("Товар не найден")
    locs = _sale_locations(db, location_id)
    cur = fs.current_run(db)
    start = (cur.base_date if cur else date.today()) - timedelta(days=history)
    hist = defaultdict(float)
    for r in db.query(DailySales.day, func.sum(DailySales.qty)).filter(
            DailySales.product_id == product_id, DailySales.location_id.in_(locs), DailySales.day >= start
    ).group_by(DailySales.day):
        hist[r[0]] += r[1]
    fc = defaultdict(lambda: [0.0, 0.0, 0.0])
    algos = set()
    if cur:
        for f in db.query(Forecast).filter(Forecast.run_id == cur.id, Forecast.product_id == product_id,
                                           Forecast.location_id.in_(locs)):
            v = fc[f.day]
            v[0] += f.p50
            v[1] += f.p80
            v[2] += f.p95
            algos.add(f.algorithm)
    days = sorted(set(hist) | set(fc))
    if days:
        d, out = days[0], []
        while d <= days[-1]:
            row = {"day": d, "actual": hist.get(d) if d < (cur.base_date if cur else date.today()) else None}
            if d in fc:
                row.update(p50=round(fc[d][0], 2), p80=round(fc[d][1], 2), p95=round(fc[d][2], 2))
            out.append(row)
            d += timedelta(days=1)
    else:
        out = []
    return {"product": p.name, "unit": p.unit, "algorithms": [ALGORITHMS.get(a, a) for a in sorted(algos)],
            "run": run_out(cur) if cur else None, "points": out}


@router.get("/table", summary="Прогноз на горизонт по товарам: суммы P50/P80/P95")
def table(location_id: int | None = None, group_id: int | None = None, _: User = Depends(viewers),
          db: Session = Depends(get_db)):
    cur = fs.current_run(db)
    if cur is None:
        return {"run": None, "rows": []}
    locs = _sale_locations(db, location_id)
    q = db.query(Forecast.product_id, func.sum(Forecast.p50), func.sum(Forecast.p80), func.sum(Forecast.p95),
                 func.max(Forecast.algorithm)).filter(Forecast.run_id == cur.id, Forecast.location_id.in_(locs))
    agg = {r[0]: r[1:] for r in q.group_by(Forecast.product_id)}
    week = {r[0]: r[1] for r in db.query(Forecast.product_id, func.sum(Forecast.p50)).filter(
        Forecast.run_id == cur.id, Forecast.location_id.in_(locs),
        Forecast.day < cur.base_date + timedelta(days=7)).group_by(Forecast.product_id)}
    prods = db.query(Product).filter(Product.id.in_(list(agg)))
    if group_id:
        prods = prods.filter(Product.group_id == group_id)
    rows = [{"product_id": p.id, "product": p.name, "group": p.group.name, "unit": p.unit,
             "week_p50": round(week.get(p.id, 0), 1), "p50": round(agg[p.id][0], 1), "p80": round(agg[p.id][1], 1),
             "p95": round(agg[p.id][2], 1), "algorithm": ALGORITHMS.get(agg[p.id][3], agg[p.id][3])}
            for p in prods]
    return {"run": run_out(cur), "rows": sorted(rows, key=lambda r: -r["p50"])}


# ------------------------------------------------------------------ версии модели (С-17, П-14)
def model_out(m: ForecastModel) -> dict:
    return {"id": m.id, "version": m.version, "algorithm": m.algorithm, "algorithm_name": ALGORITHMS.get(m.algorithm),
            "params": m.params, "wape": m.wape, "bias": m.bias, "details": m.details, "status": m.status,
            "status_name": MODEL_STATUSES.get(m.status), "created_at": m.created_at, "published_at": m.published_at,
            "comment": m.comment}


@router.get("/models")
def models(_: User = Depends(viewers), db: Session = Depends(get_db)):
    return [model_out(m) for m in db.query(ForecastModel).order_by(ForecastModel.version.desc())]


class ModelIn(BaseModel):
    algorithm: str = "auto"
    holdout: int = Field(default=28, ge=14, le=56)
    trend: bool = False
    use_weather: bool = True
    comment: str = ""


def _evaluate_pair(db: Session, cand: ForecastModel) -> tuple[dict, dict]:
    pub = fs.published_model(db)
    ev_c = fs.evaluate(db, cand)
    ev_p = fs.evaluate(db, pub) if pub.id != cand.id else ev_c
    return ev_c, ev_p


def _js(ev: dict) -> dict:
    return {"period": [str(ev["period"][0]), str(ev["period"][1])],
            "groups": {str(k): v for k, v in ev["groups"].items()}, "wape": ev["wape"], "bias": ev["bias"]}


@router.post("/models", summary="Пересчитать параметры: новая версия-кандидат с оценкой на отложенном периоде")
def create_model(body: ModelIn, me: User = Depends(analysts), db: Session = Depends(get_db)):
    if body.algorithm not in ALGORITHMS:
        raise DomainError("Неизвестный алгоритм")
    ver = (db.query(func.max(ForecastModel.version)).scalar() or 0) + 1
    m = ForecastModel(version=ver, algorithm=body.algorithm, status="candidate", comment=body.comment,
                      params={"season": 7, "holdout": body.holdout, "trend": body.trend, "use_weather": body.use_weather})
    db.add(m)
    db.flush()
    ev_c, ev_p = _evaluate_pair(db, m)
    m.wape, m.bias = ev_c["wape"], ev_c["bias"]
    m.details = {"candidate": _js(ev_c), "published": _js(ev_p), "published_version": fs.published_model(db).version}
    audit.log(db, me, "Создана версия модели прогноза", "forecast_model", m.version,
              f"WAPE {m.wape:.3f} против действующей {ev_p['wape']:.3f}" if m.wape is not None and ev_p["wape"] is not None else "")
    db.commit()
    return model_out(m)


@router.post("/models/{mid}/publish", summary="Опубликовать версию (только если WAPE не хуже действующей)")
def publish(mid: int, me: User = Depends(analysts), db: Session = Depends(get_db)):
    m = db.get(ForecastModel, mid)
    if m is None:
        raise NotFound("Версия модели не найдена")
    if m.status != "candidate":
        raise DomainError("Опубликовать можно только версию-кандидат")
    ev_c, ev_p = _evaluate_pair(db, m)
    m.wape, m.bias = ev_c["wape"], ev_c["bias"]
    if ev_c["wape"] is None or (ev_p["wape"] is not None and ev_c["wape"] > ev_p["wape"] + 1e-9):
        m.status = "rejected"
        audit.log(db, me, "Версия модели отклонена", "forecast_model", m.version,
                  f"WAPE {ev_c['wape']} хуже действующей {ev_p['wape']}")
        db.commit()
        raise DomainError(f"Версия {m.version} не опубликована: WAPE {_pct(ev_c['wape'])} хуже действующей "
                          f"{_pct(ev_p['wape'])} на том же периоде")
    for old in db.query(ForecastModel).filter(ForecastModel.status == "published"):
        old.status = "archived"
    m.status = "published"
    m.published_at = datetime.now()
    audit.log(db, me, "Опубликована версия модели прогноза", "forecast_model", m.version, f"WAPE {_pct(m.wape)}")
    db.commit()
    return model_out(m)


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f} %"


# ------------------------------------------------------------------ погода
@router.get("/weather")
def weather(_: User = Depends(viewers), db: Session = Depends(get_db)):
    start = date.today()
    t = wx.temps(db, start, start + timedelta(days=13))
    src = {w.day: w.source for w in db.query(Weather).filter(Weather.day >= start)}
    return [{"day": d, "temp": round(v, 1), "normal": round(wx.normal(d), 1), "source": src.get(d, "climate")}
            for d, v in t.items()]


@router.post("/weather/refresh")
def weather_refresh(me: User = Depends(analysts), db: Session = Depends(get_db)):
    res = wx.fetch(db)
    audit.log(db, me, "Обновление прогноза погоды", "weather", "", str(res))
    db.commit()
    return res
