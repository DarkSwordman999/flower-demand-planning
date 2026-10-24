"""Учёт запасов по партиям: FEFO (С-4), перемещения, списания (С-13), инвентаризация."""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..errors import DomainError, NotFound
from ..models import (Batch, Location, Product, StockMove, StockoutDay, User, WriteOff, WriteOffReason)
from .numbering import next_number


def batch_state(b: Batch, today: date, expiring_days: int) -> str:
    if b.qty <= 1e-9:
        return "written_off" if b.written_off else "sold"
    if b.expiry_date < today:
        return "expired"
    if b.discount_pct > 0:
        return "marked_down"
    if (b.expiry_date - today).days <= expiring_days:
        return "expiring"
    return "fresh"


def unit_price(b: Batch) -> float:
    return round(b.product.price * (1 - b.discount_pct / 100), 2)


def move(db: Session, kind: str, b: Batch, qty: float, day: date, user: User | None = None, ref: str = "") -> None:
    db.add(StockMove(kind=kind, batch_id=b.id, product_id=b.product_id, location_id=b.location_id, qty=qty,
                     cost=b.cost, day=day, ts=datetime.now(), user_id=user.id if user else None, ref=ref))


def create_batch(db: Session, product: Product, location_id: int, qty: float, cost: float, received: date,
                 expiry: date, user: User | None = None, order_line_id: int | None = None, quality: str = "",
                 ref: str = "", parent_id: int | None = None, kind: str = "receipt") -> Batch:
    b = Batch(product_id=product.id, location_id=location_id, order_line_id=order_line_id, parent_id=parent_id,
              received_at=received, expiry_date=expiry, qty_initial=qty, qty=qty, cost=cost, quality=quality)
    b.product = product
    db.add(b)
    db.flush()
    move(db, kind, b, qty, received, user, ref)
    return b


def fefo_batches(db: Session, product_id: int, location_id: int, day: date, include_expired: bool = False):
    q = db.query(Batch).filter(Batch.product_id == product_id, Batch.location_id == location_id,
                               Batch.qty - Batch.reserved > 1e-9)
    if not include_expired:
        q = q.filter(Batch.expiry_date >= day)
    return q.order_by(Batch.expiry_date, Batch.received_at, Batch.id).all()


def available(db: Session, product_id: int, location_id: int, day: date) -> float:
    v = db.query(func.coalesce(func.sum(Batch.qty - Batch.reserved), 0.0)).filter(
        Batch.product_id == product_id, Batch.location_id == location_id, Batch.expiry_date >= day).scalar()
    return max(0.0, float(v))


@dataclass
class Taken:
    batch: Batch
    qty: float


def consume(db: Session, product_id: int, location_id: int, qty: float, day: date, kind: str, ref: str = "",
            user: User | None = None, batch_id: int | None = None, use_reserved: bool = False) -> tuple[list[Taken], float]:
    """Расход по FEFO: сначала партия с наименьшей датой «годен до» (С-4). batch_id — партия, выбранная
    продавцом (FEFO — рекомендация, ПР 4 табл. 4.8). Возвращает взятое и недостачу."""
    taken: list[Taken] = []
    left = qty
    if batch_id:
        b = db.get(Batch, batch_id)
        if b is None or b.product_id != product_id or b.location_id != location_id:
            raise DomainError("Выбранная партия не относится к этому товару и месту")
        free = b.qty if use_reserved else b.available
        t = min(free, left)
        if t > 0:
            taken.append(Taken(b, t))
            left -= t
    if left > 1e-9:
        pools = [fefo_batches(db, product_id, location_id, day)]
        pools.append([b for b in fefo_batches(db, product_id, location_id, day, include_expired=True)
                      if b.expiry_date < day])   # касса уже продала — берём и из просроченных
        for pool in pools:
            for b in pool:
                if left <= 1e-9:
                    break
                if any(t.batch.id == b.id for t in taken):
                    continue
                t = min(b.available, left)
                if t > 0:
                    taken.append(Taken(b, t))
                    left -= t
    for t in taken:
        t.batch.qty -= t.qty
        if use_reserved:
            t.batch.reserved = max(0.0, t.batch.reserved - t.qty)
        move(db, kind, t.batch, -t.qty, day, user, ref)
    db.flush()
    if available(db, product_id, location_id, day) <= 1e-9:
        mark_stockout(db, product_id, location_id, day)
    return taken, max(0.0, left)


def mark_stockout(db: Session, product_id: int, location_id: int, day: date) -> None:
    exists = db.query(StockoutDay.id).filter_by(product_id=product_id, location_id=location_id, day=day).first()
    if not exists:
        db.add(StockoutDay(product_id=product_id, location_id=location_id, day=day))


