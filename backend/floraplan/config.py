"""Настройки системы: переменные окружения с префиксом FLORAPLAN_ или файл .env."""
from functools import lru_cache
from pathlib import Path
import os
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    # в собранной Windows-версии данные лежат рядом с exe, иначе — в backend/data
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLORAPLAN_", env_file=".env", extra="ignore")

    data_dir: Path = _default_data_dir()
    # postgresql+psycopg://user:pass@host:5432/flora_db  или sqlite:///путь.db
    database_url: str = ""
    secret_key: str = "change-me-in-production"
    token_hours: int = 12

    # ключи внешних систем (заголовок X-API-Key)
    shop_api_key: str = "shop-demo-key"
    onec_api_key: str = "1c-demo-key"

    # почта для отправки заказов поставщикам; без SMTP заказы кладутся в data/outbox
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "zakupki@floraplan.local"
    smtp_tls: bool = True

    # погодный сервис Open-Meteo (координаты Тулы по умолчанию)
    weather_enabled: bool = True
    latitude: float = 54.19
    longitude: float = 37.62

    # адрес сайта для активной выгрузки остатков и цен каждые 15 минут (С-14); пусто — сайт сам опрашивает API
    shop_webhook_url: str = ""

    scheduler_enabled: bool = True
    timezone: str = "Europe/Moscow"
    cors_origins: str = ""

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'floraplan.db').as_posix()}"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def inbox_1c_dir(self) -> Path:
        return self.data_dir / "inbox_1c"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.outbox_dir, self.inbox_1c_dir, self.inbox_1c_dir / "processed", self.backup_dir):
            os.makedirs(d, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
