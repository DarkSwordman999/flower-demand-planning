from datetime import date, timedelta

from sqlalchemy import insert

from factories import reference
from floraplan.models import Forecast, ForecastRun, User
from floraplan.services import expiry
from floraplan.services import inventory as inv

T = date.today()


def _setup(session, daily=5.0):
    ref = reference(session)
    u = session.query(User).filter_by(login="storekeeper").one()
    run = ForecastRun(base_date=T, status="ok", model_id=1)
    session.add(run)
    session.flush()
    session.execute(insert(Forecast), [{"run_id": run.id, "product_id": ref.rose.id, "location_id": ref.salon.id,
                                        "day": T + timedelta(days=i), "p50": daily, "p80": daily, "p95": daily,
                                        "sigma": 0.2, "event_coef": 1, "algorithm": "seasonal_naive"} for i in range(14)])
    a = inv.create_batch(session, ref.rose, ref.salon.id, 40, 60, T - timedelta(days=6), T + timedelta(days=1), u)
    b = inv.create_batch(session, ref.rose, ref.salon.id, 6, 60, T - timedelta(days=6), T + timedelta(days=2), u)
    fresh = inv.create_batch(session, ref.rose, ref.salon.id, 50, 60, T, T + timedelta(days=7), u)
    old = inv.create_batch(session, ref.rose, ref.salon.id, 3, 60, T - timedelta(days=9), T - timedelta(days=1), u)
    session.commit()
    return ref, a, b, fresh, old


def test_recommendations_use_forecast_and_fefo(session):
    ref, a, b, fresh, _ = _setup(session)
    recs = {r["id"]: r for r in expiry.recommendations(session)}
    assert set(recs) == {a.id, b.id}                         # свежая и просроченная не попадают
    # партия a: спрос за 2 дня 10 → из 40 не продастся 30 → большая скидка
    assert recs[a.id]["forecast_sales"] == 10 and recs[a.id]["unsold"] == 30
    assert 35 <= recs[a.id]["recommended_discount"] <= 50
    # партия b идёт после a (FEFO): спрос за 3 дня 15, a забирает 40 → b не продаётся
    assert recs[b.id]["forecast_sales"] == 0 and recs[b.id]["recommended_discount"] == 50


def test_no_markdown_when_demand_covers(session):
    ref, a, b, *_ = _setup(session, daily=40.0)
    recs = {r["id"]: r for r in expiry.recommendations(session)}
    assert recs[a.id]["recommended_discount"] == 0 and recs[a.id]["recommendation"] == "продастся без уценки"


def test_apply_markdown_and_price_export(client, login, session):
    ref, a, *_ = _setup(session)
    h = login("florist")
    assert client.post("/api/expiry/markdown", headers=h, json={"items": [{"batch_id": a.id, "discount_pct": 70}]}).status_code == 400
    r = client.post("/api/expiry/markdown", headers=h, json={"items": [{"batch_id": a.id, "discount_pct": 30}]})
    assert r.status_code == 200 and r.json()[0]["price"] == 105.0
    rows = client.get("/api/inventory/batches", headers=h, params={"state": "marked_down"}).json()
    assert [x["id"] for x in rows] == [a.id]
    p = client.get("/api/onec/prices", headers={"X-API-Key": "1c-demo-key"}, params={"only_new": True}).json()
    assert p["markdowns"][0]["batch_id"] == a.id and p["markdowns"][0]["price"] == 105.0
    again = client.get("/api/onec/prices", headers={"X-API-Key": "1c-demo-key"}, params={"only_new": True}).json()
    assert again["markdowns"] == []
    assert client.post("/api/expiry/markdown", headers=login("buyer"),
                       json={"items": [{"batch_id": a.id, "discount_pct": 30}]}).status_code == 403


def test_expired_list(client, login, session):
    *_, old = _setup(session)
    rows = client.get("/api/expiry/expired", headers=login("storekeeper")).json()
    assert [r["id"] for r in rows] == [old.id] and rows[0]["state"] == "expired"
