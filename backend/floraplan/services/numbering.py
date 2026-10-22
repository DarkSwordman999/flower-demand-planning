"""Номера документов: ЗП-2026-000123 (заказ), АР- (акт расхождений), АС- (акт списания)."""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session


def next_number(db: Session, prefix: str, column, day: date | None = None) -> str:
    year = (day or date.today()).year
    head = f"{prefix}-{year}-"
    last = db.query(func.max(column)).filter(column.like(f"{head}%")).scalar()
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{head}{n:06d}"
