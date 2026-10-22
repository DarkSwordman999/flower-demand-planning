"""Журнал действий пользователей и обмена с внешними системами."""
from sqlalchemy.orm import Session

from .models import AuditLog, IntegrationLog, User


def log(db: Session, user: User | None, action: str, entity: str = "", entity_id: object = "", details: str = "") -> None:
    db.add(AuditLog(user_id=user.id if user else None, user_login=user.login if user else "система",
                    action=action, entity=entity, entity_id=str(entity_id), details=details[:4000]))


def integration(db: Session, system: str, message: str, status: str = "ok", direction: str = "in") -> None:
    db.add(IntegrationLog(system=system, message=message[:4000], status=status, direction=direction))
