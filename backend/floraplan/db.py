"""Подключение к БД (PostgreSQL или SQLite) и сессии SQLAlchemy."""
from collections.abc import Iterator

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
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
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


def session() -> Session:
    if _SessionLocal is None:
        configure()
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = session()
    try:
        yield db
    finally:
        db.close()
