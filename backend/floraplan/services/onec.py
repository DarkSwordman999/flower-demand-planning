"""Обмен с «1С:Розница» и кассами (В-1): папка обмена для чеков, выгрузка цен и уценок."""
import json
import shutil
from datetime import date

from sqlalchemy.orm import Session, joinedload

from .. import audit
from ..config import get_settings
from ..models import Batch, Markdown, Product
from . import inventory as inv
from .sales import import_receipts, parse_receipts


def import_folder(db: Session) -> dict:
    """Чеки, выложенные «1С» в data/inbox_1c (*.json, *.csv), загружаются и переносятся в processed/.
    Повторная загрузка не создаёт дубликатов, поэтому пропущенный период можно просто выложить заново."""
    s = get_settings()
    s.ensure_dirs()
    total = {"files": 0, "created": 0, "skipped": 0, "errors": []}
    for f in sorted(list(s.inbox_1c_dir.glob("*.json")) + list(s.inbox_1c_dir.glob("*.csv"))):
        try:
            res = import_receipts(db, parse_receipts(f.read_bytes(), f.name), source="1c")
        except Exception as e:  # битый файл не должен останавливать обмен
            db.rollback()
            audit.integration(db, "1c", f"файл {f.name}: {e}", status="error")
            db.commit()
            total["errors"].append(f"{f.name}: {e}")
            continue
        db.commit()
        total["files"] += 1
        total["created"] += res["created"]
        total["skipped"] += res["skipped"]
        total["errors"] += res["errors"]
        shutil.move(str(f), str(s.inbox_1c_dir / "processed" / f.name))
    return total


def prices(db: Session, only_new: bool = False) -> dict:
    """Цены для касс: базовые цены товаров и цены уценённых партий (С-12 → касса)."""
    today = date.today()
    base = [{"product_id": p.id, "barcode": p.barcode, "name": p.name, "price": p.price}
            for p in db.query(Product).filter(Product.active.is_(True)).order_by(Product.id)]
    q = db.query(Markdown).options(joinedload(Markdown.batch).joinedload(Batch.product))
    if only_new:
        q = q.filter(Markdown.exported.is_(False))
    marks = []
    for m in q.order_by(Markdown.id):
        b = m.batch
        if b.qty > 1e-9 and b.expiry_date >= today:
            marks.append({"batch_id": b.id, "product_id": b.product_id, "barcode": b.product.barcode,
                          "location_id": b.location_id, "discount_pct": m.discount_pct, "price": m.price,
                          "valid_until": b.expiry_date})
        m.exported = True
    audit.integration(db, "1c", f"выгружено цен {len(base)}, уценок {len(marks)}", direction="out")
    return {"date": today, "prices": base, "markdowns": marks}


def receipts_example() -> str:
    return json.dumps({"receipts": [{"id": "000123", "datetime": "2026-10-22T12:30:00", "store": "Салон «Центр»",
                                     "lines": [{"barcode": "4600000000011", "qty": 11, "price": 150, "discount": 0}]}]},
                      ensure_ascii=False, indent=2)
