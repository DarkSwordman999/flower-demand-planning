"""Администрирование: пользователи и роли, журнал действий, параметры системы, каналы продаж."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..db import get_db
from ..models import ROLES, AuditLog, IntegrationLog, Location, OnlineOrder, SalesChannel, User
from ..security import hash_password, require
from ..services import shop
from .auth import UserOut, user_out

router = APIRouter(prefix="/api/admin", tags=["Администрирование"])
admin_only = require("admin")


@router.get("/roles")
def roles(_: User = Depends(require())):
    return [{"code": k, "name": v} for k, v in ROLES.items()]


@router.get("/users", response_model=list[UserOut])
def users(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.query(User).order_by(User.login)]


class UserIn(BaseModel):
    login: str = Field(min_length=2, max_length=64)
    full_name: str
    role: str
    location_id: int | None = None
    password: str | None = None
    active: bool = True


def _check(db: Session, body: UserIn, uid: int | None = None):
    body.login = body.login.strip()
    if body.role not in ROLES:
        raise HTTPException(400, "Неизвестная роль")
    if body.password is not None and len(body.password) < 6:
        raise HTTPException(400, "Пароль должен быть не короче 6 символов")
    if body.location_id is not None and db.get(Location, body.location_id) is None:
        raise HTTPException(400, "Место хранения не найдено")
    other = db.query(User).filter(User.login == body.login).first()
    if other is not None and other.id != uid:
        raise HTTPException(409, "Пользователь с таким логином уже есть")


@router.post("/users", response_model=UserOut)
def create_user(body: UserIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check(db, body)
    if not body.password:
        raise HTTPException(400, "Задайте пароль")
    u = User(login=body.login, full_name=body.full_name, role=body.role, location_id=body.location_id,
             active=body.active, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit.log(db, me, "Создан пользователь", "user", u.id, f"{u.login}, {ROLES[u.role]}")
    db.commit()
    return user_out(u)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
    _check(db, body, u.id)
    if u.id == me.id and (body.role != "admin" or not body.active):
        raise HTTPException(400, "Нельзя снять с себя роль администратора или заблокировать себя")
    u.login, u.full_name, u.role, u.location_id, u.active = body.login, body.full_name, body.role, body.location_id, body.active
    if body.password:
        u.password_hash = hash_password(body.password)
    audit.log(db, me, "Изменён пользователь", "user", u.id, f"{u.login}, {ROLES[u.role]}, активен={u.active}")
    db.commit()
    return user_out(u)


@router.get("/audit")
def audit_log(date_from: date | None = None, date_to: date | None = None, q: str = "", limit: int = 500,
              _: User = Depends(require("director")), db: Session = Depends(get_db)):
    qry = db.query(AuditLog)
    if date_from:
        qry = qry.filter(AuditLog.ts >= datetime.combine(date_from, time.min))
    if date_to:
        qry = qry.filter(AuditLog.ts <= datetime.combine(date_to, time.max))
    if q:
        like = f"%{q}%"
        qry = qry.filter((AuditLog.action.ilike(like)) | (AuditLog.details.ilike(like)) | (AuditLog.user_login.ilike(like)))
    rows = qry.order_by(AuditLog.ts.desc()).limit(min(limit, 5000)).all()
    return [{"id": r.id, "ts": r.ts, "user": r.user_login, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "details": r.details} for r in rows]


@router.get("/integration-log")
def integration_log(system: str = "", limit: int = 200, _: User = Depends(require("analyst", "director")),
                    db: Session = Depends(get_db)):
    q = db.query(IntegrationLog)
    if system:
        q = q.filter(IntegrationLog.system == system)
    return [{"id": r.id, "ts": r.ts, "system": r.system, "direction": r.direction, "status": r.status,
             "message": r.message} for r in q.order_by(IntegrationLog.ts.desc()).limit(min(limit, 2000))]


@router.get("/settings")
def get_settings_(_: User = Depends(require()), db: Session = Depends(get_db)):
    return appsettings.get_all(db)


@router.put("/settings")
def put_settings(values: dict, me: User = Depends(require("director")), db: Session = Depends(get_db)):
    try:
        values = appsettings.validate(db, values)
    except ValueError as e:
        raise HTTPException(400, str(e))
    appsettings.set_many(db, values)
    audit.log(db, me, "Изменены параметры системы", "settings", "", ", ".join(f"{k}={v}" for k, v in values.items()))
    db.commit()
    return appsettings.get_all(db)


# ------------------------------------------------------------------ резервное копирование (Н-1)
@router.post("/backups")
def make_backup(me: User = Depends(admin_only), db: Session = Depends(get_db)):
    from ..services import backup
    p = backup.make()
    audit.log(db, me, "Резервная копия БД", "backup", p.name)
    db.commit()
    return {"name": p.name}


@router.get("/backups")
def backups(_: User = Depends(admin_only)):
    from ..services import backup
    return backup.listing()


@router.get("/backups/{name}")
def download_backup(name: str, _: User = Depends(admin_only)):
    from fastapi.responses import FileResponse
    from ..services import backup
    return FileResponse(backup.path_of(name), filename=name)


@router.get("/jobs")
def jobs(request: Request, _: User = Depends(require("analyst", "director"))):
    """Задачи планировщика и время следующего запуска."""
    sched = getattr(request.app.state, "scheduler", None)
    names = {"forecast": "Прогноз спроса", "onec": "Чеки «1С» из папки обмена", "weather": "Погода",
             "shop": "Выгрузка остатков на сайт", "backup": "Резервная копия БД",
             "anonymize": "Обезличивание данных покупателей (152-ФЗ)",
             "settings": "Применение часа расчёта прогноза из параметров"}
    if sched is None:
        return {"running": False, "jobs": []}
    return {"running": True, "jobs": [{"id": j.id, "name": names.get(j.id, j.id), "next_run": j.next_run_time}
                                      for j in sched.get_jobs()]}


# ------------------------------------------------------------ каналы продаж (Р-4)
class ChannelIn(BaseModel):
    code: str = Field(min_length=2, max_length=30, description="латиница, цифры, - и _; префикс номеров заказов")
    name: str = Field(min_length=1, max_length=100)
    location_id: int
    price_factor: float = Field(default=1.0, gt=0, le=10)
    active: bool = True


def _channel_out(c: SalesChannel, key: str | None = None) -> dict:
    out = {"id": c.id, "code": c.code, "name": c.name, "location_id": c.location_id, "location": c.location.name,
           "price_factor": c.price_factor, "active": c.active, "created_at": c.created_at}
    if key:
        out["api_key"] = key          # показывается один раз: в БД хранится только хеш
    return out


def _channel_check(db: Session, body: ChannelIn, cid: int | None = None) -> None:
    if not shop.CODE_RE.match(body.code) or body.code in ("site", "shop", "1c"):
        raise HTTPException(400, "Код канала: 2–30 символов — строчная латиница, цифры, «-» и «_»")
    if db.get(Location, body.location_id) is None:
        raise HTTPException(400, "Место хранения не найдено")
    other = db.query(SalesChannel).filter(SalesChannel.code == body.code).first()
    if other is not None and other.id != cid:
        raise HTTPException(409, "Канал с таким кодом уже есть")


@router.get("/channels")
def channels(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [_channel_out(c) for c in db.query(SalesChannel).order_by(SalesChannel.name)]


@router.post("/channels", summary="Подключить канал продаж: выдаётся ключ API")
def create_channel(body: ChannelIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    _channel_check(db, body)
    key = shop.new_key()
    c = SalesChannel(code=body.code, name=body.name, location_id=body.location_id, price_factor=body.price_factor,
                     active=body.active, key_hash=shop.key_hash(key))
    db.add(c)
    db.flush()
    audit.log(db, me, "Подключён канал продаж", "channel", c.id, f"{c.code}, {c.name}")
    db.commit()
    return _channel_out(c, key)


@router.put("/channels/{cid}")
def update_channel(cid: int, body: ChannelIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    c = db.get(SalesChannel, cid)
    if c is None:
        raise HTTPException(404, "Канал не найден")
    if body.code != c.code and db.query(OnlineOrder).filter(OnlineOrder.channel_id == c.id).first():
        raise HTTPException(400, "Код канала с заказами менять нельзя: он входит в номера заказов")
    _channel_check(db, body, cid)
    c.code, c.name, c.location_id, c.price_factor, c.active = (body.code, body.name, body.location_id,
                                                               body.price_factor, body.active)
    audit.log(db, me, "Изменён канал продаж", "channel", c.id, f"{c.code}, активен: {c.active}")
    db.commit()
    return _channel_out(c)


@router.post("/channels/{cid}/key", summary="Выдать новый ключ API (старый перестаёт действовать)")
def rotate_channel_key(cid: int, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    c = db.get(SalesChannel, cid)
    if c is None:
        raise HTTPException(404, "Канал не найден")
    key = shop.new_key()
    c.key_hash = shop.key_hash(key)
    audit.log(db, me, "Выдан новый ключ канала продаж", "channel", c.id, c.code)
    db.commit()
    return _channel_out(c, key)
