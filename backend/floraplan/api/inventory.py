"""Учёт запасов и партий (П-3, С-4, С-13): остатки, перемещения, списания, инвентаризация."""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from .. import appsettings
from ..db import get_db
from ..errors import NotFound
from ..models import BATCH_STATES, Batch, Product, StockMove, User, WriteOff
from ..security import require
from ..services import inventory as inv
from ..services import xlsx

router = APIRouter(prefix="/api/inventory", tags=["Запасы и партии"])
viewers = require("storekeeper", "florist", "buyer", "director", "analyst", "shop_manager")
storekeepers = require("storekeeper")


@router.get("/batches")
def batches(location_id: int | None = None, product_id: int | None = None, state: str = "", q: str = "",
            only_active: bool = True, _: User = Depends(viewers), db: Session = Depends(get_db)):
    today = date.today()
    exp = inv.expiring_days(db)
    qry = db.query(Batch).options(joinedload(Batch.product), joinedload(Batch.location))
    if only_active:
        qry = qry.filter(Batch.qty > 1e-9)
    if location_id:
        qry = qry.filter(Batch.location_id == location_id)
    if product_id:
        qry = qry.filter(Batch.product_id == product_id)
    if q:
        qry = qry.join(Product).filter(Product.name.ilike(f"%{q}%") | Product.barcode.ilike(f"%{q}%"))
    rows = [inv.batch_row(b, today, exp) for b in qry.order_by(Batch.expiry_date, Batch.id).limit(5000)]
    if state:
        rows = [r for r in rows if r["state"] == state]
    return rows


@router.get("/batch-states")
def states(_: User = Depends(viewers)):
    return [{"code": k, "name": v} for k, v in BATCH_STATES.items()]


@router.get("/stock")
def stock(location_id: int | None = None, _: User = Depends(viewers), db: Session = Depends(get_db)):
    """Сводка остатков «товар × место»: всего, доступно, в резерве, ближайший срок, стоимость."""
    today = date.today()
    exp = inv.expiring_days(db)
    qry = db.query(Batch).options(joinedload(Batch.product), joinedload(Batch.location)).filter(Batch.qty > 1e-9)
    if location_id:
        qry = qry.filter(Batch.location_id == location_id)
    agg: dict = defaultdict(lambda: {"qty": 0.0, "available": 0.0, "reserved": 0.0, "expiring": 0.0,
                                     "expired": 0.0, "value": 0.0, "nearest_expiry": None})
    for b in qry:
        k = (b.product_id, b.location_id)
        a = agg[k]
        a.update(product_id=b.product_id, product=b.product.name, location_id=b.location_id,
                 location=b.location.name, unit=b.product.unit, group_id=b.product.group_id)
        a["qty"] += b.qty
        a["reserved"] += b.reserved
        a["value"] += b.qty * b.cost
        st = inv.batch_state(b, today, exp)
        if st == "expired":
            a["expired"] += b.qty
        else:
            a["available"] += b.available
            if st in ("expiring", "marked_down"):
                a["expiring"] += b.qty
            if a["nearest_expiry"] is None or b.expiry_date < a["nearest_expiry"]:
                a["nearest_expiry"] = b.expiry_date
    return sorted(agg.values(), key=lambda r: (r["product"], r["location"]))


