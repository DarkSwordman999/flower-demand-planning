"""Планирование закупок и заказы поставщикам (П-6…П-8, П-12, С-7…С-11, С-15)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..errors import DomainError, NotFound
from ..models import ORDER_STATUSES, HolidayScenario, PurchaseOrder, PurchaseOrderLine, Supplier, User
from ..security import require
from ..services import purchasing as svc
from ..services import xlsx

router = APIRouter(prefix="/api/purchasing", tags=["Планирование закупок"])
buyers = require("buyer")
viewers = require("buyer", "director", "storekeeper", "analyst")


class PlanIn(BaseModel):
    supplier_id: int
    delivery_date: date | None = None
    scenario_id: int | None = None


@router.post("/plan", summary="Рассчитать рекомендуемый заказ (без сохранения)")
def plan(body: PlanIn, _: User = Depends(require("buyer", "director")), db: Session = Depends(get_db)):
    return svc.plan(db, body.supplier_id, delivery_date=body.delivery_date, scenario_id=body.scenario_id)


def order_out(o: PurchaseOrder, lines: bool = True) -> dict:
    d = {"id": o.id, "number": o.number, "supplier_id": o.supplier_id, "supplier": o.supplier.name,
         "supplier_email": o.supplier.email, "location": o.location.name, "order_date": o.order_date,
         "expected_date": o.expected_date, "next_delivery_date": o.next_delivery_date, "status": o.status,
         "status_name": ORDER_STATUSES[o.status], "total": o.total, "over_budget": o.over_budget,
         "sent_at": o.sent_at, "comment": o.comment, "scenario_id": o.scenario_id,
         "warnings": (o.plan_info or {}).get("warnings", []), "imported": o.supplier.imported}
    if lines:
        d["lines"] = [{"id": ln.id, "product_id": ln.product_id, "product": ln.product.name, "unit": ln.product.unit,
                       "barcode": ln.product.barcode, "recommended_qty": ln.recommended_qty,
                       "ordered_qty": ln.ordered_qty, "price": ln.price, "sum": ln.ordered_qty * ln.price,
                       "pack_multiple": ln.pack_multiple, "change_reason": ln.change_reason, "calc": ln.calc,
                       "received_qty": ln.received_qty} for ln in o.lines]
    return d


def _load(db: Session, oid: int) -> PurchaseOrder:
    o = db.get(PurchaseOrder, oid, options=[joinedload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.product),
                                            joinedload(PurchaseOrder.supplier), joinedload(PurchaseOrder.location)])
    if o is None:
        raise NotFound("Заказ не найден")
    return o


@router.post("/orders", summary="Сформировать черновик заказа по рекомендации")
def create(body: PlanIn, me: User = Depends(buyers), db: Session = Depends(get_db)):
    p = svc.plan(db, body.supplier_id, delivery_date=body.delivery_date, scenario_id=body.scenario_id)
    o = svc.create_order(db, p, me)
    db.commit()
    return order_out(_load(db, o.id))


@router.get("/orders")
def orders(status: str = "", supplier_id: int | None = None, date_from: date | None = None,
           _: User = Depends(viewers), db: Session = Depends(get_db)):
    q = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.supplier), joinedload(PurchaseOrder.location))
    if status:
        q = q.filter(PurchaseOrder.status.in_(status.split(",")))
    if supplier_id:
        q = q.filter(PurchaseOrder.supplier_id == supplier_id)
    if date_from:
        q = q.filter(PurchaseOrder.order_date >= date_from)
    return [order_out(o, lines=False) for o in q.order_by(PurchaseOrder.id.desc()).limit(1000)]


@router.get("/orders/{oid}")
def order(oid: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    return order_out(_load(db, oid))


class LineEdit(BaseModel):
    line_id: int | None = None
    product_id: int | None = None
    ordered_qty: float = Field(ge=0)
    change_reason: str = ""


class LinesIn(BaseModel):
    items: list[LineEdit]


@router.put("/orders/{oid}/lines", summary="Корректировка количеств (кратность, причина при отклонении > 30 %)")
def edit_lines(oid: int, body: LinesIn, me: User = Depends(buyers), db: Session = Depends(get_db)):
    o = svc.update_lines(db, _load(db, oid), [i.model_dump() for i in body.items], me)
    db.commit()
    return order_out(_load(db, o.id))


class ActionIn(BaseModel):
    comment: str = ""


@router.post("/orders/{oid}/{action}", summary="Смена статуса: submit, approve, reject, send, confirm, in_transit, close, cancel")
def action(oid: int, action: str, body: ActionIn | None = None,
           me: User = Depends(require("buyer", "director")), db: Session = Depends(get_db)):
    if action not in svc.TRANSITIONS:
        raise NotFound("Неизвестное действие")
    if me.role == "director" and action not in ("approve", "reject"):
        raise DomainError("Директор утверждает или возвращает заказы; остальное делает менеджер по закупкам",
                          status=403)
    o = svc.transition(db, _load(db, oid), action, me, (body.comment if body else "").strip())
    db.commit()
    return order_out(_load(db, o.id))


@router.get("/orders/{oid}/xlsx", summary="Заказ в XLSX (как отправляется поставщику)")
def order_file(oid: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    o = _load(db, oid)
    return xlsx.response(svc.order_xlsx(db, o), f"{o.number}.xlsx")


@router.get("/budget")
def budget(_: User = Depends(viewers), db: Session = Depends(get_db)):
    from .. import appsettings
    today = date.today()
    a, b = svc.week_bounds(today)
    waiting = db.query(PurchaseOrder).filter(PurchaseOrder.status == "approval").count()
    return {"week_from": a, "week_to": b, "budget": appsettings.get(db, "weekly_budget"),
            "committed": svc.committed_this_week(db, today), "awaiting_approval": waiting}


@router.get("/scenarios/{sid}/schedule", summary="График заказов по поставщикам к празднику (С-15)")
def scenario_schedule(sid: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    s = db.get(HolidayScenario, sid)
    if s is None:
        raise NotFound("Сценарий не найден")
    today = date.today()
    out = []
    for sup in db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name):
        days = {int(x) for x in sup.order_weekdays.split(",") if x.strip()}
        last_order = s.last_delivery_date - timedelta(days=sup.lead_time_days)
        dates = []
        d = today
        while d <= last_order:
            if d.weekday() in days:
                dates.append({"order_date": d, "delivery_date": d + timedelta(days=sup.lead_time_days)})
            d += timedelta(days=1)
        out.append({"supplier_id": sup.id, "supplier": sup.name, "lead_time_days": sup.lead_time_days,
                    "last_order_date": last_order, "orders": dates,
                    "late": last_order < today})
    return {"scenario": s.name, "event_date": s.event_date, "last_delivery_date": s.last_delivery_date,
            "suppliers": out}
