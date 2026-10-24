"""Вход в систему и сведения о текущем пользователе."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..db import session as db_session
from ..models import ROLES, User
from ..security import current_user, hash_password, make_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["Вход"])


class UserOut(BaseModel):
    id: int
    login: str
    full_name: str
    role: str
    role_name: str
    location_id: int | None
    active: bool = True


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, login=u.login, full_name=u.full_name, role=u.role, role_name=ROLES.get(u.role, u.role),
                   location_id=u.location_id, active=u.active)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/token", response_model=TokenOut, summary="Получить токен по логину и паролю")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # поиск и проверка пароля (PBKDF2, ~0,3 с) — вне пишущей транзакции, чтобы входы не держали блокировку записи
    with db_session("autocommit") as s:
        user = s.query(User).filter(User.login == form.username.strip()).first()
    if user is None or not user.active or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    audit.log(db, user, "Вход в систему")
    db.commit()
    return TokenOut(access_token=make_token(user), user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/password", summary="Сменить свой пароль")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Пароль должен быть не короче 6 символов")
    u = db.get(User, user.id)
    u.password_hash = hash_password(body.new_password)
    audit.log(db, u, "Смена пароля", "user", u.id)
    db.commit()
    return {"ok": True}
