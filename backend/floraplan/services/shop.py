"""Интернет-магазин (П-11, С-14): остатки и цены для сайта, заказы с резервированием, предзаказы.
Каналы продаж (Р-4): маркетплейсы и другие сайты работают через тот же API со своим ключом."""
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..errors import Conflict, DomainError, NotFound
from ..models import Batch, Location, OnlineOrder, OnlineOrderLine, Product, Reservation, SalesChannel, User
from .sales import record_sale


@dataclass(frozen=True)
class Channel:
    """Кто обращается к API: основной сайт (ключ из настроек) или подключённый канал продаж."""
    id: int | None
    code: str
    name: str
    location_id: int | None = None      # None — место хранения интернет-магазина
    price_factor: float = 1.0

    def order_id(self, external_id: str) -> str:
        """Номер заказа в системе: у каналов — с префиксом кода, чтобы номера разных площадок не совпадали."""
        return external_id if self.id is None else f"{self.code}:{external_id}"


SITE = Channel(None, "site", "Интернет-магазин")
CODE_RE = re.compile(r"^[a-z0-9_-]{2,30}$")


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return "ch_" + secrets.token_urlsafe(24)


def channel_by_key(db: Session, key: str) -> Channel | None:
    c = db.query(SalesChannel).filter(SalesChannel.key_hash == key_hash(key), SalesChannel.active.is_(True)).first()
    return Channel(c.id, c.code, c.name, c.location_id, c.price_factor) if c else None


def channel_location(db: Session, ch: Channel) -> Location:
    return db.get(Location, ch.location_id) if ch.location_id else online_location(db)


def channel_price(p: Product, ch: Channel) -> float:
    return round(p.price * ch.price_factor, 2)


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


def stock(db: Session, ch: Channel = SITE) -> dict:
    loc = channel_location(db, ch)
    today = date.today()
    rows = (db.query(Batch.product_id, func.sum(Batch.qty - Batch.reserved))
            .filter(Batch.location_id == loc.id, Batch.expiry_date >= today).group_by(Batch.product_id).all())
    free = {pid: max(0.0, float(q or 0)) for pid, q in rows}
    items = [{"product_id": p.id, "barcode": p.barcode, "name": p.name, "available": free.get(p.id, 0.0),
              "unit": p.unit} for p in db.query(Product).filter(Product.active.is_(True)).order_by(Product.id)]
    return {"updated_at": datetime.now().replace(microsecond=0), "location": loc.name, "items": items}


def prices(db: Session, ch: Channel = SITE) -> dict:
    return {"updated_at": datetime.now().replace(microsecond=0),
            "items": [{"product_id": p.id, "barcode": p.barcode, "name": p.name, "price": channel_price(p, ch)}
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
                 phone: str = "", comment: str = "", allow_preorder: bool = True,
                 ch: Channel = SITE) -> tuple[OnlineOrder, bool]:
    external_id = ch.order_id(external_id)
    old = db.query(OnlineOrder).filter(OnlineOrder.external_id == external_id).first()
    if old is not None:
        return old, False
    if delivery_date < date.today():
        raise DomainError("Дата доставки уже прошла")
    loc = channel_location(db, ch)
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
    order = OnlineOrder(external_id=external_id, channel_id=ch.id, delivery_date=delivery_date, location_id=loc.id,
                        customer_name=customer_name, phone=phone, comment=comment, status="new")
    db.add(order)
    db.flush()
    for p, q in resolved:
        db.add(OnlineOrderLine(order_id=order.id, product_id=p.id, qty=q, price=channel_price(p, ch)))
    order.total = round(sum(channel_price(p, ch) * q for p, q in resolved), 2)
    db.flush()
    db.refresh(order)
    if short:
        order.status = "preorder"   # товар ещё не поступил: резерв — по приходе (С-14, предзаказ)
    else:
        _reserve(db, order)
    audit.integration(db, "shop", f"{ch.name}: заказ {external_id}: {order.status}, сумма {order.total}")
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


def reserve_waiting(db: Session, location_id: int, user: User | None = None) -> list[str]:
    """С-14: товар поступил в место хранения (приёмка, перемещение) — предзаказы этого места, которые теперь
    можно собрать, резервируются сами; первыми — с ближайшей датой доставки. Возвращает номера заказов."""
    done = []
    waiting = (db.query(OnlineOrder).filter(OnlineOrder.status == "preorder", OnlineOrder.location_id == location_id,
                                            OnlineOrder.delivery_date >= date.today())
               .order_by(OnlineOrder.delivery_date, OnlineOrder.id).all())
    for o in waiting:
        if shortage(db, [(ln.product, ln.qty) for ln in o.lines], o.location_id, o.delivery_date):
            continue
        _reserve(db, o)
        db.flush()
        audit.log(db, user, "Резерв под предзаказ при поступлении товара", "online_order", o.id, o.external_id)
        done.append(o.external_id)
    return done


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


ANONYMIZED = "(обезличено)"


def anonymize_closed(db: Session, now: datetime | None = None) -> int:
    """Б-1, 152-ФЗ: в выполненных и отменённых онлайн-заказах старше срока хранения стираются имя, телефон
    и комментарий покупателя (там бывает адрес). Состав, суммы и продажи остаются для отчётов и прогноза."""
    days = int(appsettings.get(db, "pd_retention_days"))
    border = (now or datetime.now()) - timedelta(days=days)
    orders = (db.query(OnlineOrder).filter(OnlineOrder.status.in_(("completed", "cancelled")),
                                           OnlineOrder.created_at < border,
                                           (OnlineOrder.customer_name != ANONYMIZED) | (OnlineOrder.phone != "")
                                           | (OnlineOrder.comment != "")).all())
    for o in orders:
        o.customer_name, o.phone, o.comment = ANONYMIZED, "", ""
    if orders:
        audit.log(db, None, "Обезличены персональные данные онлайн-заказов", "online_order", "",
                  f"заказов {len(orders)}, закрытых до {border:%d.%m.%Y}")
    return len(orders)
