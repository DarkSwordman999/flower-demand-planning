import math
from datetime import date, timedelta

import pytest

import history
from factories import reference
from floraplan import appsettings
from floraplan.config import get_settings
from floraplan.models import Batch, HolidayScenario, PurchaseOrder, Supplier, User
from floraplan.services import forecasting as fs
from floraplan.services import inventory as inv
from floraplan.services import purchasing as pur

T = date.today()


# ---------------------------------------------------------------- формулы
def test_service_level_newsvendor():
    # Cu = 150 − 60 = 90, Co = 60 → α = 0,6
    assert pur.service_level(150, 60, 0, 0.5, 0.95) == pytest.approx(0.6)
    assert pur.service_level(1000, 10, 0, 0.5, 0.95) == 0.95       # верхняя граница
    assert pur.service_level(50, 60, 0, 0.5, 0.95) == 0.5           # убыточная позиция — нижняя граница


def test_rounding_to_pack():
    assert pur.ceil_to(41, 20) == 60 and pur.ceil_to(40, 20) == 40 and pur.ceil_to(0, 20) == 0


def test_next_delivery_by_schedule():
    sup = Supplier(name="x", lead_time_days=5, order_weekdays="0,3")
    monday = date(2026, 10, 19)
    assert pur.next_delivery(sup, monday) == date(2026, 10, 22) + timedelta(days=5)   # чт + 5


def test_usable_stock_respects_expiry():
    b1 = Batch(qty=30, reserved=0, expiry_date=T + timedelta(days=1))
    b2 = Batch(qty=10, reserved=0, expiry_date=T + timedelta(days=10))
    demand = {T + timedelta(days=i): 10.0 for i in range(5)}
    # из первой партии успеют продать только 20 (2 дня по 10), вторая — 10 целиком
    assert pur.usable_stock([b1, b2], demand, T) == 30


# ---------------------------------------------------------------- расчёт на данных
@pytest.fixture
def ready(session):
    ref = reference(session)
    history.make(session, ref, T - timedelta(days=1), days=200, events=False)
    r = fs.run(session, base=T)
    assert r.status == "ok"
    u = session.query(User).filter_by(login="storekeeper").one()
    inv.create_batch(session, ref.rose, ref.salon.id, 40, 60, T - timedelta(days=2), T + timedelta(days=5), u)
    session.commit()
    return ref


def test_plan_follows_formula(session, ready):
    ref = ready
    p = pur.plan(session, ref.imp.id)
    ln = next(x for x in p["lines"] if x["product_id"] == ref.rose.id)
    c = ln["calc"]
    assert c["alpha"] == pytest.approx(0.6)
    assert c["S"] == pytest.approx(40, abs=0.01)             # всё продастся до истечения срока
    assert c["D"] > c["mean_demand"] * 0.99
    expected = pur.ceil_to(min(max(0, c["D"] - c["S"] - c["Z"]), c["cap_shelf_life"]), 20)
    assert ln["recommended_qty"] >= expected and ln["recommended_qty"] % 20 == 0
    assert p["delivery_date"] == T + timedelta(days=5)


def test_min_order_sum_topup(session, ready):
    ref = ready
    ref.imp.min_order_sum = 200000
    session.commit()
    p = pur.plan(session, ref.imp.id)
    assert p["total"] >= 200000
    assert any("минимальной суммы" in w for w in p["warnings"])


def test_budget_cut_and_director_approval(client, login, session, ready):
    ref = ready
    appsettings.set_many(session, {"weekly_budget": 100.0})
    session.commit()
    p = pur.plan(session, ref.ru.id)
    assert p["over_budget"] and any("бюджет" in w for w in p["warnings"])
    hb = login("buyer")
    appsettings.set_many(session, {"weekly_budget": 600000.0})
    session.commit()
    o = client.post("/api/purchasing/orders", headers=hb, json={"supplier_id": ref.ru.id}).json()
    assert o["status"] == "draft" and o["number"].startswith(f"ЗП-{T.year}-")
    appsettings.set_many(session, {"weekly_budget": 10.0})
    session.commit()
    r = client.post(f"/api/purchasing/orders/{o['id']}/submit", headers=hb).json()
    assert r["status"] == "approval" and r["over_budget"]
    assert client.post(f"/api/purchasing/orders/{o['id']}/approve", headers=hb).status_code == 403
    r = client.post(f"/api/purchasing/orders/{o['id']}/approve", headers=login("director"), json={"comment": "праздник"})
    assert r.json()["status"] == "approved"


def test_edit_rules_send_and_lifecycle(client, login, session, ready):
    ref = ready
    hb = login("buyer")
    o = client.post("/api/purchasing/orders", headers=hb, json={"supplier_id": ref.ru.id}).json()
    ln = next(x for x in o["lines"] if x["product_id"] == ref.chr.id)
    rec = ln["recommended_qty"]
    # кратность упаковки
    r = client.put(f"/api/purchasing/orders/{o['id']}/lines", headers=hb,
                   json={"items": [{"line_id": ln["id"], "ordered_qty": rec + 3}]})
    assert r.status_code == 400 and "кратно" in r.json()["detail"]
    # изменение больше 30 % без причины (С-10)
    big = pur.ceil_to(rec * 1.6 + 10, 10)
    r = client.put(f"/api/purchasing/orders/{o['id']}/lines", headers=hb,
                   json={"items": [{"line_id": ln["id"], "ordered_qty": big}]})
    assert r.status_code == 400 and "причину" in r.json()["detail"]
    r = client.put(f"/api/purchasing/orders/{o['id']}/lines", headers=hb,
                   json={"items": [{"line_id": ln["id"], "ordered_qty": big, "change_reason": "свадебный заказ"}]})
    assert r.status_code == 200 and r.json()["total"] > o["total"]
    assert client.post(f"/api/purchasing/orders/{o['id']}/send", headers=hb).status_code == 400  # ещё черновик
    assert client.post(f"/api/purchasing/orders/{o['id']}/submit", headers=hb).json()["status"] == "approved"
    r = client.post(f"/api/purchasing/orders/{o['id']}/send", headers=hb).json()
    assert r["status"] == "sent" and "письмо" in r["comment"]
    out = list(get_settings().outbox_dir.glob("*.xlsx"))
    assert len(out) == 1
    for act, st in (("confirm", "confirmed"), ("in_transit", "in_transit")):
        assert client.post(f"/api/purchasing/orders/{o['id']}/{act}", headers=hb).json()["status"] == st
    assert client.post(f"/api/purchasing/orders/{o['id']}/cancel", headers=hb).status_code == 400
    x = client.get(f"/api/purchasing/orders/{o['id']}/xlsx", headers=hb)
    assert x.content[:2] == b"PK"
    # заказ в пути учитывается как Z в следующем расчёте
    p = pur.plan(session, ref.ru.id)
    assert next(x for x in p["lines"] if x["product_id"] == ref.chr.id)["calc"]["Z"] == big