@router.get("/batches/{bid}/moves")
def batch_moves(bid: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    if db.get(Batch, bid) is None:
        raise NotFound("Партия не найдена")
    return [{"ts": m.ts, "kind": m.kind, "qty": m.qty, "ref": m.ref}
            for m in db.query(StockMove).filter(StockMove.batch_id == bid).order_by(StockMove.id)]


class TransferIn(BaseModel):
    product_id: int
    from_location_id: int
    to_location_id: int
    qty: float = Field(gt=0)


@router.post("/transfer")
def transfer(body: TransferIn, me: User = Depends(storekeepers), db: Session = Depends(get_db)):
    out = inv.transfer(db, body.product_id, body.from_location_id, body.to_location_id, body.qty, me)
    db.commit()
    return {"batches": [b.id for b in out]}


class WriteOffItem(BaseModel):
    batch_id: int
    qty: float = Field(gt=0)


class WriteOffIn(BaseModel):
    items: list[WriteOffItem]
    reason_id: int
    comment: str = ""


@router.post("/writeoff")
def writeoff(body: WriteOffIn, me: User = Depends(require("storekeeper", "florist")), db: Session = Depends(get_db)):
    act = inv.writeoff(db, [i.model_dump() for i in body.items], body.reason_id, me, body.comment)
    db.commit()
    return {"act_number": act}


def _act_rows(db: Session, act: str):
    rows = db.query(WriteOff).options(joinedload(WriteOff.batch).joinedload(Batch.product),
                                      joinedload(WriteOff.batch).joinedload(Batch.location),
                                      joinedload(WriteOff.reason)).filter(WriteOff.act_number == act).all()
    if not rows:
        raise NotFound("Акт списания не найден")
    return rows


@router.get("/writeoffs")
def writeoff_acts(date_from: date | None = None, date_to: date | None = None, _: User = Depends(viewers),
                  db: Session = Depends(get_db)):
    q = db.query(WriteOff).options(joinedload(WriteOff.batch).joinedload(Batch.product),
                                   joinedload(WriteOff.batch).joinedload(Batch.location), joinedload(WriteOff.reason))
    if date_from:
        q = q.filter(WriteOff.ts >= date_from)
    if date_to:
        q = q.filter(WriteOff.ts < date.fromordinal(date_to.toordinal() + 1))
    acts: dict = {}
    for w in q.order_by(WriteOff.ts.desc()).limit(5000):
        a = acts.setdefault(w.act_number, {"act_number": w.act_number, "ts": w.ts, "reason": w.reason.name,
                                           "location": w.batch.location.name, "items": 0, "qty": 0.0, "cost": 0.0,
                                           "comment": w.comment})
        a["items"] += 1
        a["qty"] += w.qty
        a["cost"] += w.qty * w.cost
    return list(acts.values())


@router.get("/writeoffs/{act}")
def writeoff_act(act: str, _: User = Depends(viewers), db: Session = Depends(get_db)):
    rows = _act_rows(db, act)
    return {"act_number": act, "ts": rows[0].ts, "reason": rows[0].reason.name, "comment": rows[0].comment,
            "items": [{"batch_id": w.batch_id, "product": w.batch.product.name, "location": w.batch.location.name,
                       "expiry_date": w.batch.expiry_date, "qty": w.qty, "cost": w.cost, "sum": w.qty * w.cost}
                      for w in rows]}


@router.get("/writeoffs/{act}/xlsx")
def writeoff_act_xlsx(act: str, _: User = Depends(viewers), db: Session = Depends(get_db)):
    rows = _act_rows(db, act)
    company = appsettings.get(db, "company_name")
    data = xlsx.build(
        f"Акт списания № {act}", ["№", "Товар", "Место", "Партия", "Годен до", "Количество", "Себестоимость", "Сумма"],
        [[i + 1, w.batch.product.name, w.batch.location.name, w.batch_id, w.batch.expiry_date, w.qty, w.cost,
          w.qty * w.cost] for i, w in enumerate(rows)],
        meta=[("Организация", company), ("Дата", rows[0].ts.strftime("%d.%m.%Y %H:%M")),
              ("Причина", rows[0].reason.name), ("Комментарий", rows[0].comment)],
        footer=[f"Итого: {sum(w.qty * w.cost for w in rows):,.2f} руб.".replace(",", " "),
                "Ответственный: ____________________     Утверждаю: ____________________"],
        sheet="Акт списания")
    return xlsx.response(data, f"{act}.xlsx")


class CountItem(BaseModel):
    batch_id: int
    qty: float


class CountIn(BaseModel):
    items: list[CountItem]


@router.post("/count")
def inventory_count(body: CountIn, me: User = Depends(storekeepers), db: Session = Depends(get_db)):
    res = inv.count(db, [i.model_dump() for i in body.items], me)
    db.commit()
    return res
