from datetime import date, timedelta

import pytest

from factories import reference
from floraplan.errors import DomainError
from floraplan.models import Batch, StockMove, StockoutDay, User
from floraplan.services import inventory as inv

T = date.today()


def _batches(s, ref):
    u = s.query(User).filter_by(login="storekeeper").one()
    b_late = inv.create_batch(s, ref.rose, ref.salon.id, 30, 60, T - timedelta(days=1), T + timedelta(days=6), u)
    b_early = inv.create_batch(s, ref.rose, ref.salon.id, 20, 58, T - timedelta(days=4), T + timedelta(days=2), u)
    b_wh = inv.create_batch(s, ref.rose, ref.wh.id, 100, 60, T, T + timedelta(days=7), u)
    s.commit()
    return u, b_early, b_late, b_wh


def test_fefo_takes_earliest_expiry_first(session):
    ref = reference(session)
    u, early, late, _ = _batches(session, ref)
    taken, short = inv.consume(session, ref.rose.id, ref.salon.id, 25, T, "sale", "чек 1", u)
    assert short == 0
    assert [(t.batch.id, t.qty) for t in taken] == [(early.id, 20), (late.id, 5)]
    assert early.qty == 0 and late.qty == 25


def test_florist_may_choose_batch(session):
    ref = reference(session)
    u, early, late, _ = _batches(session, ref)
    taken, _ = inv.consume(session, ref.rose.id, ref.salon.id, 10, T, "sale", "", u, batch_id=late.id)
    assert taken[0].batch.id == late.id and early.qty == 20


def test_shortage_and_stockout_day(session):
    ref = reference(session)
    u, *_ = _batches(session, ref)
    taken, short = inv.consume(session, ref.rose.id, ref.salon.id, 60, T, "sale", "", u)
    assert sum(t.qty for t in taken) == 50 and short == 10
    session.commit()
    assert session.query(StockoutDay).filter_by(product_id=ref.rose.id, location_id=ref.salon.id, day=T).count() == 1


def test_batch_states():
    b = Batch(qty=5, reserved=0, discount_pct=0, written_off=False, expiry_date=T + timedelta(days=5))
    assert inv.batch_state(b, T, 2) == "fresh"
    b.expiry_date = T + timedelta(days=2)
    assert inv.batch_state(b, T, 2) == "expiring"
    b.discount_pct = 20
    assert inv.batch_state(b, T, 2) == "marked_down"
    b.expiry_date = T - timedelta(days=1)
    assert inv.batch_state(b, T, 2) == "expired"
    b.qty = 0
    assert inv.batch_state(b, T, 2) == "sold"
    b.written_off = True
    assert inv.batch_state(b, T, 2) == "written_off"


def test_transfer_keeps_expiry_and_cost(session):
    ref = reference(session)
    u, _, _, wh = _batches(session, ref)
    out = inv.transfer(session, ref.rose.id, ref.wh.id, ref.salon.id, 40, u)
    session.commit()
    assert wh.qty == 60
    assert out[0].expiry_date == wh.expiry_date and out[0].cost == wh.cost and out[0].parent_id == wh.id
    with pytest.raises(DomainError):
        inv.transfer(session, ref.rose.id, ref.wh.id, ref.salon.id, 1000, u)


def test_api_stock_writeoff_act_and_count(client, login, session):
    ref = reference(session)
    _, early, late, wh = _batches(session, ref)
    h = login("storekeeper")
    rows = client.get("/api/inventory/batches", headers=h, params={"location_id": ref.salon.id}).json()
    assert [r["id"] for r in rows] == [early.id, late.id]
    assert rows[0]["state"] == "expiring" and rows[1]["state"] == "fresh"
    summary = client.get("/api/inventory/stock", headers=h).json()
    salon = next(r for r in summary if r["location_id"] == ref.salon.id)
    assert salon["qty"] == 50 and salon["nearest_expiry"] == str(early.expiry_date)

    reasons = client.get("/api/nsi/writeoff-reasons", headers=h).json()
    r = client.post("/api/inventory/writeoff", headers=h, json={
        "items": [{"batch_id": early.id, "qty": 5}], "reason_id": reasons[0]["id"], "comment": "помятые бутоны"})
    assert r.status_code == 200, r.text
    act = r.json()["act_number"]
    assert act.startswith(f"АС-{T.year}-")
    assert client.post("/api/inventory/writeoff", headers=h, json={
        "items": [{"batch_id": early.id, "qty": 500}], "reason_id": reasons[0]["id"]}).status_code == 400
    detail = client.get(f"/api/inventory/writeoffs/{act}", headers=h).json()
    assert detail["items"][0]["qty"] == 5 and detail["reason"] == reasons[0]["name"]
    x = client.get(f"/api/inventory/writeoffs/{act}/xlsx", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"

    r = client.post("/api/inventory/count", headers=h, json={"items": [{"batch_id": late.id, "qty": 28}]})
    assert r.json()["differences"][0]["diff"] == -2
    session.expire_all()
    assert session.get(Batch, late.id).qty == 28
    kinds = {m.kind for m in session.query(StockMove).all()}
    assert {"receipt", "writeoff", "inventory"} <= kinds
    assert client.post("/api/inventory/writeoff", headers=login("buyer"), json={
        "items": [{"batch_id": late.id, "qty": 1}], "reason_id": reasons[0]["id"]}).status_code == 403


def test_api_transfer(client, login, session):
    ref = reference(session)
    *_, wh = _batches(session, ref)
    h = login("storekeeper")
    r = client.post("/api/inventory/transfer", headers=h, json={"product_id": ref.rose.id, "from_location_id": ref.wh.id,
                                                                 "to_location_id": ref.online.id, "qty": 15})
    assert r.status_code == 200, r.text
    rows = client.get("/api/inventory/batches", headers=h, params={"location_id": ref.online.id}).json()
    assert rows[0]["qty"] == 15
    r = client.post("/api/inventory/transfer", headers=h, json={"product_id": ref.rose.id, "from_location_id": ref.wh.id,
                                                                 "to_location_id": ref.wh.id, "qty": 1})
    assert r.status_code == 400
