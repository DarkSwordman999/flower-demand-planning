"""Продажи: запись чеков с расходом по FEFO, агрегаты по дням, загрузка из «1С:Розница» (П-4, С-5)."""
import csv
import io
import json
from collections import OrderedDict
from datetime import date, datetime

from sqlalchemy.orm import Session

from .. import audit
from ..errors import DomainError, NotFound
from ..models import Batch, DailySales, Location, Product, Sale, SaleLine, User
from . import inventory as inv


def add_daily(db: Session, product_id: int, location_id: int, day: date, qty: float, revenue: float) -> None:
    row = db.query(DailySales).filter_by(product_id=product_id, location_id=location_id, day=day).first()
    if row is None:
        db.add(DailySales(product_id=product_id, location_id=location_id, day=day, qty=qty, revenue=revenue))
    else:
        row.qty += qty
        row.revenue += revenue


def _product(db: Session, line: dict) -> Product:
    p = None
    if line.get("product_id"):
        p = db.get(Product, int(line["product_id"]))
    elif line.get("barcode"):
        p = db.query(Product).filter(Product.barcode == str(line["barcode"]).strip()).first()
    if p is None:
        raise NotFound(f"Товар не найден: {line.get('product_id') or line.get('barcode')}")
    return p


def record_sale(db: Session, location_id: int, lines: list[dict], ts: datetime | None = None, channel: str = "pos",
                external_id: str | None = None, user: User | None = None, use_reserved: bool = False) -> tuple[Sale, bool]:
    """Записывает чек. Возвращает (чек, создан_ли). Повтор external_id не создаёт дубликат (С-5).
    Строка: product_id или barcode, qty (< 0 — возврат), price (по умолчанию цена партии), discount (сумма), batch_id."""
    if external_id:
        old = db.query(Sale).filter(Sale.external_id == external_id).first()
        if old is not None:
            return old, False
    if db.get(Location, location_id) is None:
        raise NotFound("Торговая точка не найдена")
    if not lines:
        raise DomainError("Чек без позиций")
    ts = ts or datetime.now()
    day = ts.date()
    sale = Sale(external_id=external_id, location_id=location_id, ts=ts, day=day, channel=channel, total=0)
    db.add(sale)
    db.flush()
    ref = f"чек {external_id or sale.id}"
    total = 0.0
    shortages = []
    for ln in lines:
        p = _product(db, ln)
        qty = float(ln["qty"])
        if abs(qty) < 1e-9:
            continue
        discount = float(ln.get("discount") or 0)
        if qty < 0:   # возврат покупателя — в последнюю партию товара в точке
            price = float(ln.get("price") or p.price)
            b = (db.query(Batch).filter(Batch.product_id == p.id, Batch.location_id == location_id)
                 .order_by(Batch.received_at.desc(), Batch.id.desc()).first())
            if b is not None:
                b.qty += -qty
                inv.move(db, "return", b, -qty, day, user, ref)
            db.add(SaleLine(sale_id=sale.id, product_id=p.id, batch_id=b.id if b else None, qty=qty, price=price,
                            discount=-discount, cost=b.cost if b else 0))
            total += qty * price + discount
            add_daily(db, p.id, location_id, day, qty, qty * price + discount)
            continue
        taken, short = inv.consume(db, p.id, location_id, qty, day, "sale", ref, user,
                                   batch_id=ln.get("batch_id"), use_reserved=use_reserved)
        parts = [(t.batch, t.qty) for t in taken] + ([(None, short)] if short > 1e-9 else [])
        revenue = 0.0
        for b, q in parts:
            price = float(ln["price"]) if ln.get("price") is not None else (inv.unit_price(b) if b else p.price)
            d = discount * q / qty
            db.add(SaleLine(sale_id=sale.id, product_id=p.id, batch_id=b.id if b else None, qty=q, price=price,
                            discount=d, cost=b.cost if b else 0))
            revenue += q * price - d
        total += revenue
        if short > 1e-9:
            shortages.append(f"{p.name}: {short:g}")
        add_daily(db, p.id, location_id, day, qty, revenue)
    sale.total = round(total, 2)
    if shortages:
        audit.log(db, user, "Продажа сверх учётного остатка", "sale", sale.id, "; ".join(shortages))
    db.flush()
    return sale, True


def parse_receipts(content: bytes, filename: str) -> list[dict]:
    """JSON {"receipts": [...]} или CSV: чек;дата;точка;штрихкод;количество;цена;скидка."""
    text = content.decode("utf-8-sig")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
        data = json.loads(text)
        return data["receipts"] if isinstance(data, dict) else data
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    norm = {"чек": "id", "дата": "datetime", "точка": "store", "штрихкод": "barcode", "количество": "qty",
            "цена": "price", "скидка": "discount", "товар": "product_id"}
    receipts: "OrderedDict[str, dict]" = OrderedDict()
    for row in reader:
        r = {norm.get(k.strip().lower(), k.strip().lower()): (v or "").strip() for k, v in row.items() if k}
        if not r.get("id"):
            continue
        rc = receipts.setdefault(r["id"], {"id": r["id"], "datetime": r.get("datetime"), "store": r.get("store"),
                                           "lines": []})
        line = {k: r[k] for k in ("barcode", "product_id") if r.get(k)}
        for k in ("qty", "price", "discount"):
            if r.get(k):
                try:
                    line[k] = float(r[k].replace(" ", "").replace(" ", "").replace(",", "."))
                except ValueError:
                    raise DomainError(f"чек {r['id']}: «{r[k]}» — не число в поле «{k}»")
        rc["lines"].append(line)
    return list(receipts.values())


def _location(db: Session, store) -> Location:
    loc = None
    if store is None or store == "":
        raise DomainError("В чеке не указана торговая точка")
    if isinstance(store, (int, float)) or str(store).isdigit():
        loc = db.get(Location, int(store))
    if loc is None:
        loc = db.query(Location).filter(Location.name == str(store)).first()
    if loc is None:
        raise NotFound(f"Торговая точка не найдена: {store}")
    return loc


def _ts(v) -> datetime:
    if not v:
        return datetime.now()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(v)[:19], fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(str(v))


def import_receipts(db: Session, receipts: list[dict], user: User | None = None, source: str = "1c") -> dict:
    """Загрузка пачки чеков: каждый чек — отдельно, ошибки не останавливают остальные."""
    created = skipped = 0
    errors = []
    for rc in receipts:
        try:
            with db.begin_nested():
                ext = str(rc.get("id") or "").strip() or None
                if ext:
                    ext = f"{source}:{ext}"
                loc = _location(db, rc.get("store") if rc.get("store") is not None else rc.get("location_id"))
                _, new = record_sale(db, loc.id, rc.get("lines", []), _ts(rc.get("datetime")), "pos", ext, user)
                created += new
                skipped += not new
        except (DomainError, KeyError, ValueError, TypeError) as e:
            errors.append(f"чек {rc.get('id')}: {getattr(e, 'message', e)}")
    msg = f"чеков загружено {created}, повторных {skipped}, ошибок {len(errors)}"
    audit.integration(db, source, msg + ("; " + "; ".join(errors[:20]) if errors else ""),
                      status="ok" if not errors else "warn")
    db.flush()
    return {"created": created, "skipped": skipped, "errors": errors}