def transfer(db: Session, product_id: int, src: int, dst: int, qty: float, user: User, day: date | None = None) -> list[Batch]:
    day = day or date.today()
    if src == dst:
        raise DomainError("Место отправления и назначения совпадают")
    if db.get(Location, dst) is None or db.get(Location, src) is None:
        raise NotFound("Место хранения не найдено")
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("Товар не найден")
    if available(db, product_id, src, day) + 1e-9 < qty:
        raise DomainError(f"Недостаточно товара «{product.name}»: доступно {available(db, product_id, src, day):g}")
    ref = f"перемещение {src}→{dst}"
    taken, _ = consume(db, product_id, src, qty, day, "transfer_out", ref, user)
    out = []
    for t in taken:
        out.append(create_batch(db, product, dst, t.qty, t.batch.cost, t.batch.received_at, t.batch.expiry_date,
                                user, t.batch.order_line_id, t.batch.quality, ref, parent_id=t.batch.id,
                                kind="transfer_in"))
        out[-1].discount_pct = t.batch.discount_pct
    audit.log(db, user, "Перемещение товара", "product", product_id, f"{product.name}: {qty:g} {product.unit}, {ref}")
    db.flush()
    from .shop import reserve_waiting
    reserve_waiting(db, dst, user)
    return out


def writeoff(db: Session, items: list[dict], reason_id: int, user: User, comment: str = "", day: date | None = None) -> str:
    """items: [{batch_id, qty}] — одно списание = один акт."""
    day = day or date.today()
    reason = db.get(WriteOffReason, reason_id)
    if reason is None:
        raise NotFound("Причина списания не найдена")
    if not items:
        raise DomainError("Нет позиций для списания")
    act = next_number(db, "АС", WriteOff.act_number, day)
    for it in items:
        b = db.get(Batch, it["batch_id"])
        q = float(it["qty"])
        if b is None:
            raise NotFound(f"Партия {it['batch_id']} не найдена")
        if q <= 0 or q > b.available + 1e-9:
            raise DomainError(f"Партия {b.id} ({b.product.name}): можно списать не больше {b.available:g}")
        b.qty -= q
        if b.qty <= 1e-9:
            b.written_off = True
        db.add(WriteOff(act_number=act, batch_id=b.id, qty=q, cost=b.cost, reason_id=reason_id, user_id=user.id,
                        comment=comment))
        move(db, "writeoff", b, -q, day, user, act)
        if available(db, b.product_id, b.location_id, day) <= 1e-9:
            mark_stockout(db, b.product_id, b.location_id, day)
    audit.log(db, user, "Списание товара", "writeoff", act, f"{reason.name}; позиций {len(items)}")
    db.flush()
    return act


def count(db: Session, items: list[dict], user: User, day: date | None = None) -> dict:
    """Инвентаризация: фактический остаток по партиям; излишки и недостачи проводятся движением inventory."""
    day = day or date.today()
    diffs = []
    for it in items:
        b = db.get(Batch, it["batch_id"])
        if b is None:
            raise NotFound(f"Партия {it['batch_id']} не найдена")
        fact = float(it["qty"])
        if fact < 0:
            raise DomainError("Фактическое количество не может быть отрицательным")
        if fact < b.reserved - 1e-9:
            raise DomainError(f"Партия {b.id}: в резерве {b.reserved:g}, факт не может быть меньше")
        d = fact - b.qty
        if abs(d) > 1e-9:
            b.qty = fact
            move(db, "inventory", b, d, day, user, "инвентаризация")
            diffs.append({"batch_id": b.id, "product": b.product.name, "diff": d})
    audit.log(db, user, "Инвентаризация", "inventory", "", f"расхождений {len(diffs)}")
    db.flush()
    return {"differences": diffs}


def batch_row(b: Batch, today: date, expiring_days: int) -> dict:
    st = batch_state(b, today, expiring_days)
    return {"id": b.id, "product_id": b.product_id, "product": b.product.name, "group_id": b.product.group_id,
            "location_id": b.location_id, "location": b.location.name, "received_at": b.received_at,
            "expiry_date": b.expiry_date, "days_left": (b.expiry_date - today).days, "qty_initial": b.qty_initial,
            "qty": b.qty, "reserved": b.reserved, "available": b.available, "cost": b.cost,
            "price": b.product.price, "discount_pct": b.discount_pct, "sale_price": unit_price(b),
            "quality": b.quality, "state": st, "unit": b.product.unit, "barcode": b.product.barcode}


def expiring_days(db: Session) -> int:
    return int(appsettings.get(db, "expiring_days"))
