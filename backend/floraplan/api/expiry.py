"""Контроль сроков реализации: рекомендации по уценке, уценка, партии с истёкшим сроком (П-9, С-12)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import require
from ..services import expiry as svc

router = APIRouter(prefix="/api/expiry", tags=["Сроки и уценка"])
staff = require("florist", "storekeeper", "director", "buyer")


@router.get("/recommendations")
def recommendations(location_id: int | None = None, me: User = Depends(staff), db: Session = Depends(get_db)):
    return svc.recommendations(db, location_id or (me.location_id if me.role == "florist" else None))


@router.get("/expired")
def expired(location_id: int | None = None, me: User = Depends(staff), db: Session = Depends(get_db)):
    return svc.expired(db, location_id or (me.location_id if me.role == "florist" else None))


class MarkdownItem(BaseModel):
    batch_id: int
    discount_pct: float = Field(gt=0, le=100)


class MarkdownIn(BaseModel):
    items: list[MarkdownItem]


@router.post("/markdown", summary="Подтвердить уценку партий")
def markdown(body: MarkdownIn, me: User = Depends(require("florist")), db: Session = Depends(get_db)):
    res = svc.apply(db, [i.model_dump() for i in body.items], me)
    db.commit()
    return res
