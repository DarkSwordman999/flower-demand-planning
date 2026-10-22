"""Окружение Alembic: URL берётся из настроек ФлораПлан (или из config.attributes["url"])."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from floraplan import models  # noqa: F401 — регистрирует таблицы
from floraplan.config import get_settings
from floraplan.db import Base

config = context.config
target_metadata = Base.metadata
url = config.attributes.get("url") or get_settings().db_url


def run_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = engine_from_config({"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as conn:
            _run(conn)
    else:
        _run(connectable)


def _run(conn) -> None:
    context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=url.startswith("sqlite"),
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
