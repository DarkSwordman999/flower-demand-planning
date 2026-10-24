import os
import shutil

import pytest

from floraplan.models import User
from floraplan.security import hash_password, verify_password

PG = bool(os.environ.get("FLORAPLAN_TEST_DATABASE_URL"))


def test_password_hash_roundtrip():
    h = hash_password("Розы-2026")
    assert verify_password("Розы-2026", h)
    assert not verify_password("розы-2026", h)
    assert not verify_password("x", "мусор")


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_and_me(client, login):
    h = login("admin")
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "admin" and me["role_name"] == "Администратор"


def test_wrong_password_and_no_token(client):
    assert client.post("/api/auth/token", data={"username": "admin", "password": "нет"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_roles_are_enforced(client, login):
    assert client.get("/api/admin/users", headers=login("florist")).status_code == 403
    assert client.get("/api/admin/users", headers=login("admin")).status_code == 200


def test_user_lifecycle_and_audit(client, login):
    h = login("admin")
    r = client.post("/api/admin/users", headers=h,
                    json={"login": "ivanova", "full_name": "Иванова А. А.", "role": "buyer", "password": "qwerty1"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert client.post("/api/admin/users", headers=h,
                       json={"login": "ivanova", "full_name": "x", "role": "buyer", "password": "qwerty1"}).status_code == 409
    login("ivanova", "qwerty1")
    r = client.put(f"/api/admin/users/{uid}", headers=h,
                   json={"login": "ivanova", "full_name": "Иванова А. А.", "role": "buyer", "active": False})
    assert r.status_code == 200
    assert client.post("/api/auth/token", data={"username": "ivanova", "password": "qwerty1"}).status_code == 401
    log = client.get("/api/admin/audit", headers=h).json()
    assert any(x["action"] == "Создан пользователь" for x in log)


def test_admin_cannot_lock_himself(client, login):
    h = login("admin")
    me = client.get("/api/auth/me", headers=h).json()
    r = client.put(f"/api/admin/users/{me['id']}", headers=h,
                   json={"login": "admin", "full_name": "A", "role": "admin", "active": False})
    assert r.status_code == 400


def test_change_password(client, login):
    h = login("buyer")
    assert client.post("/api/auth/password", headers=h, json={"old_password": "bad", "new_password": "newpass1"}).status_code == 400
    assert client.post("/api/auth/password", headers=h, json={"old_password": "secret1", "new_password": "newpass1"}).status_code == 200
    login("buyer", "newpass1")


def test_settings(client, login):
    h = login("director")
    s = client.get("/api/admin/settings", headers=h).json()
    assert s["expiring_days"] == 2 and s["discrepancy_pct"] == 2.0
    r = client.put("/api/admin/settings", headers=h, json={"weekly_budget": 500000})
    assert r.json()["weekly_budget"] == 500000
    assert client.put("/api/admin/settings", headers=h, json={"нет_такого": 1}).status_code == 400
    assert client.put("/api/admin/settings", headers=login("florist"), json={"weekly_budget": 1}).status_code == 403


def test_backup(client, login):
    h = login("admin")
    r = client.post("/api/admin/backups", headers=h)
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert [b["name"] for b in client.get("/api/admin/backups", headers=h).json()] == [name]
    f = client.get(f"/api/admin/backups/{name}", headers=h)
    assert f.status_code == 200 and f.content[:5] == (b"PGDMP" if PG else b"SQLit")
    assert client.get("/api/admin/backups/..%2Fsecret", headers=h).status_code == 404
    assert client.get("/api/admin/jobs", headers=login("director")).json() == {"running": False, "jobs": []}



@pytest.mark.skipif(PG and not shutil.which("pg_restore"), reason="нет pg_dump/pg_restore")
def test_restore(session, tmp_path):
    """Н-1: восстановление из копии возвращает данные на момент копии; текущее состояние сохраняется."""
    from floraplan import db
    from floraplan.cli import main as cli
    from floraplan.errors import DomainError
    from floraplan.services import backup
    copy = backup.make()
    with db.session() as s:
        s.add(User(login="after_copy", full_name="x", role="florist", password_hash="x"))
        s.commit()
    cli(["restore", copy.name, "--yes"])
    with db.session() as s:
        assert s.query(User).filter_by(login="after_copy").first() is None
        assert s.query(User).filter_by(login="buyer").one()
    safety = next(b for b in backup.listing() if "before-restore" in b["name"])
    backup.restore(backup.path_of(safety["name"]))         # откат восстановления
    with db.session() as s:
        assert s.query(User).filter_by(login="after_copy").one()
    bad = tmp_path / ("not.dump" if PG else "not.db")
    bad.write_bytes(b"not a database")
    with pytest.raises(DomainError):
        backup.restore(bad)
    with pytest.raises(SystemExit):
        cli(["restore", "нет-такой-копии.db", "--yes"])


def test_scheduler_jobs_run(session):
    from floraplan import scheduler
    from floraplan.models import IntegrationLog
    scheduler.job_onec()     # пустая папка — без записи
    scheduler.job_backup()
    session.expire_all()
    msgs = [x.message for x in session.query(IntegrationLog).filter_by(system="scheduler")]
    assert any("резервная копия" in m for m in msgs)


def test_scheduler_starts_with_all_jobs(session):
    from floraplan import scheduler
    s = scheduler.start(paused=True)
    try:
        assert {j.id for j in s.get_jobs()} == {"forecast", "onec", "weather", "shop", "backup", "anonymize"}
        f = s.get_job("forecast").trigger
        assert "hour='3'" in str(f)
    finally:
        s.shutdown(wait=False)


def test_token_secret_generated_when_not_set(tmp_path, monkeypatch):
    """Б-1: без FLORAPLAN_SECRET_KEY (или с примером из .env.example) токены подписываются случайным ключом
    из data/secret.key, а не общеизвестной строкой — иначе вход можно подделать."""
    from floraplan.config import Settings
    for weak in ("", "change-me-in-production"):
        d = tmp_path / (weak or "empty")
        s = Settings(data_dir=d, secret_key=weak)
        key = s.token_secret
        assert len(key) >= 40 and key != weak
        assert (d / "secret.key").read_text(encoding="ascii") == key
        assert Settings(data_dir=d, secret_key=weak).token_secret == key     # тот же ключ после перезапуска
    assert Settings(data_dir=tmp_path / "own", secret_key="мой-ключ").token_secret == "мой-ключ"
    assert not (tmp_path / "own" / "secret.key").exists()


def test_token_with_default_key_rejected(client):
    import jwt
    from datetime import datetime, timedelta, timezone
    forged = jwt.encode({"sub": "1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "change-me-in-production", algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
