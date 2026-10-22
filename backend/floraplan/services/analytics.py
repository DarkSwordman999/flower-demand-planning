"""Аналитика и отчётность (П-13, С-16; ПР 7-8 «Сформировать аналитический отчёт»).

Каждый отчёт возвращает {"title", "columns": [(ключ, заголовок)], "rows": [...], "totals": {...}} — одна форма
для экрана и для выгрузки в XLSX."""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import statistics

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..errors import DomainError
from ..models import (ORDER_STATUSES, Batch, Forecast, ForecastRun, Location, Product, PurchaseOrder, Sale, SaleLine,
                      StockMove, Supplier, WriteOff, WriteOffReason)
from . import tsmodels as tm

GROUP_BY = {"product": "Товар", "group": "Группа", "location": "Место", "day": "День", "week": "Неделя",
            "month": "Месяц"}


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    date_to = date_to or date.today()
    date_from = date_from or date_to - timedelta(days=29)
    if date_from > date_to:
        raise DomainError("Начало периода позже конца")
    if (date_to - date_from).days > 3 * 366:
        raise DomainError("Период отчёта — не больше трёх лет")
    return date_from, date_to


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-Н{w:02d}"


def _key(gb: str, product: Product, loc_name: str, day: date) -> str:
    return {"product": lambda: product.name, "group": lambda: product.group.name, "location": lambda: loc_name,
            "day": lambda: day.isoformat(), "week": lambda: _week(day),
            "month": lambda: f"{day.year}-{day.month:02d}"}[gb]()


def _refs(db: Session):
    prods = {p.id: p for p in db.query(Product).all()}
    for p in prods.values():
        _ = p.group
    locs = {x.id: x.name for x in db.query(Location).all()}
    return prods, locs


def _check_gb(gb: str):
    if gb not in GROUP_BY:
        raise DomainError("Группировка: " + ", ".join(GROUP_BY))


# ---------------------------------------------------------------- продажи
def sales(db: Session, date_from=None, date_to=None, group_by="group", location_id=None) -> dict:
    _check_gb(group_by)
    a, b = _period(date_from, date_to)
    prods, locs = _refs(db)
    q = (db.query(SaleLine.product_id, Sale.location_id, Sale.day, func.sum(SaleLine.qty),
                  func.sum(SaleLine.qty * SaleLine.price - SaleLine.discount), func.sum(SaleLine.qty * SaleLine.cost),
                  func.count(func.distinct(Sale.id)))
         .join(Sale).filter(Sale.day >= a, Sale.day <= b))
    if location_id:
        q = q.filter(Sale.location_id == location_id)
    agg = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0, "cost": 0.0, "receipts": 0})
    for pid, lid, day, qty, rev, cost, n in q.group_by(SaleLine.product_id, Sale.location_id, Sale.day):
        r = agg[_key(group_by, prods[pid], locs[lid], day)]
        r["qty"] += qty or 0
        r["revenue"] += rev or 0
        r["cost"] += cost or 0
        r["receipts"] += n or 0
    rows = []
    for k, r in agg.items():
        margin = r["revenue"] - r["cost"]
        rows.append({"key": k, "qty": round(r["qty"], 1), "revenue": round(r["revenue"], 2),
                     "cost": round(r["cost"], 2), "margin": round(margin, 2),
                     "margin_pct": round(margin / r["revenue"] * 100, 1) if r["revenue"] else None})
    rows.sort(key=lambda r: r["key"] if group_by in ("day", "week", "month") else -r["revenue"])
    tot_rev = sum(r["revenue"] for r in rows)
    tot_cost = sum(r["cost"] for r in rows)
    return {"title": f"Продажи за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", GROUP_BY[group_by]), ("qty", "Количество"), ("revenue", "Выручка, руб."),
                        ("cost", "Себестоимость, руб."), ("margin", "Маржа, руб."), ("margin_pct", "Маржа, %")],
            "rows": rows, "totals": {"key": "Итого", "qty": round(sum(r["qty"] for r in rows), 1),
                                     "revenue": round(tot_rev, 2), "cost": round(tot_cost, 2),
                                     "margin": round(tot_rev - tot_cost, 2),
                                     "margin_pct": round((tot_rev - tot_cost) / tot_rev * 100, 1) if tot_rev else None}}


# ---------------------------------------------------------------- списания
def received_cost(db: Session, a: date, b: date) -> float:
    v = db.query(func.coalesce(func.sum(StockMove.qty * StockMove.cost), 0.0)).filter(
        StockMove.kind == "receipt", StockMove.day >= a, StockMove.day <= b).scalar()
    return float(v)


