"""Общие фикстуры: временная БД (SQLite или FLORAPLAN_TEST_DATABASE_URL), клиент API, вход по ролям.

Для SQLite схема и пользователи создаются один раз в шаблоне, каждый тест получает его копию."""
import os
import shutil
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ.setdefault("FLORAPLAN_SCHEDULER_ENABLED", "false")
os.environ.setdefault("FLORAPLAN_WEATHER_ENABLED", "false")

from floraplan import db, migrate  # noqa: E402
from floraplan.bootstrap import ensure_base  # noqa: E402
from floraplan.config import get_settings  # noqa: E402
from floraplan.models import User  # noqa: E402
from floraplan.security import hash_password  # noqa: E402

ROLES = ["director", "buyer", "storekeeper", "florist", "shop_manager", "analyst"]
PG = os.environ.get("FLORAPLAN_TEST_DATABASE_URL")


def _prepare(url: str) -> None:
    migrate.upgrade(url)
    db.configure(url)
    with db.session() as s:
        ensure_base(s)
        for r in ROLES:
            s.add(User(login=r, full_name=r, role=r, password_hash=hash_password("secret1")))
        s.commit()
    db.engine().dispose()


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    if PG:
        return None
    path = tmp_path_factory.mktemp("tpl") / "template.db"
    _prepare(f"sqlite:///{path.as_posix()}")
    return path


@pytest.fixture
def db_url(tmp_path, monkeypatch, template_db):
    monkeypatch.setenv("FLORAPLAN_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    if PG:  # отдельная база PostgreSQL на тест
        name = "fp_test_" + uuid.uuid4().hex[:10]
        admin = create_engine(PG, isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f"CREATE DATABASE {name}"))
        url = PG.rsplit("/", 1)[0] + "/" + name
        _prepare(url)
        yield url
        db.engine().dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()
    else:
        path = tmp_path / "test.db"
        shutil.copy(template_db, path)
        yield f"sqlite:///{path.as_posix()}"
    get_settings.cache_clear()


@pytest.fixture
def session(db_url):
    db.configure(db_url)
    s = db.session()
    yield s
    s.close()
    db.engine().dispose()


@pytest.fixture
def client(session):
    from floraplan.main import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def login(client):
    """login("buyer") -> заголовки авторизации."""
    cache = {}

    def _login(user: str, password: str | None = None) -> dict:
        pw = password or ("admin" if user == "admin" else "secret1")
        if (user, pw) not in cache:
            r = client.post("/api/auth/token", data={"username": user, "password": pw})
            assert r.status_code == 200, r.text
            cache[(user, pw)] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[(user, pw)]
    return _login
