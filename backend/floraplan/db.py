"""Подключение к БД (PostgreSQL или SQLite) и сессии SQLAlchemy."""
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def make_engine(url: str):
    kw = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(conn, _):
            conn.isolation_level = None   # транзакции открываем сами (см. _begin)
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        @event.listens_for(eng, "begin")
        def _begin(conn):
            # Режим транзакции SQLite (в PostgreSQL не нужен):
            #  immediate — изменяющие запросы API и короткие задачи: читают и сразу пишут, поэтому встают
            #              в очередь писателей и ждут, а не падают с «database is locked»;
            #  deferred  — по умолчанию: долгие чтения (прогноз) не держат блокировку записи;
            #  autocommit — без транзакции (наблюдающая сессия в тестах).
            mode = conn.get_execution_options().get("sqlite_tx", "deferred")
            if mode == "immediate":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            elif mode == "deferred":
                conn.exec_driver_sql("BEGIN")
    return eng


def configure(url: str | None = None) -> None:
    """Создаёт движок и фабрику сессий (повторный вызов — переподключение, нужен тестам)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url or get_settings().db_url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def engine():
    if _engine is None:
        configure()
    return _engine


def session(mode: str | None = None) -> Session:
    """mode — режим транзакции SQLite: immediate | deferred (по умолчанию) | autocommit."""
    if _SessionLocal is None:
        configure()
    if mode:
        return _SessionLocal(bind=engine().execution_options(sqlite_tx=mode))
    return _SessionLocal()


def get_db(request: Request) -> Iterator[Session]:
    """Сессия запроса: изменяющие запросы — immediate, чтение — deferred."""
    db = session("immediate" if request.method not in ("GET", "HEAD", "OPTIONS") else None)
    try:
        yield db
    finally:
        db.close()


def get_db_long() -> Iterator[Session]:
    """Для долгих операций, которые сами фиксируют свои записи (расчёт и оценка прогноза)."""
    db = session()
    try:
        yield db
    finally:
        db.close()
