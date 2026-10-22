from floraplan.security import hash_password, verify_password


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
