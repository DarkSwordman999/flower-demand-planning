"""Аналитические отчёты (П-13, С-16): за произвольный период, с группировкой, выгрузка в XLSX."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..db import get_db
from ..errors import NotFound
from ..models import User
from ..security import require
from ..services import analytics as an
from ..services import xlsx

router = APIRouter(prefix="/api/reports", tags=["Отчёты"])
viewers = require("director", "analyst", "buyer")


@router.get("")
def list_reports(_: User = Depends(viewers)):
    return [{"code": k, "name": v} for k, v in an.TITLES.items()]


def _build(kind, db, date_from, date_to, group_by, location_id):
    if kind not in an.REPORTS:
        raise NotFound("Нет такого отчёта")
    kw = {"date_from": date_from, "date_to": date_to, "location_id": location_id}
    if group_by:
        kw["group_by"] = group_by
    return an.REPORTS[kind](db, **kw)


@router.get("/{kind}")
def report(kind: str, date_from: date | None = None, date_to: date | None = None, group_by: str = "",
           location_id: int | None = None, _: User = Depends(viewers), db: Session = Depends(get_db)):
    r = _build(kind, db, date_from, date_to, group_by, location_id)
    return {**r, "columns": [{"key": k, "title": t} for k, t in r["columns"]]}


@router.get("/{kind}/xlsx")
def report_xlsx(kind: str, date_from: date | None = None, date_to: date | None = None, group_by: str = "",
                location_id: int | None = None, me: User = Depends(viewers), db: Session = Depends(get_db)):
    r = _build(kind, db, date_from, date_to, group_by, location_id)
    keys = [k for k, _ in r["columns"]]
    rows = [[row.get(k) for k in keys] for row in r["rows"]]
    if r.get("totals"):
        rows.append([r["totals"].get(k) for k in keys])
    data = xlsx.build(r["title"], [t for _, t in r["columns"]], rows,
                      meta=[("Организация", appsettings.get(db, "company_name")),
                            ("Сформировал", f"{me.full_name} ({me.login})"), ("Дата", date.today().strftime("%d.%m.%Y"))],
                      footer=[r["note"]] if r.get("note") else None, sheet=an.TITLES[kind])
    audit.log(db, me, "Выгрузка отчёта в XLSX", "report", kind, r["title"])
    db.commit()
    return xlsx.response(data, f"{an.TITLES[kind]}_{date.today():%Y%m%d}.xlsx")
