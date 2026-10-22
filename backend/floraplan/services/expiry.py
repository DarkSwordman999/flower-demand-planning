"""Управление сроками и уценкой (П-9, С-12; ПР 7-8 «Уценить или списать партию»)."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .. import appsettings, audit
from ..errors import DomainError, NotFound
from ..models import Batch, Forecast, Location, Markdown, User
from . import forecasting as fs
from . import inventory as inv


def _forecast(db: Session, product_ids: set[int], location_ids: set[int], until: date) -> dict:
    run = fs.current_run(db)
    out = defaultdict(dict)
    if run is None or not product_ids:
        return out
    for f in db.query(Forecast).filter(Forecast.run_id == run.id, Forecast.product_id.in_(product_ids),
                                       Forecast.location_id.in_(location_ids), Forecast.day <= until):
        out[(f.product_id, f.location_id)][f.day] = f.p50
    return out


def recommendations(db: Session, location_id: int | None = None, today: date | None = None) -> list[dict]:
    """Партии в точках продаж, у которых до «годен до» осталось не больше N дней: ожидаемые продажи до
    истечения срока (прогноз P50, FEFO среди партий товара) и рекомендуемая скидка 10–50 %."""
    today = today or date.today()
    s = appsettings.get_all(db)
    n, lo, hi = int(s["expiring_days"]), float(s["markdown_min"]), float(s["markdown_max"])
    sale_locs = {x.id for x in db.query(Location).filter(Location.type.in_(fs.SALE_LOCATIONS))}
    if location_id:
        sale_locs &= {location_id}
    q = (db.query(Batch).options(joinedload(Batch.product), joinedload(Batch.location))
         .filter(Batch.qty > 1e-9, Batch.location_id.in_(sale_locs), Batch.expiry_date >= today)
         .order_by(Batch.expiry_date, Batch.id))
    all_b = q.all()
    soon = [b for b in all_b if (b.expiry_date - today).days <= n]
    fc = _forecast(db, {b.product_id for b in soon}, {b.location_id for b in soon}, today + timedelta(days=n))
    by_key = defaultdict(list)
    for b in all_b:
        by_key[(b.product_id, b.location_id)].append(b)
    out = []
    for b in soon:
        days = fc.get((b.product_id, b.location_id), {})
        # спрос, достающийся партии: дни до её срока минус то, что заберут партии с более ранним сроком
        ahead = sum(x.available for x in by_key[(b.product_id, b.location_id)]
                    if (x.expiry_date, x.id) < (b.expiry_date, b.id))
        demand = sum(v for d, v in days.items() if today <= d <= b.expiry_date)
        expected = max(0.0, min(b.available, demand - ahead))
        rest = max(0.0, b.available - expected)
        days_left = (b.expiry_date - today).days
        if rest <= 1e-9 or b.available <= 1e-9:
            disc = 0.0
        else:
            share = rest / b.available
            disc = lo + (hi - lo) * share + (10 if days_left == 0 else 0)
            disc = float(min(hi, max(lo, round(disc / 5) * 5)))
        out.append({**inv.batch_row(b, today, n), "forecast_sales": round(expected, 1), "unsold": round(rest, 1),
                    "recommended_discount": disc,
                    "recommendation": ("уценить" if disc > b.discount_pct + 1e-9 else
                                       ("уценка уже действует" if b.discount_pct > 0 else "продастся без уценки"))})
    return out


def expired(db: Session, location_id: int | None = None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    q = (db.query(Batch).options(joinedload(Batch.product), joinedload(Batch.location))
         .filter(Batch.qty - Batch.reserved > 1e-9, Batch.expiry_date < today))
    if location_id:
        q = q.filter(Batch.location_id == location_id)
    n = inv.expiring_days(db)
    return [inv.batch_row(b, today, n) for b in q.order_by(Batch.expiry_date)]


def apply(db: Session, items: list[dict], user: User) -> list[dict]:
    """Уценка партий: новая цена уходит в кассы через выгрузку цен (GET /api/onec/prices)."""
    s = appsettings.get_all(db)
    lo, hi = float(s["markdown_min"]), float(s["markdown_max"])
    out = []
    for it in items:
        b = db.get(Batch, it["batch_id"])
        if b is None:
            raise NotFound(f"Партия {it['batch_id']} не найдена")
        d = float(it["discount_pct"])
        if not (lo <= d <= hi):
            raise DomainError(f"Скидка должна быть от {lo:g} до {hi:g} %")
        if b.qty <= 1e-9 or b.expiry_date < date.today():
            raise DomainError(f"Партия {b.id}: уценять можно только партию в продаже с неистёкшим сроком")
        b.discount_pct = d
        price = inv.unit_price(b)
        db.add(Markdown(batch_id=b.id, discount_pct=d, price=price, user_id=user.id))
        audit.log(db, user, "Уценка партии", "batch", b.id, f"{b.product.name}: скидка {d:g} %, цена {price:.2f}")
        out.append({"batch_id": b.id, "discount_pct": d, "price": price})
    db.flush()
    return out
