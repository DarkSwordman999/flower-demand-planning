"""Интернет-магазин (П-11, С-14): остатки и цены для сайта, заказы с резервированием, предзаказы."""
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, DomainError, NotFound
from ..models import Batch, Location, OnlineOrder, OnlineOrderLine, Product, Reservation, User
from .sales import record_sale


def online_location(db: Session) -> Location:
    loc = (db.query(Location).filter(Location.type == "online", Location.active.is_(True)).order_by(Location.id).first()
           or db.query(Location).filter(Location.type == "warehouse").order_by(Location.id).first())
    if loc is None:
        raise DomainError("Не задано место хранения интернет-магазина")
    return loc


def _free_batches(db: Session, product_id: int, location_id: int, fresh_on: date):
    """Партии, годные на дату доставки, по FEFO."""
    return (db.query(Batch).filter(Batch.product_id == product_id, Batch.location_id == location_id,
                                   Batch.expiry_date >= fresh_on, Batch.qty - Batch.reserved > 1e-9)
            .order_by(Batch.expiry_date, Batch.id).all())


def free_qty(db: Session, product_id: int, location_id: int, fresh_on: date) -> float:
    v = db.query(func.coalesce(func.sum(Batch.qty - Batch.reserved), 0.0)).filter(
        Batch.product_id == product_id, Batch.location_id == location_id, Batch.expiry_date >= fresh_on).scalar()
    return max(0.0, float(v))


def stock(db: Session) -> dict:
    loc = online_location(db)
    today = date.today()
    rows = (db.query(Batch.product_id, func.sum(Batch.qty - Batch.reserved))
            .filter(Batch.location_id == loc.id, Batch.expiry_date >= today).group_by(Batch.product_id).all())
    free = {pid: max(0.0, float(q or 0)) for pid, q in rows}
    items = [{"product_id": p.id, "barcode": p.barcode, "name": p.name, "available": free.get(p.id, 0.0),
              "unit": p.unit} for p in db.query(Product).filter(Product.active.is_(True)).order_by(Product.id)]
    return {"updated_at": datetime.now().replace(microsecond=0), "location": loc.name, "items": items}


def prices(db: Session) -> dict:
    return {"updated_at": datetime.now().replace(microsecond=0),
            "items": [{"product_id": p.id, "barcode": p.barcode, "name": p.name, "price": p.price}
                      for p in db.query(Product).filter(Product.active.is_(True)).order_by(Product.id)]}


def _reserve(db: Session, order: OnlineOrder) -> None:
    for ln in order.lines:
        left = ln.qty
        for b in _free_batches(db, ln.product_id, order.location_id, order.delivery_date):
            t = min(b.qty - b.reserved, left)
            b.reserved += t
            db.add(Reservation(line_id=ln.id, batch_id=b.id, qty=t))
            left -= t
            if left <= 1e-9:
                break
    order.status = "reserved"


def shortage(db: Session, order_lines: list[tuple[Product, float]], location_id: int, on: date) -> list[dict]:
    out = []
    for p, q in order_lines:
        free = free_qty(db, p.id, location_id, on)
        if free + 1e-9 < q:
            out.append({"product_id": p.id, "name": p.name, "requested": q, "available": free})
    return out


def create_order(db: Session, external_id: str, delivery_date: date, lines: list[dict], customer_name: str = "",
                 phone: str = "", comment: str = "", allow_preorder: bool = True) -> tuple[OnlineOrder, bool]:
    old = db.query(OnlineOrder).filter(OnlineOrder.external_id == external_id).first()
    if old is not None:
        return old, False
    if delivery_date < date.today():
        raise DomainError("Дата доставки уже прошла")
    loc = online_location(db)
    resolved = []
    for ln in lines:
        p = (db.get(Product, int(ln["product_id"])) if ln.get("product_id")
             else db.query(Product).filter(Product.barcode == str(ln.get("barcode", ""))).first())
        if p is None or not p.active:
            raise NotFound(f"Товар не найден: {ln.get('product_id') or ln.get('barcode')}")
        if float(ln["qty"]) <= 0:
            raise DomainError("Количество должно быть больше нуля")
        resolved.append((p, float(ln["qty"])))
    if not resolved:
        raise DomainError("Заказ без позиций")
    short = shortage(db, resolved, loc.id, delivery_date)
    if short and not allow_preorder:
        raise Conflict("Недостаточно товара для заказа", data={"shortage": short})
    order = OnlineOrder(external_id=external_id, delivery_date=delivery_date, location_id=loc.id,
                        customer_name=customer_name, phone=phone, comment=comment, status="new")
    db.add(order)
    db.flush()
    for p, q in resolved:
        db.add(OnlineOrderLine(order_id=order.id, product_id=p.id, qty=q, price=p.price))
    order.total = round(sum(p.price * q for p, q in resolved), 2)
    db.flush()
    db.refresh(order)
    if short:
        order.status = "preorder"   # товар ещё не поступил: резерв — по приходе (С-14, предзаказ)
    else:
        _reserve(db, order)
    audit.integration(db, "shop", f"заказ {external_id}: {order.status}, сумма {order.total}")
    db.flush()
    return order, True


def reserve_preorder(db: Session, order: OnlineOrder, user: User) -> OnlineOrder:
    if order.status != "preorder":
        raise DomainError("Резервировать можно только предзаказ")
    short = shortage(db, [(ln.product, ln.qty) for ln in order.lines], order.location_id, order.delivery_date)
    if short:
        raise Conflict("Товара для предзаказа пока недостаточно", data={"shortage": short})
    _reserve(db, order)
    audit.log(db, user, "Резерв под предзаказ", "online_order", order.id, order.external_id)
    return order


def _release(db: Session, order: OnlineOrder) -> None:
    for ln in order.lines:
        for r in db.query(Reservation).filter(Reservation.line_id == ln.id).all():
            b = db.get(Batch, r.batch_id)
            b.reserved = max(0.0, b.reserved - r.qty)
            db.delete(r)


def complete(db: Session, order: OnlineOrder, user: User) -> OnlineOrder:
    if order.status != "reserved":
        raise DomainError("Выполнить можно только заказ с резервом")
    lines = []
    for ln in order.lines:
        for r in db.query(Reservation).filter(Reservation.line_id == ln.id).all():
            lines.append({"product_id": ln.product_id, "qty": r.qty, "price": ln.price, "batch_id": r.batch_id})
            db.delete(r)
    sale, _ = record_sale(db, order.location_id, lines, channel="online", external_id=f"shop:{order.external_id}",
                          user=user, use_reserved=True)
    order.sale_id = sale.id
    order.status = "completed"
    audit.log(db, user, "Онлайн-заказ выполнен", "online_order", order.id, order.external_id)
    return order


def cancel(db: Session, order: OnlineOrder, user: User | None) -> OnlineOrder:
    if order.status in ("completed", "cancelled"):
        raise DomainError("Заказ уже закрыт")
    _release(db, order)
    order.status = "cancelled"
    audit.log(db, user, "Онлайн-заказ отменён", "online_order", order.id, order.external_id)
    return order
