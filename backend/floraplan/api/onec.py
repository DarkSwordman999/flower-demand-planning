"""Интеграция с «1С:Розница» и кассами (В-1, С-5): HTTP-сервис для чеков и выгрузки цен (ключ X-API-Key)."""
from datetime import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import api_key, require
from ..services import onec, sales

router = APIRouter(prefix="/api/onec", tags=["Интеграция: 1С и кассы"])


class ReceiptLine(BaseModel):
    barcode: str | None = None
    product_id: int | None = None
    qty: float
    price: float | None = None
    discount: float = 0


class Receipt(BaseModel):
    id: str
    datetime: dt | None = None
    store: str | int
    lines: list[ReceiptLine]


class ReceiptsIn(BaseModel):
    receipts: list[Receipt]


@router.post("/receipts", summary="Передача чеков продаж и возвратов (повтор не создаёт дубликатов)")
def receipts(body: ReceiptsIn, _: str = Depends(api_key("1c")), db: Session = Depends(get_db)):
    res = sales.import_receipts(db, [r.model_dump() for r in body.receipts], source="1c")
    db.commit()
    return res


@router.get("/prices", summary="Цены и уценки для касс")
def prices(only_new: bool = False, _: str = Depends(api_key("1c")), db: Session = Depends(get_db)):
    out = onec.prices(db, only_new)
    db.commit()
    return out


@router.post("/import-folder", summary="Загрузить чеки из папки обмена сейчас")
def import_folder(_: User = Depends(require("analyst")), db: Session = Depends(get_db)):
    return onec.import_folder(db)
