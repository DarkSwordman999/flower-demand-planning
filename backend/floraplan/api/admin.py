"""Администрирование: пользователи и роли, журнал действий, параметры системы."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import appsettings, audit
from ..db import get_db
from ..models import ROLES, AuditLog, IntegrationLog, User
from ..security import hash_password, require
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


def _check(body: UserIn):
    if body.role not in ROLES:
        raise HTTPException(400, "Неизвестная роль")
    if body.password is not None and len(body.password) < 6:
        raise HTTPException(400, "Пароль должен быть не короче 6 символов")


@router.post("/users", response_model=UserOut)
def create_user(body: UserIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check(body)
    if not body.password:
        raise HTTPException(400, "Задайте пароль")
    if db.query(User).filter(User.login == body.login).first():
        raise HTTPException(409, "Пользователь с таким логином уже есть")
    u = User(login=body.login, full_name=body.full_name, role=body.role, location_id=body.location_id,
             active=body.active, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit.log(db, me, "Создан пользователь", "user", u.id, f"{u.login}, {ROLES[u.role]}")
    db.commit()
    return user_out(u)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserIn, me: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check(body)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
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
        appsettings.set_many(db, values)
    except KeyError as e:
        raise HTTPException(400, f"Неизвестный параметр {e}")
    audit.log(db, me, "Изменены параметры системы", "settings", "", ", ".join(f"{k}={v}" for k, v in values.items()))
    db.commit()
    return appsettings.get_all(db)