def writeoffs(db: Session, date_from=None, date_to=None, group_by="group", location_id=None) -> dict:
    if group_by not in GROUP_BY and group_by != "reason":
        raise DomainError("Группировка: " + ", ".join(list(GROUP_BY) + ["reason"]))
    a, b = _period(date_from, date_to)
    prods, locs = _refs(db)
    reasons = {r.id: r.name for r in db.query(WriteOffReason)}
    q = (db.query(WriteOff.reason_id, Batch.product_id, Batch.location_id, WriteOff.ts, WriteOff.qty, WriteOff.cost)
         .join(Batch, WriteOff.batch_id == Batch.id)
         .filter(WriteOff.ts >= datetime.combine(a, time.min), WriteOff.ts <= datetime.combine(b, time.max)))
    if location_id:
        q = q.filter(Batch.location_id == location_id)
    agg = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "acts": 0})
    for rid, pid, lid, ts, qty, cost in q:
        k = reasons[rid] if group_by == "reason" else _key(group_by, prods[pid], locs[lid], ts.date())
        agg[k]["qty"] += qty
        agg[k]["cost"] += qty * cost
        agg[k]["acts"] += 1
    purchased = received_cost(db, a, b)
    rows = [{"key": k, "qty": round(v["qty"], 1), "cost": round(v["cost"], 2), "items": v["acts"],
             "share_pct": round(v["cost"] / purchased * 100, 2) if purchased else None}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["cost"])]
    total = sum(r["cost"] for r in rows)
    return {"title": f"Списания за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", "Причина" if group_by == "reason" else GROUP_BY[group_by]), ("qty", "Количество"),
                        ("cost", "Себестоимость, руб."), ("items", "Позиций"),
                        ("share_pct", "Доля от закупок, %")],
            "rows": rows,
            "totals": {"key": "Итого", "qty": round(sum(r["qty"] for r in rows), 1), "cost": round(total, 2),
                       "items": sum(r["items"] for r in rows),
                       "share_pct": round(total / purchased * 100, 2) if purchased else None},
            "note": f"Закуплено (оприходовано) за период: {purchased:,.2f} руб.".replace(",", " ")}


# ---------------------------------------------------------------- оборачиваемость
def turnover(db: Session, date_from=None, date_to=None, group_by="product", location_id=None) -> dict:
    """Средний запас (по движениям на конец каждого дня) / среднедневные продажи = оборачиваемость в днях."""
    if group_by not in ("product", "group", "location"):
        raise DomainError("Группировка: product, group или location")
    a, b = _period(date_from, date_to)
    ndays = (b - a).days + 1
    prods, locs = _refs(db)
    mq = db.query(StockMove.product_id, StockMove.location_id, StockMove.day, func.sum(StockMove.qty)).filter(
        StockMove.day <= b)
    if location_id:
        mq = mq.filter(StockMove.location_id == location_id)
    moves = defaultdict(list)
    for pid, lid, day, qty in mq.group_by(StockMove.product_id, StockMove.location_id, StockMove.day):
        moves[(pid, lid)].append((day, qty))
    stock_sum = defaultdict(float)
    for k, lst in moves.items():
        lst.sort()
        days = [d for d, _ in lst]
        cum, acc = [], 0.0
        for _, q in lst:
            acc += q
            cum.append(acc)
        total = 0.0
        for i in range(ndays):
            d = a + timedelta(days=i)
            j = bisect_right(days, d) - 1
            total += max(0.0, cum[j]) if j >= 0 else 0.0
        stock_sum[k] = total / ndays
    sq = (db.query(SaleLine.product_id, Sale.location_id, func.sum(SaleLine.qty)).join(Sale)
          .filter(Sale.day >= a, Sale.day <= b))
    if location_id:
        sq = sq.filter(Sale.location_id == location_id)
    sold = {(p, l): q for p, l, q in sq.group_by(SaleLine.product_id, Sale.location_id)}
    agg = defaultdict(lambda: {"avg_stock": 0.0, "sold": 0.0})
    for k in set(stock_sum) | set(sold):
        pid, lid = k
        key = {"product": prods[pid].name, "group": prods[pid].group.name, "location": locs[lid]}[group_by]
        agg[key]["avg_stock"] += stock_sum.get(k, 0.0)
        agg[key]["sold"] += sold.get(k, 0.0) or 0.0
    rows = []
    for k, v in agg.items():
        per_day = v["sold"] / ndays
        rows.append({"key": k, "avg_stock": round(v["avg_stock"], 1), "sold": round(v["sold"], 1),
                     "per_day": round(per_day, 2),
                     "turnover_days": round(v["avg_stock"] / per_day, 1) if per_day > 0 else None})
    rows.sort(key=lambda r: -(r["turnover_days"] or 1e9))
    s_avg = sum(r["avg_stock"] for r in rows)
    s_sold = sum(r["sold"] for r in rows)
    return {"title": f"Оборачиваемость за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", GROUP_BY[group_by]), ("avg_stock", "Средний запас"), ("sold", "Продано"),
                        ("per_day", "Продаж в день"), ("turnover_days", "Оборачиваемость, дней")],
            "rows": rows, "totals": {"key": "Итого", "avg_stock": round(s_avg, 1), "sold": round(s_sold, 1),
                                     "per_day": round(s_sold / ndays, 2),
                                     "turnover_days": round(s_avg / (s_sold / ndays), 1) if s_sold else None}}