def test_scenario_raises_demand(session, ready):
    ref = ready
    base = pur.plan(session, ref.imp.id)
    rose = next(x for x in base["lines"] if x["product_id"] == ref.rose.id)
    peak = T + timedelta(days=6)
    session.add(HolidayScenario(name="Праздник", event_date=peak, days_before=1, last_delivery_date=T + timedelta(days=5),
                                coefficients={str(ref.roses.id): 5.0}, approved=True))
    session.commit()
    p = pur.plan(session, ref.imp.id)
    rose2 = next(x for x in p["lines"] if x["product_id"] == ref.rose.id)
    assert p["scenario"] == "Праздник" and len(rose2["calc"]["scenario_days"]) == 2
    assert rose2["calc"]["D"] > rose["calc"]["D"] * 1.5


def test_plan_requires_forecast_and_conditions(client, login, session):
    ref = reference(session)
    r = client.post("/api/purchasing/plan", headers=login("buyer"), json={"supplier_id": ref.imp.id})
    assert r.status_code == 400 and "Прогноз" in r.json()["detail"]
    assert client.post("/api/purchasing/plan", headers=login("florist"), json={"supplier_id": ref.imp.id}).status_code == 403


def test_scenario_schedule(client, login, session):
    ref = reference(session)
    s = HolidayScenario(name="8 Марта", event_date=T + timedelta(days=20), last_delivery_date=T + timedelta(days=17),
                        coefficients={}, approved=True)
    session.add(s)
    session.commit()
    r = client.get(f"/api/purchasing/scenarios/{s.id}/schedule", headers=login("buyer")).json()
    imp = next(x for x in r["suppliers"] if x["supplier_id"] == ref.imp.id)
    assert imp["last_order_date"] == str(T + timedelta(days=12))
    assert all(date.fromisoformat(o["delivery_date"]) <= T + timedelta(days=17) for o in imp["orders"])


def test_send_order_through_supplier_api(client, login, session, ready, monkeypatch):
    """Р-4: способ отправки — адаптер у поставщика; заказ уходит JSON-ом в API поставщика."""
    import httpx
    from floraplan.services import supplier_send
    ref = ready
    hb = login("buyer")
    sup = client.get("/api/nsi/suppliers", headers=hb).json()
    body = next(s for s in sup if s["id"] == ref.ru.id)
    body = {k: body[k] for k in ("name", "country", "lead_time_days", "min_order_sum", "email", "order_weekdays",
                                 "reliability", "active")}
    assert {m["code"] for m in client.get("/api/nsi/order-methods", headers=hb).json()} >= {"email", "api"}
    r = client.put(f"/api/nsi/suppliers/{ref.ru.id}", headers=hb, json=dict(body, order_method="api"))
    assert r.status_code == 400                                         # без адреса API
    r = client.put(f"/api/nsi/suppliers/{ref.ru.id}", headers=hb,
                   json=dict(body, order_method="api", order_url="https://supplier.example/orders", order_api_key="s3cr3t"))
    assert r.status_code == 200 and r.json()["has_api_key"] and "order_api_key" not in r.json()
    r = client.put(f"/api/nsi/suppliers/{ref.ru.id}", headers=hb,       # ключ без нового значения не стирается
                   json=dict(body, order_method="api", order_url="https://supplier.example/orders"))
    assert r.json()["has_api_key"]

    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        if len(calls) == 1:
            raise httpx.ConnectError("нет связи")
        return httpx.Response(201, request=httpx.Request("POST", url))
    monkeypatch.setattr(supplier_send.httpx, "post", fake_post)

    o = client.post("/api/purchasing/orders", headers=hb, json={"supplier_id": ref.ru.id}).json()
    assert client.post(f"/api/purchasing/orders/{o['id']}/submit", headers=hb).json()["status"] == "approved"
    r = client.post(f"/api/purchasing/orders/{o['id']}/send", headers=hb)
    assert r.status_code == 502 and "не приняло" in r.json()["detail"]
    assert client.get(f"/api/purchasing/orders/{o['id']}", headers=hb).json()["status"] == "approved"
    r = client.post(f"/api/purchasing/orders/{o['id']}/send", headers=hb).json()
    assert r["status"] == "sent" and "API поставщика" in r["comment"]
    url, payload, headers = calls[-1]
    assert url == "https://supplier.example/orders" and headers == {"Authorization": "Bearer s3cr3t"}
    assert payload["number"] == o["number"] and payload["lines"]
    assert all(x["qty"] > 0 and x["barcode"] for x in payload["lines"])
