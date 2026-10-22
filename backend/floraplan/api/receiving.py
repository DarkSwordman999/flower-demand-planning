"""Приёмка поставок с ТСД (П-2, С-2, С-3): заказы в пути, приёмка, акты расхождений, этикетки."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from .. import appsettings
from ..db import get_db
from ..errors import NotFound
from ..models import Batch, DiscrepancyAct, PurchaseOrder, PurchaseOrderLine, User
from ..security import require
from ..services import receiving as svc
from ..services import xlsx
from .purchasing import order_out

router = APIRouter(prefix="/api/receiving", tags=["Приёмка поставок"])
storekeepers = require("storekeeper")
viewers = require("storekeeper", "buyer", "director")


@router.get("/orders", summary="Заказы в пути — к приёмке")
def to_receive(_: User = Depends(viewers), db: Session = Depends(get_db)):
    q = (db.query(PurchaseOrder).options(joinedload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.product),
                                         joinedload(PurchaseOrder.supplier), joinedload(PurchaseOrder.location))
         .filter(PurchaseOrder.status == "in_transit").order_by(PurchaseOrder.expected_date))
    return [order_out(o) for o in q.all()]


class ReceiveLine(BaseModel):
    line_id: int
    received_qty: float = Field(ge=0)
    defect_qty: float = Field(default=0, ge=0)
    shelf_reduction_days: int = Field(default=0, ge=0)
    phyto_ok: bool = False
    quality: str = ""


class ReceiveIn(BaseModel):
    items: list[ReceiveLine]


@router.post("/orders/{oid}", summary="Завершить приёмку: партии, акт расхождений, статус «Принят»")
def receive(oid: int, body: ReceiveIn, me: User = Depends(storekeepers), db: Session = Depends(get_db)):
    o = db.get(PurchaseOrder, oid, options=[joinedload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.product),
                                            joinedload(PurchaseOrder.supplier)])
    if o is None:
        raise NotFound("Заказ не найден")
    res = svc.receive(db, o, [i.model_dump() for i in body.items], me)
    db.commit()
    return res


def act_out(a: DiscrepancyAct) -> dict:
    return {"id": a.id, "number": a.number, "created_at": a.created_at, "order_id": a.order_id,
            "order_number": a.order.number, "supplier": a.order.supplier.name, "lines": a.lines}


@router.get("/acts")
def acts(_: User = Depends(viewers), db: Session = Depends(get_db)):
    return [act_out(a) for a in db.query(DiscrepancyAct).order_by(DiscrepancyAct.id.desc()).limit(500)]


@router.get("/acts/{aid}/xlsx")
def act_xlsx(aid: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    a = db.get(DiscrepancyAct, aid)
    if a is None:
        raise NotFound("Акт не найден")
    data = xlsx.build(
        f"Акт расхождений № {a.number}", ["Товар", "Заказано", "Поступило", "Принято", "Расхождение", "Причина"],
        [[x["product"], x["ordered"], x["received"], x["accepted"], x["diff"], x["reason"]] for x in a.lines],
        meta=[("Организация", appsettings.get(db, "company_name")), ("Поставщик", a.order.supplier.name),
              ("Заказ", a.order.number), ("Дата", a.created_at.strftime("%d.%m.%Y %H:%M"))],
        footer=["Кладовщик: ____________________     Представитель поставщика: ____________________"],
        sheet="Акт расхождений")
    return xlsx.response(data, f"{a.number}.xlsx")


@router.get("/labels", response_class=HTMLResponse, summary="Этикетки партий для печати")
def labels(batch_ids: list[int] = Query(...), _: User = Depends(require("storekeeper", "florist")),
           db: Session = Depends(get_db)):
    bs = (db.query(Batch).options(joinedload(Batch.product), joinedload(Batch.location))
          .filter(Batch.id.in_(batch_ids)).order_by(Batch.id).all())
    if not bs:
        raise NotFound("Партии не найдены")
    return HTMLResponse(svc.labels_html(bs))
