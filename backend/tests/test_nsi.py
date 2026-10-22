from factories import reference


def test_product_crud_and_validation(client, login, session):
    ref = reference(session)
    h = login("buyer")
    body = {"name": "Тюльпан Strong Gold", "kind": "Тюльпан", "variety": "Strong Gold", "stem_length": 40,
            "color": "жёлтый", "shelf_life_days": 6, "pack_multiple": 25, "group_id": ref.roses.id,
            "barcode": "4600000000042", "price": 90}
    r = client.post("/api/nsi/products", headers=h, json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["group"] == "Розы"
    assert client.post("/api/nsi/products", headers=h, json={**body, "shelf_life_days": 0}).status_code == 422
    assert client.post("/api/nsi/products", headers=h, json={**body, "group_id": 999}).status_code == 404
    r = client.put(f"/api/nsi/products/{pid}", headers=h, json={**body, "price": 95})
    assert r.json()["price"] == 95
    found = client.get("/api/nsi/products", headers=login("florist"), params={"q": "4600000000042"}).json()
    assert [p["id"] for p in found] == [pid]
    assert client.post("/api/nsi/products", headers=login("florist"), json=body).status_code == 403


def test_supplier_conditions(client, login, session):
    ref = reference(session)
    h = login("buyer")
    r = client.post("/api/nsi/suppliers", headers=h, json={"name": "Ecuador Roses", "country": "Эквадор",
                                                            "lead_time_days": 7, "order_weekdays": "1"})
    assert r.status_code == 200 and r.json()["imported"] is True
    sid = r.json()["id"]
    assert client.post("/api/nsi/suppliers", headers=h, json={"name": "x", "lead_time_days": 1,
                                                               "order_weekdays": "8"}).status_code == 400
    r = client.post("/api/nsi/conditions", headers=h, json={"supplier_id": sid, "product_id": ref.rose.id,
                                                            "price": 70, "pack_multiple": 25})
    assert r.status_code == 200
    # повтор той же пары поставщик — товар
    assert client.post("/api/nsi/conditions", headers=h, json={"supplier_id": sid, "product_id": ref.rose.id,
                                                               "price": 71}).status_code == 409
    conds = client.get("/api/nsi/conditions", headers=h, params={"product_id": ref.rose.id}).json()
    assert {c["supplier"] for c in conds} == {"Holland Flowers B.V.", "Ecuador Roses"}


def test_events_and_scenarios(client, login, session):
    ref = reference(session)
    h = login("analyst")
    r = client.post("/api/nsi/events", headers=h, json={"date": "2027-03-08", "name": "8 Марта", "coefficient": 6})
    assert r.status_code == 200
    hb = login("buyer")
    bad = {"name": "8 Марта", "event_date": "2027-03-08", "last_delivery_date": "2027-03-09",
           "coefficients": {str(ref.roses.id): 5}}
    assert client.post("/api/nsi/scenarios", headers=hb, json=bad).status_code == 400
    ok = {**bad, "last_delivery_date": "2027-03-05"}
    r = client.post("/api/nsi/scenarios", headers=hb, json=ok)
    assert r.status_code == 200 and r.json()["approved"] is False
    sid = r.json()["id"]
    assert client.post(f"/api/nsi/scenarios/{sid}/approve", headers=login("director")).json()["approved"] is True
    # изменение сбрасывает утверждение
    assert client.put(f"/api/nsi/scenarios/{sid}", headers=hb, json=ok).json()["approved"] is False


def test_reference_lists(client, login, session):
    reference(session)
    h = login("florist")
    assert len(client.get("/api/nsi/locations", headers=h).json()) == 3
    assert len(client.get("/api/nsi/writeoff-reasons", headers=h).json()) == 5
    assert client.post("/api/nsi/locations", headers=login("admin"), json={"name": "Салон 2", "type": "bad"}).status_code == 400