# ---------------------------------------------------------------- точность прогноза
def accuracy(db: Session, date_from=None, date_to=None, group_by="group", location_id=None) -> dict:
    """WAPE и bias недельного прогноза: для каждого дня берётся прогноз последнего расчёта, сделанного
    не позже этого дня; сравнение по неделям с фактом продаж."""
    if group_by not in ("group", "product", "week"):
        raise DomainError("Группировка: group, product или week")
    a, b = _period(date_from, date_to)
    b = min(b, date.today() - timedelta(days=1))
    prods, _ = _refs(db)
    runs = sorted((r.base_date, r.id) for r in db.query(ForecastRun).filter(
        ForecastRun.status == "ok", ForecastRun.base_date <= b, ForecastRun.base_date >= a - timedelta(days=30)))
    if not runs:
        return {"title": "Точность прогноза", "columns": [("key", "—")], "rows": [], "totals": {},
                "note": "За период нет рассчитанных прогнозов"}
    bases = [x[0] for x in runs]
    fc = defaultdict(float)
    act = defaultdict(float)
    by_run = defaultdict(list)
    d = a
    while d <= b:
        j = bisect_right(bases, d) - 1
        if j >= 0:
            by_run[runs[j][1]].append(d)
        d += timedelta(days=1)
    for rid, days in by_run.items():
        q = db.query(Forecast.product_id, Forecast.day, func.sum(Forecast.p50)).filter(
            Forecast.run_id == rid, Forecast.day.in_(days))
        if location_id:
            q = q.filter(Forecast.location_id == location_id)
        for pid, day, v in q.group_by(Forecast.product_id, Forecast.day):
            fc[(pid, day)] += v
    covered = {d for ds in by_run.values() for d in ds}
    sq = (db.query(SaleLine.product_id, Sale.day, func.sum(SaleLine.qty)).join(Sale)
          .filter(Sale.day >= a, Sale.day <= b))
    if location_id:
        sq = sq.filter(Sale.location_id == location_id)
    else:
        sale_locs = [x.id for x in db.query(Location).filter(Location.type.in_(("salon", "online")))]
        sq = sq.filter(Sale.location_id.in_(sale_locs))
    for pid, day, v in sq.group_by(SaleLine.product_id, Sale.day):
        if day in covered:
            act[(pid, day)] += v
    cell_f, cell_a = defaultdict(float), defaultdict(float)
    for (pid, day), v in fc.items():
        if pid in prods:
            cell_f[(_acc_key(group_by, prods[pid]), _week(day))] += v
    for (pid, day), v in act.items():
        if pid in prods:
            cell_a[(_acc_key(group_by, prods[pid]), _week(day))] += v
    keys = set(cell_f) | set(cell_a)
    rows = []
    groups = sorted({k[0] for k in keys}) if group_by != "week" else sorted({k[1] for k in keys})
    for gkey in groups:
        ks = [k for k in keys if (k[0] if group_by != "week" else k[1]) == gkey]
        A = [cell_a[k] for k in ks]
        F = [cell_f[k] for k in ks]
        w, bs = tm.wape(A, F), tm.bias(A, F)
        rows.append({"key": gkey, "actual": round(sum(A), 1), "forecast": round(sum(F), 1),
                     "wape_pct": round(w * 100, 1) if w is not None else None,
                     "bias_pct": round(bs * 100, 1) if bs is not None else None})
    A = [cell_a[k] for k in keys]
    F = [cell_f[k] for k in keys]
    w, bs = tm.wape(A, F), tm.bias(A, F)
    return {"title": f"Точность недельного прогноза за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", {"group": "Группа", "product": "Товар", "week": "Неделя"}[group_by]),
                        ("actual", "Факт"), ("forecast", "Прогноз P50"), ("wape_pct", "WAPE, %"),
                        ("bias_pct", "Смещение, %")],
            "rows": rows, "totals": {"key": "Итого", "actual": round(sum(A), 1), "forecast": round(sum(F), 1),
                                     "wape_pct": round(w * 100, 1) if w is not None else None,
                                     "bias_pct": round(bs * 100, 1) if bs is not None else None},
            "note": "Критерий успеха проекта: WAPE недельного прогноза по основным группам не более 25 %"}


def _acc_key(gb: str, p: Product) -> str:
    return p.group.name if gb in ("group", "week") else p.name


