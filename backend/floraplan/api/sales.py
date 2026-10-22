"""Учёт продаж: журнал чеков, продажа в салоне, загрузка чеков из файла."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from .. import audit
from ..db import get_db
from ..errors import NotFound
from ..models import Sale, SaleLine, User
from ..security import require
from ..services import sales as svc

router = APIRouter(prefix="/api/sales", tags=["Продажи"])
viewers = require("florist", "director", "analyst", "buyer", "shop_manager", "storekeeper")


def sale_out(s: Sale, lines: bool = False) -> dict:
    d = {"id": s.id, "external_id": s.external_id, "ts": s.ts, "location_id": s.location_id,
         "location": s.location.name, "channel": s.channel, "total": s.total, "items": len(s.lines)}
    if lines:
        d["lines"] = [{"product_id": ln.product_id, "product": ln.product.name, "batch_id": ln.batch_id, "qty": ln.qty,
                       "price": ln.price, "discount": ln.discount, "sum": ln.qty * ln.price - ln.discount}
                      for ln in s.lines]
    return d


@router.get("")
def journal(date_from: date | None = None, date_to: date | None = None, location_id: int | None = None,
            channel: str = "", limit: int = 500, _: User = Depends(viewers), db: Session = Depends(get_db)):
    q = db.query(Sale).options(joinedload(Sale.location), joinedload(Sale.lines)).filter(Sale.channel != "history")
    if date_from:
        q = q.filter(Sale.ts >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.filter(Sale.ts <= datetime.combine(date_to, time.max))
    if location_id:
        q = q.filter(Sale.location_id == location_id)
    if channel:
        q = q.filter(Sale.channel == channel)
    return [sale_out(s) for s in q.order_by(Sale.ts.desc()).limit(min(limit, 5000)).all()]


@router.get("/{sale_id}")
def sale(sale_id: int, _: User = Depends(viewers), db: Session = Depends(get_db)):
    s = db.get(Sale, sale_id, options=[joinedload(Sale.lines).joinedload(SaleLine.product)])
    if s is None:
        raise NotFound("Чек не найден")
    return sale_out(s, lines=True)


class LineIn(BaseModel):
    product_id: int | None = None
    barcode: str | None = None
    qty: float = Field(gt=0)
    price: float | None = Field(default=None, ge=0)
    discount: float = Field(default=0, ge=0)
    batch_id: int | None = None


class SaleIn(BaseModel):
    location_id: int
    lines: list[LineIn]


@router.post("")
def create_sale(body: SaleIn, me: User = Depends(require("florist")), db: Session = Depends(get_db)):
    """Продажа в салоне (когда чек проводится в системе, а не загружается из касс)."""
    s, _ = svc.record_sale(db, body.location_id, [ln.model_dump() for ln in body.lines], channel="manual", user=me)
    audit.log(db, me, "Продажа", "sale", s.id, f"сумма {s.total:.2f}")
    db.commit()
    return sale_out(db.get(Sale, s.id), lines=True)


@router.post("/import")
async def import_file(file: UploadFile = File(...), me: User = Depends(require("analyst", "storekeeper")),
                      db: Session = Depends(get_db)):
    """Загрузка выгрузки чеков «1С» (JSON или CSV: чек;дата;точка;штрихкод;количество;цена;скидка)."""
    receipts = svc.parse_receipts(await file.read(), file.filename or "")
    res = svc.import_receipts(db, receipts, me, source="1c")
    audit.log(db, me, "Загрузка чеков из файла", "sale", "", f"{file.filename}: создано {res['created']}")
    db.commit()
    return res
