"""Интернет-магазин: методы для сайта (И-1, ключ X-API-Key) и обработка заказов менеджером."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from .. import audit
from ..db import get_db
from ..errors import NotFound
from ..models import ONLINE_STATUSES, OnlineOrder, OnlineOrderLine, User
from ..security import api_key, require
from ..services import shop

router = APIRouter(tags=["Интернет-магазин"])
site = api_key("shop")
managers = require("shop_manager")


@router.get("/api/shop/stock", summary="Остатки, доступные для продажи на сайте")
def stock(_: str = Depends(site), db: Session = Depends(get_db)):
    return shop.stock(db)


@router.get("/api/shop/prices", summary="Цены для сайта")
def prices(_: str = Depends(site), db: Session = Depends(get_db)):
    return shop.prices(db)


class ShopLine(BaseModel):
    product_id: int | None = None
    barcode: str | None = None
    qty: float = Field(gt=0)


class ShopOrderIn(BaseModel):
    id: str = Field(min_length=1, max_length=100, description="номер заказа на сайте")
    delivery_date: date
    customer_name: str = ""
    phone: str = ""
    comment: str = ""
    allow_preorder: bool = True
    lines: list[ShopLine]


def order_out(o: OnlineOrder, show_pd: bool) -> dict:
    phone = o.phone if show_pd else (o.phone[:2] + "*" * max(0, len(o.phone) - 4) + o.phone[-2:] if o.phone else "")
    return {"id": o.id, "external_id": o.external_id, "created_at": o.created_at, "delivery_date": o.delivery_date,
            "customer_name": o.customer_name, "phone": phone, "status": o.status,
            "status_name": ONLINE_STATUSES[o.status], "total": o.total, "comment": o.comment, "sale_id": o.sale_id,
            "lines": [{"product_id": ln.product_id, "product": ln.product.name, "qty": ln.qty, "price": ln.price}
                      for ln in o.lines]}


@router.post("/api/shop/orders", summary="Передать заказ с сайта (резервирует товар; повтор номера не дублирует)")
def create(body: ShopOrderIn, _: str = Depends(site), db: Session = Depends(get_db)):
    o, created = shop.create_order(db, body.id, body.delivery_date, [ln.model_dump() for ln in body.lines],
                                   body.customer_name, body.phone, body.comment, body.allow_preorder)
    db.commit()
    return {"order_id": o.id, "status": o.status, "status_name": ONLINE_STATUSES[o.status], "created": created,
            "total": o.total}


@router.get("/api/shop/orders/{external_id}", summary="Статус заказа для сайта")
def status(external_id: str, _: str = Depends(site), db: Session = Depends(get_db)):
    o = db.query(OnlineOrder).filter(OnlineOrder.external_id == external_id).first()
    if o is None:
        raise NotFound("Заказ не найден")
    return {"order_id": o.id, "status": o.status, "status_name": ONLINE_STATUSES[o.status]}


# ------------------------------------------------------------ рабочее место менеджера интернет-магазина
def _load(db: Session, oid: int) -> OnlineOrder:
    o = db.get(OnlineOrder, oid, options=[joinedload(OnlineOrder.lines).joinedload(OnlineOrderLine.product)])
    if o is None:
        raise NotFound("Заказ не найден")
    return o


@router.get("/api/online-orders")
def orders(status: str = "", date_from: date | None = None, date_to: date | None = None,
           me: User = Depends(require("shop_manager", "director", "florist")), db: Session = Depends(get_db)):
    q = db.query(OnlineOrder).options(joinedload(OnlineOrder.lines).joinedload(OnlineOrderLine.product))
    if status:
        q = q.filter(OnlineOrder.status == status)
    if date_from:
        q = q.filter(OnlineOrder.delivery_date >= date_from)
    if date_to:
        q = q.filter(OnlineOrder.delivery_date <= date_to)
    show = me.role in ("shop_manager", "admin")
    return [order_out(o, show) for o in q.order_by(OnlineOrder.delivery_date, OnlineOrder.id).limit(2000).all()]


@router.post("/api/online-orders/{oid}/reserve")
def reserve(oid: int, me: User = Depends(managers), db: Session = Depends(get_db)):
    o = shop.reserve_preorder(db, _load(db, oid), me)
    db.commit()
    return order_out(o, True)


@router.post("/api/online-orders/{oid}/complete")
def complete(oid: int, me: User = Depends(managers), db: Session = Depends(get_db)):
    o = shop.complete(db, _load(db, oid), me)
    db.commit()
    return order_out(o, True)


@router.post("/api/online-orders/{oid}/cancel")
def cancel(oid: int, me: User = Depends(managers), db: Session = Depends(get_db)):
    o = shop.cancel(db, _load(db, oid), me)
    db.commit()
    return order_out(o, True)


class ManualOrderIn(ShopOrderIn):
    pass


@router.post("/api/online-orders")
def create_manual(body: ManualOrderIn, me: User = Depends(require("shop_manager", "florist")),
                  db: Session = Depends(get_db)):
    """Предзаказ или заказ, принятый по телефону или в салоне."""
    o, _ = shop.create_order(db, body.id, body.delivery_date, [ln.model_dump() for ln in body.lines],
                             body.customer_name, body.phone, body.comment, body.allow_preorder)
    audit.log(db, me, "Принят заказ покупателя", "online_order", o.id, o.external_id)
    db.commit()
    return order_out(_load(db, o.id), me.role in ("shop_manager", "admin"))
