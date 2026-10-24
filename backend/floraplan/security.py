"""Аутентификация (JWT), хэши паролей и разграничение доступа по ролям (Б-1)."""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .config import get_settings
from .db import session as db_session
from .models import User

_ITER = 200_000
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def make_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.token_hours)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.token_secret, algorithm="HS256")


def current_user(token: str | None = Depends(oauth2)) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, get_settings().token_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сеанс истёк, войдите снова",
                            headers={"WWW-Authenticate": "Bearer"})
    with db_session("autocommit") as s:   # только чтение, без транзакции: не мешает записи в сессии запроса
        user = s.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь заблокирован")
    return user


def require(*roles: str):
    """Зависимость: доступ только указанным ролям (администратор допускается всегда)."""
    def dep(user: User = Depends(current_user)) -> User:
        if roles and user.role not in roles and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этой операции")
        return user
    return dep


def api_key(system: str):
    """Зависимость для внешних систем: заголовок X-API-Key (интернет-магазин, «1С»)."""
    def dep(x_api_key: str | None = Header(default=None)) -> str:
        s = get_settings()
        expected = {"shop": s.shop_api_key, "1c": s.onec_api_key}[system]
        if not x_api_key or not hmac.compare_digest(x_api_key, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный ключ API")
        return system
    return dep