# ---------------------------------------------------------------- ABC / XYZ
def abcxyz(db: Session, date_from=None, date_to=None, group_by="product", location_id=None) -> dict:
    a, b = _period(date_from or (date_to or date.today()) - timedelta(days=89), date_to)
    prods, _ = _refs(db)
    q = (db.query(SaleLine.product_id, Sale.day, func.sum(SaleLine.qty),
                  func.sum(SaleLine.qty * SaleLine.price - SaleLine.discount))
         .join(Sale).filter(Sale.day >= a, Sale.day <= b))
    if location_id:
        q = q.filter(Sale.location_id == location_id)
    rev = defaultdict(float)
    weekly = defaultdict(lambda: defaultdict(float))
    for pid, day, qty, r in q.group_by(SaleLine.product_id, Sale.day):
        rev[pid] += r or 0
        weekly[pid][(day - a).days // 7] += qty or 0
    nweeks = max(1, ((b - a).days + 1) // 7)
    total = sum(max(v, 0) for v in rev.values())
    rows, acc = [], 0.0
    for pid, r in sorted(rev.items(), key=lambda kv: -kv[1]):
        share = acc / total if total else 1
        abc = "A" if share < 0.8 else ("B" if share < 0.95 else "C")
        acc += max(r, 0)
        w = [weekly[pid].get(i, 0.0) for i in range(nweeks)]
        mean = statistics.mean(w)
        cv = statistics.pstdev(w) / mean if mean > 0 else None
        xyz = "Z" if cv is None or cv > 0.25 else ("Y" if cv > 0.10 else "X")
        rows.append({"key": prods[pid].name, "group": prods[pid].group.name, "revenue": round(r, 2),
                     "share_pct": round(r / total * 100, 2) if total else None, "abc": abc,
                     "cv_pct": round(cv * 100, 1) if cv is not None else None, "xyz": xyz, "class": abc + xyz})
    return {"title": f"ABC/XYZ-анализ ассортимента за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", "Товар"), ("group", "Группа"), ("revenue", "Выручка, руб."), ("share_pct", "Доля, %"),
                        ("abc", "ABC"), ("cv_pct", "Вариация спроса, %"), ("xyz", "XYZ"), ("class", "Класс")],
            "rows": rows, "totals": {"key": "Итого", "revenue": round(total, 2)},
            "note": "ABC — по выручке (A — 80 %, B — 15 %, C — 5 %); XYZ — по вариации недельных продаж "
                    "(X ≤ 10 %, Y ≤ 25 %, Z — больше)"}


# ---------------------------------------------------------------- закупки
def purchases(db: Session, date_from=None, date_to=None, group_by="supplier", location_id=None) -> dict:
    a, b = _period(date_from, date_to)
    q = (db.query(PurchaseOrder).join(Supplier)
         .filter(PurchaseOrder.order_date >= a, PurchaseOrder.order_date <= b))
    agg = defaultdict(lambda: {"orders": 0, "sum": 0.0, "received": 0.0, "ordered_qty": 0.0, "received_qty": 0.0})
    for o in q:
        k = o.supplier.name if group_by == "supplier" else ORDER_STATUSES[o.status]
        r = agg[k]
        r["orders"] += 1
        if o.status != "cancelled":
            r["sum"] += o.total
        for ln in o.lines:
            if ln.received_qty is not None:
                r["received"] += ln.received_qty * ln.price
                r["received_qty"] += ln.received_qty
                r["ordered_qty"] += ln.ordered_qty
    rows = [{"key": k, "orders": v["orders"], "sum": round(v["sum"], 2), "received": round(v["received"], 2),
             "fill_pct": round(v["received_qty"] / v["ordered_qty"] * 100, 1) if v["ordered_qty"] else None}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["sum"])]
    return {"title": f"Закупки за {a:%d.%m.%Y}–{b:%d.%m.%Y}",
            "columns": [("key", "Поставщик" if group_by == "supplier" else "Статус"), ("orders", "Заказов"),
                        ("sum", "Сумма заказов, руб."), ("received", "Принято на сумму, руб."),
                        ("fill_pct", "Выполнение поставок, %")],
            "rows": rows, "totals": {"key": "Итого", "orders": sum(r["orders"] for r in rows),
                                     "sum": round(sum(r["sum"] for r in rows), 2),
                                     "received": round(sum(r["received"] for r in rows), 2)}}


REPORTS = {"sales": sales, "writeoffs": writeoffs, "turnover": turnover, "accuracy": accuracy, "abcxyz": abcxyz,
           "purchases": purchases}
TITLES = {"sales": "Продажи", "writeoffs": "Списания", "turnover": "Оборачиваемость", "accuracy": "Точность прогноза",
          "abcxyz": "ABC/XYZ-анализ", "purchases": "Закупки"}
