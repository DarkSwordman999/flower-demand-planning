"""Нормативно-справочная информация (П-1, С-1, С-15): товары, поставщики, условия, места, календарь."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import (LOCATION_TYPES, CalendarEvent, HolidayScenario, Location, Product, ProductGroup, Supplier,
                      SupplyCondition, User, WriteOffReason)
from ..security import require

router = APIRouter(prefix="/api/nsi", tags=["НСИ"])
anyone = require()
editors = require("buyer", "analyst")


def _save(db: Session, me: User, action: str, entity: str, obj, details: str = ""):
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Запись с такими данными уже существует")
    audit.log(db, me, action, entity, obj.id, details)
    db.commit()
    return obj


def _get(db: Session, model, pk: int, what: str):
    obj = db.get(model, pk)
    if obj is None:
        raise HTTPException(404, f"{what} не найден(а)")
    return obj


# ------------------------------------------------------------------ группы
class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("/groups")
def groups(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [{"id": g.id, "name": g.name} for g in db.query(ProductGroup).order_by(ProductGroup.name)]


@router.post("/groups")
def create_group(body: GroupIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    g = ProductGroup(name=body.name.strip())
    db.add(g)
    _save(db, me, "Создана товарная группа", "group", g, g.name)
    return {"id": g.id, "name": g.name}


@router.put("/groups/{gid}")
def update_group(gid: int, body: GroupIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    g = _get(db, ProductGroup, gid, "Группа")
    g.name = body.name.strip()
    _save(db, me, "Изменена товарная группа", "group", g, g.name)
    return {"id": g.id, "name": g.name}


# ------------------------------------------------------------------ товары
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = ""
    variety: str = ""
    stem_length: int | None = Field(default=None, ge=0, le=300)
    color: str = ""
    unit: str = "шт"
    shelf_life_days: int = Field(ge=1, le=365)
    pack_multiple: int = Field(default=1, ge=1, le=1000)
    group_id: int
    barcode: str = ""
    price: float = Field(ge=0)
    active: bool = True


def product_out(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "variety": p.variety, "stem_length": p.stem_length,
            "color": p.color, "unit": p.unit, "shelf_life_days": p.shelf_life_days, "pack_multiple": p.pack_multiple,
            "group_id": p.group_id, "group": p.group.name if p.group else "", "barcode": p.barcode,
            "price": p.price, "active": p.active}


@router.get("/products")
def products(q: str = "", group_id: int | None = None, active: bool | None = None,
             _: User = Depends(anyone), db: Session = Depends(get_db)):
    qry = db.query(Product)
    if q:
        like = f"%{q}%"
        qry = qry.filter(Product.name.ilike(like) | Product.barcode.ilike(like) | Product.variety.ilike(like))
    if group_id:
        qry = qry.filter(Product.group_id == group_id)
    if active is not None:
        qry = qry.filter(Product.active == active)
    return [product_out(p) for p in qry.order_by(Product.name)]


@router.get("/products/{pid}")
def product(pid: int, _: User = Depends(anyone), db: Session = Depends(get_db)):
    return product_out(_get(db, Product, pid, "Товар"))


@router.post("/products")
def create_product(body: ProductIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    _get(db, ProductGroup, body.group_id, "Группа")
    p = Product(**body.model_dump())
    db.add(p)
    _save(db, me, "Создан товар", "product", p, p.name)
    return product_out(p)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    p = _get(db, Product, pid, "Товар")
    _get(db, ProductGroup, body.group_id, "Группа")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    _save(db, me, "Изменён товар", "product", p, p.name)
    return product_out(p)


# ------------------------------------------------------------------ поставщики и условия
class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = "Россия"
    lead_time_days: int = Field(ge=0, le=60)
    min_order_sum: float = Field(default=0, ge=0)
    email: str = ""
    order_weekdays: str = "0,3"
    reliability: float = Field(default=0.95, ge=0, le=1)
    active: bool = True


def supplier_out(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "country": s.country, "lead_time_days": s.lead_time_days,
            "min_order_sum": s.min_order_sum, "email": s.email, "order_weekdays": s.order_weekdays,
            "reliability": s.reliability, "active": s.active, "imported": s.imported}


def _weekdays_ok(v: str) -> bool:
    try:
        days = [int(x) for x in v.split(",") if x.strip()]
    except ValueError:
        return False
    return bool(days) and all(0 <= d <= 6 for d in days)


@router.get("/suppliers")
def suppliers(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [supplier_out(s) for s in db.query(Supplier).order_by(Supplier.name)]


@router.post("/suppliers")
def create_supplier(body: SupplierIn, me: User = Depends(require("buyer")), db: Session = Depends(get_db)):
    if not _weekdays_ok(body.order_weekdays):
        raise HTTPException(400, "Дни заказа: номера дней недели через запятую, 0 — понедельник")
    s = Supplier(**body.model_dump())
    db.add(s)
    _save(db, me, "Создан поставщик", "supplier", s, s.name)
    return supplier_out(s)


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: SupplierIn, me: User = Depends(require("buyer")), db: Session = Depends(get_db)):
    if not _weekdays_ok(body.order_weekdays):
        raise HTTPException(400, "Дни заказа: номера дней недели через запятую, 0 — понедельник")
    s = _get(db, Supplier, sid, "Поставщик")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    _save(db, me, "Изменён поставщик", "supplier", s, s.name)
    return supplier_out(s)


class ConditionIn(BaseModel):
    supplier_id: int
    product_id: int
    price: float = Field(gt=0)
    pack_multiple: int = Field(default=1, ge=1, le=1000)


def condition_out(c: SupplyCondition) -> dict:
    return {"id": c.id, "supplier_id": c.supplier_id, "supplier": c.supplier.name, "product_id": c.product_id,
            "product": c.product.name, "price": c.price, "pack_multiple": c.pack_multiple}


@router.get("/conditions")
def conditions(supplier_id: int | None = None, product_id: int | None = None,
               _: User = Depends(anyone), db: Session = Depends(get_db)):
    q = db.query(SupplyCondition)
    if supplier_id:
        q = q.filter(SupplyCondition.supplier_id == supplier_id)
    if product_id:
        q = q.filter(SupplyCondition.product_id == product_id)
    return [condition_out(c) for c in q.order_by(SupplyCondition.id)]


@router.post("/conditions")
def create_condition(body: ConditionIn, me: User = Depends(require("buyer")), db: Session = Depends(get_db)):
    _get(db, Supplier, body.supplier_id, "Поставщик")
    _get(db, Product, body.product_id, "Товар")
    c = SupplyCondition(**body.model_dump())
    db.add(c)
    _save(db, me, "Добавлено условие поставки", "condition", c, f"товар {c.product_id}, цена {c.price}")
    return condition_out(c)


@router.put("/conditions/{cid}")
def update_condition(cid: int, body: ConditionIn, me: User = Depends(require("buyer")), db: Session = Depends(get_db)):
    c = _get(db, SupplyCondition, cid, "Условие поставки")
    c.price, c.pack_multiple = body.price, body.pack_multiple
    _save(db, me, "Изменено условие поставки", "condition", c, f"цена {c.price}, кратность {c.pack_multiple}")
    return condition_out(c)


@router.delete("/conditions/{cid}")
def delete_condition(cid: int, me: User = Depends(require("buyer")), db: Session = Depends(get_db)):
    c = _get(db, SupplyCondition, cid, "Условие поставки")
    audit.log(db, me, "Удалено условие поставки", "condition", c.id, f"{c.supplier.name} — {c.product.name}")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ места хранения
class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = "salon"
    active: bool = True


@router.get("/locations")
def locations(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [{"id": x.id, "name": x.name, "type": x.type, "type_name": LOCATION_TYPES.get(x.type, x.type),
             "active": x.active} for x in db.query(Location).order_by(Location.id)]


@router.post("/locations")
def create_location(body: LocationIn, me: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if body.type not in LOCATION_TYPES:
        raise HTTPException(400, "Тип: warehouse, salon или online")
    x = Location(**body.model_dump())
    db.add(x)
    _save(db, me, "Создано место хранения", "location", x, x.name)
    return {"id": x.id, "name": x.name, "type": x.type, "active": x.active}


@router.put("/locations/{lid}")
def update_location(lid: int, body: LocationIn, me: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if body.type not in LOCATION_TYPES:
        raise HTTPException(400, "Тип: warehouse, salon или online")
    x = _get(db, Location, lid, "Место хранения")
    x.name, x.type, x.active = body.name, body.type, body.active
    _save(db, me, "Изменено место хранения", "location", x, x.name)
    return {"id": x.id, "name": x.name, "type": x.type, "active": x.active}


# ------------------------------------------------------------------ календарь событий
class EventIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=200)
    type: str = "holiday"
    recurring: bool = True
    coefficient: float | None = Field(default=None, gt=0, le=50)
    group_id: int | None = None


def event_out(e: CalendarEvent) -> dict:
    return {"id": e.id, "date": e.date, "name": e.name, "type": e.type, "recurring": e.recurring,
            "coefficient": e.coefficient, "group_id": e.group_id}


@router.get("/events")
def events(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [event_out(e) for e in db.query(CalendarEvent).order_by(CalendarEvent.date)]


@router.post("/events")
def create_event(body: EventIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    if body.type not in ("holiday", "promo"):
        raise HTTPException(400, "Тип события: holiday или promo")
    e = CalendarEvent(**body.model_dump())
    db.add(e)
    _save(db, me, "Добавлено событие календаря", "event", e, f"{e.date} {e.name}")
    return event_out(e)


@router.put("/events/{eid}")
def update_event(eid: int, body: EventIn, me: User = Depends(editors), db: Session = Depends(get_db)):
    e = _get(db, CalendarEvent, eid, "Событие")
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    _save(db, me, "Изменено событие календаря", "event", e, f"{e.date} {e.name}")
    return event_out(e)


@router.delete("/events/{eid}")
def delete_event(eid: int, me: User = Depends(editors), db: Session = Depends(get_db)):
    e = _get(db, CalendarEvent, eid, "Событие")
    audit.log(db, me, "Удалено событие календаря", "event", e.id, f"{e.date} {e.name}")
    db.delete(e)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ сценарии праздников (С-15)
class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    event_date: date
    days_before: int = Field(default=2, ge=0, le=14)
    last_delivery_date: date
    coefficients: dict[str, float] = {}
    comment: str = ""


def scenario_out(s: HolidayScenario) -> dict:
    return {"id": s.id, "name": s.name, "event_date": s.event_date, "days_before": s.days_before,
            "last_delivery_date": s.last_delivery_date, "coefficients": s.coefficients, "approved": s.approved,
            "comment": s.comment}


def _check_scenario(body: ScenarioIn):
    if body.last_delivery_date > body.event_date:
        raise HTTPException(400, "Последняя поставка должна быть не позже даты праздника")
    for k, v in body.coefficients.items():
        if v <= 0 or v > 50:
            raise HTTPException(400, f"Коэффициент группы {k} должен быть от 0 до 50")


@router.get("/scenarios")
def scenarios(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [scenario_out(s) for s in db.query(HolidayScenario).order_by(HolidayScenario.event_date.desc())]


@router.post("/scenarios")
def create_scenario(body: ScenarioIn, me: User = Depends(require("buyer", "director")), db: Session = Depends(get_db)):
    _check_scenario(body)
    s = HolidayScenario(**body.model_dump())
    db.add(s)
    _save(db, me, "Создан сценарий праздника", "scenario", s, s.name)
    return scenario_out(s)


@router.put("/scenarios/{sid}")
def update_scenario(sid: int, body: ScenarioIn, me: User = Depends(require("buyer", "director")),
                    db: Session = Depends(get_db)):
    _check_scenario(body)
    s = _get(db, HolidayScenario, sid, "Сценарий")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    s.approved = False  # изменённый сценарий утверждается заново
    _save(db, me, "Изменён сценарий праздника", "scenario", s, s.name)
    return scenario_out(s)


@router.post("/scenarios/{sid}/approve")
def approve_scenario(sid: int, me: User = Depends(require("buyer", "director")), db: Session = Depends(get_db)):
    s = _get(db, HolidayScenario, sid, "Сценарий")
    s.approved = True
    _save(db, me, "Утверждён сценарий праздника", "scenario", s, s.name)
    return scenario_out(s)


# ------------------------------------------------------------------ причины списания
@router.get("/writeoff-reasons")
def reasons(_: User = Depends(anyone), db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(WriteOffReason).order_by(WriteOffReason.id)]


@router.post("/writeoff-reasons")
def create_reason(body: GroupIn, me: User = Depends(require("admin")), db: Session = Depends(get_db)):
    r = WriteOffReason(name=body.name.strip())
    db.add(r)
    _save(db, me, "Добавлена причина списания", "reason", r, r.name)
    return {"id": r.id, "name": r.name}


@router.put("/writeoff-reasons/{rid}")
def update_reason(rid: int, body: GroupIn, me: User = Depends(require("admin")), db: Session = Depends(get_db)):
    r = _get(db, WriteOffReason, rid, "Причина списания")
    r.name = body.name.strip()
    _save(db, me, "Изменена причина списания", "reason", r, r.name)
    return {"id": r.id, "name": r.name}
