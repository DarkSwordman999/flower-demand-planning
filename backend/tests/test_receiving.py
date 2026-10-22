from datetime import date, timedelta

import pytest

from factories import reference
from floraplan.models import Batch, PurchaseOrder, PurchaseOrderLine

T = date.today()


def _order(session, sup, lines, status="in_transit"):
    o = PurchaseOrder(number=f"ЗП-T-{sup.id}-{len(lines)}", supplier_id=sup.id, location_id=1, order_date=T,
                      expected_date=T, status=status, total=0)
    session.add(o)
    session.flush()
    for prod, qty, price in lines:
        session.add(PurchaseOrderLine(order_id=o.id, product_id=prod.id, recommended_qty=qty, ordered_qty=qty,
                                      price=price, pack_multiple=1))
    session.commit()
    return o


@pytest.fixture
def ref(session):
    r = reference(session)
    assert r.wh.id == 1
    return r


def test_receive_creates_batches_with_expiry(client, login, session, ref):
    o = _order(session, ref.ru, [(ref.chr, 100, 55), (ref.euc, 50, 20)])
    h = login("storekeeper")
    todo = client.get("/api/receiving/orders", headers=h).json()
    lines = {ln["product_id"]: ln["id"] for ln in todo[0]["lines"]}
    r = client.post(f"/api/receiving/orders/{o.id}", headers=h, json={"items": [
        {"line_id": lines[ref.chr.id], "received_qty": 100, "shelf_reduction_days": 2, "quality": "мелкий бутон"},
        {"line_id": lines[ref.euc.id], "received_qty": 50}]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["act_number"] is None and len(res["batches"]) == 2
    b = session.get(Batch, res["batches"][0])
    assert b.expiry_date == T + timedelta(days=12 - 2) and b.cost == 55 and b.location_id == ref.wh.id   # С-3
    session.expire_all()
    assert session.get(PurchaseOrder, o.id).status == "received"
    html = client.get("/api/receiving/labels", headers=h, params={"batch_ids": res["batches"]})
    assert "Годен до" in html.text and ref.chr.name in html.text


def test_discrepancy_over_2_percent_and_defect(client, login, session, ref):
    o = _order(session, ref.ru, [(ref.chr, 100, 55), (ref.euc, 50, 20)])
    h = login("storekeeper")
    lines = {ln.product_id: ln.id for ln in session.get(PurchaseOrder, o.id).lines}
    r = client.post(f"/api/receiving/orders/{o.id}", headers=h, json={"items": [
        {"line_id": lines[ref.chr.id], "received_qty": 99},                       # 1 % — без акта
        {"line_id": lines[ref.euc.id], "received_qty": 45, "defect_qty": 5}]}).json()   # 10 % недостача + брак
    assert r["act_number"].startswith("АР-")
    reasons = sorted(x["reason"] for x in r["act_lines"])
    assert reasons == ["брак", "недостача"]
    acts = client.get("/api/receiving/acts", headers=h).json()
    assert client.get(f"/api/receiving/acts/{acts[0]['id']}/xlsx", headers=h).content[:2] == b"PK"
    euc_batch = session.query(Batch).filter_by(product_id=ref.euc.id).one()
    assert euc_batch.qty == 40


def test_imported_without_phyto_rejected(client, login, session, ref):
    o = _order(session, ref.imp, [(ref.rose, 200, 60)])
    h = login("storekeeper")
    lid = session.get(PurchaseOrder, o.id).lines[0].id
    r = client.post(f"/api/receiving/orders/{o.id}", headers=h,
                    json={"items": [{"line_id": lid, "received_qty": 200}]}).json()
    assert r["batches"] == [] and "фитосанитарных" in r["act_lines"][0]["reason"]


def test_imported_with_phyto_ok(client, login, session, ref):
    o = _order(session, ref.imp, [(ref.rose, 200, 60)])
    lid = session.get(PurchaseOrder, o.id).lines[0].id
    r = client.post(f"/api/receiving/orders/{o.id}", headers=login("storekeeper"),
                    json={"items": [{"line_id": lid, "received_qty": 200, "phyto_ok": True}]}).json()
    assert len(r["batches"]) == 1 and r["act_number"] is None


def test_only_in_transit_and_validation(client, login, session, ref):
    o = _order(session, ref.ru, [(ref.chr, 10, 55)], status="sent")
    h = login("storekeeper")
    lid = session.get(PurchaseOrder, o.id).lines[0].id
    assert client.post(f"/api/receiving/orders/{o.id}", headers=h,
                       json={"items": [{"line_id": lid, "received_qty": 10}]}).status_code == 400
    o2 = _order(session, ref.ru, [(ref.chr, 10, 55), (ref.euc, 1, 1)])
    lid2 = session.get(PurchaseOrder, o2.id).lines[0].id
    r = client.post(f"/api/receiving/orders/{o2.id}", headers=h,
                    json={"items": [{"line_id": lid2, "received_qty": 10, "shelf_reduction_days": 50}]})
    assert r.status_code == 400
    assert client.post(f"/api/receiving/orders/{o2.id}", headers=login("buyer"),
                       json={"items": []}).status_code == 403
