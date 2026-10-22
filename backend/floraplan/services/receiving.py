"""Приёмка поставок (П-2, С-2, С-3; ПР 5-6 IDEF3 A1; ПР 7-8 «Принять поставку»)."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..errors import DomainError
from ..models import Batch, DiscrepancyAct, PurchaseOrder, User
from . import inventory as inv
from .numbering import next_number


def receive(db: Session, o: PurchaseOrder, items: list[dict], user: User, day: date | None = None) -> dict:
    """items: [{line_id, received_qty, defect_qty, shelf_reduction_days, phyto_ok, quality}].
    Строки без данных считаются не поступившими."""
    day = day or date.today()
    if o.status != "in_transit":
        raise DomainError("Принять можно только заказ в статусе «В пути»")
    limit = float(appsettings.get(db, "discrepancy_pct"))
    by_line = {it["line_id"]: it for it in items}
    unknown = set(by_line) - {ln.id for ln in o.lines}
    if unknown:
        raise DomainError("В приёмке есть строки другого заказа")
    act_lines, batches = [], []
    for ln in o.lines:
        it = by_line.get(ln.id, {"received_qty": 0})
        got = float(it.get("received_qty") or 0)
        defect = float(it.get("defect_qty") or 0)
        if got < 0 or defect < 0 or defect > got + 1e-9:
            raise DomainError(f"«{ln.product.name}»: неверное количество (брак не больше поступившего)")
        reduce = int(it.get("shelf_reduction_days") or 0)
        if reduce < 0 or reduce >= ln.product.shelf_life_days:
            raise DomainError(f"«{ln.product.name}»: сокращение срока от 0 до {ln.product.shelf_life_days - 1} дн.")
        accepted = got - defect
        if o.supplier.imported and got > 0 and not it.get("phyto_ok"):
            act_lines.append({"product": ln.product.name, "ordered": ln.ordered_qty, "received": got, "accepted": 0,
                              "diff": -ln.ordered_qty, "reason": "нет фитосанитарных документов — приёмка запрещена"})
            ln.received_qty = 0
            continue
        ln.received_qty = accepted
        diff = got - ln.ordered_qty
        if ln.ordered_qty > 0 and abs(diff) / ln.ordered_qty * 100 > limit + 1e-9:
            act_lines.append({"product": ln.product.name, "ordered": ln.ordered_qty, "received": got,
                              "accepted": accepted, "diff": diff, "reason": "недостача" if diff < 0 else "излишек"})
        elif ln.ordered_qty == 0 and got > 0:
            act_lines.append({"product": ln.product.name, "ordered": 0, "received": got, "accepted": accepted,
                              "diff": got, "reason": "не заказывался"})
        if defect > 0:
            act_lines.append({"product": ln.product.name, "ordered": ln.ordered_qty, "received": got,
                              "accepted": accepted, "diff": -defect, "reason": "брак"})
        if accepted > 1e-9:
            expiry = day + timedelta(days=ln.product.shelf_life_days - reduce)   # С-3
            quality = it.get("quality") or ("срок сокращён на %d дн." % reduce if reduce else "норма")
            batches.append(inv.create_batch(db, ln.product, o.location_id, accepted, ln.price, day, expiry, user,
                                            ln.id, quality, ref=f"приёмка {o.number}"))
    act = None
    if act_lines:
        act = DiscrepancyAct(number=next_number(db, "АР", DiscrepancyAct.number, day), order_id=o.id, user_id=user.id,
                             lines=act_lines)
        db.add(act)
    o.status = "received"
    audit.log(db, user, "Поставка принята", "order", o.number,
              f"партий {len(batches)}" + (f", акт расхождений {act.number}" if act else ""))
    db.flush()
    return {"batches": [b.id for b in batches], "act_number": act.number if act else None, "act_lines": act_lines}


def labels_html(batches: list[Batch]) -> str:
    """Этикетки партий для печати (С-3, IDEF3 1.6)."""
    cells = []
    for b in batches:
        cells.append(f"""<div class="l"><b>{_e(b.product.name)}</b>
<div>Партия № {b.id} · {_e(b.location.name)}</div>
<div>Поступила: {b.received_at:%d.%m.%Y}</div>
<div class="exp">Годен до: {b.expiry_date:%d.%m.%Y}</div>
<div>Кол-во: {b.qty_initial:g} {_e(b.product.unit)} · {_e(b.product.barcode)}</div></div>""")
    return ("<!doctype html><html lang='ru'><meta charset='utf-8'><title>Этикетки партий</title>"
            "<style>body{font:13px Arial,sans-serif;margin:8mm}.l{display:inline-block;width:62mm;height:34mm;"
            "border:1px dashed #888;padding:3mm;margin:1mm;vertical-align:top;box-sizing:border-box}"
            ".exp{font-size:15px;font-weight:bold;margin:2px 0}@media print{.l{break-inside:avoid}}</style>"
            "<body onload='window.print()'>" + "".join(cells) + "</body></html>")


def _e(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
