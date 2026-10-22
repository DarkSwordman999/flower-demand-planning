"""Начальное наполнение пустой БД: администратор и обязательные справочники."""
from sqlalchemy.orm import Session

from .models import ForecastModel, User, WriteOffReason
from .security import hash_password

REASONS = ["Потеря товарного вида", "Брак", "Повреждение при доставке", "Истёк срок реализации",
           "Недостача при инвентаризации"]


def ensure_base(db: Session, admin_password: str = "admin") -> list[str]:
    """Возвращает список сделанного (для вывода в консоль)."""
    done = []
    if db.query(User).count() == 0:
        db.add(User(login="admin", full_name="Администратор", role="admin", password_hash=hash_password(admin_password)))
        done.append(f"создан пользователь admin (пароль: {admin_password}) — смените пароль после входа")
    if db.query(WriteOffReason).count() == 0:
        db.add_all(WriteOffReason(name=n) for n in REASONS)
        done.append("заполнен справочник причин списания")
    if db.query(ForecastModel).count() == 0:
        db.add(ForecastModel(version=1, algorithm="auto", status="published",
                             params={"season": 7, "holdout": 28},
                             comment="Базовая версия: выбор модели по ряду (сезонная наивная, Хольт–Уинтерс, Кростон)"))
        done.append("опубликована базовая версия модели прогноза")
    db.commit()
    return done
