"""Применение миграций схемы БД (alembic upgrade head) без файла alembic.ini."""
from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import get_settings

SCRIPTS = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPTS))
    cfg.attributes["url"] = url or get_settings().db_url
    return cfg


def upgrade(url: str | None = None) -> None:
    get_settings().ensure_dirs()
    command.upgrade(alembic_config(url), "head")


def revision(message: str, url: str | None = None) -> None:
    """Для разработчика: новая миграция по изменениям моделей."""
    command.revision(alembic_config(url), message=message, autogenerate=True)
