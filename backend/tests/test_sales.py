import json
from datetime import date, datetime, timedelta

from factories import reference
from floraplan.config import get_settings
from floraplan.models import Batch, DailySales, Sale, SaleLine, User
from floraplan.services import inventory as inv

T = date.today()
KEY = {"X-API-Key": "1c-demo-key"}


def _stock(s, ref):
    u = s.query(User).filter_by(login="storekeeper").one()
    a = inv.create_batch(s, ref.rose, ref.salon.id, 20, 60, T - timedelta(days=3), T + timedelta(days=3), u)
    b = inv.create_batch(s, ref.rose, ref.salon.id, 30, 62, T, T + timedelta(days=7), u)
    s.commit()
    return a, b


def test_receipts_fefo_and_idempotent(client, session):
    ref = reference(session)
    a, b = _stock(session, ref)
    body = {"receipts": [{"id": "000001", "datetime": f"{T}T10:15:00", "store": "Салон «Центр»",
                          "lines": [{"barcode": ref.rose.barcode, "qty": 25, "price": 150, "discount": 50}]}]}
    r = client.post("/api/onec/receipts", headers=KEY, json=body)
    assert r.json() == {"created": 1, "skipped": 0, "errors": []}
    # повторная загрузка того же чека (С-5)
    assert client.post("/api/onec/receipts", headers=KEY, json=body).json()["skipped"] == 1
    session.expire_all()
    assert session.get(Batch, a.id).qty == 0 and session.get(Batch, b.id).qty == 25
    lines = session.query(SaleLine).all()
    assert sorted((ln.batch_id, ln.qty) for ln in lines) == [(a.id, 20), (b.id, 5)]
    sale = session.query(Sale).one()
    assert sale.total == 25 * 150 - 50
    d = session.query(DailySales).one()
    assert d.qty == 25 and d.revenue == 25 * 150 - 50


def test_receipts_wrong_key_and_bad_lines(client, session):
    ref = reference(session)
    _stock(session, ref)
    assert client.post("/api/onec/receipts", json={"receipts": []}).status_code == 401
    body = {"receipts": [
        {"id": "1", "store": "Нет такой", "lines": [{"barcode": ref.rose.barcode, "qty": 1}]},
        {"id": "2", "store": ref.salon.id, "lines": [{"barcode": "000", "qty": 1}]},
        {"id": "3", "store": ref.salon.id, "lines": [{"barcode": ref.rose.barcode, "qty": 2}]},
    ]}
    r = client.post("/api/onec/receipts", headers=KEY, json=body).json()
    assert r["created"] == 1 and len(r["errors"]) == 2


def test_return_puts_stock_back(client, session):
    ref = reference(session)
    a, b = _stock(session, ref)
    body = {"receipts": [{"id": "R1", "store": ref.salon.id,
                          "lines": [{"barcode": ref.rose.barcode, "qty": -2, "price": 150}]}]}
    assert client.post("/api/onec/receipts", headers=KEY, json=body).json()["created"] == 1
    session.expire_all()
    assert session.get(Batch, b.id).qty == 32


def test_csv_import_and_journal(client, login, session):
    ref = reference(session)
    _stock(session, ref)
    csv_text = ("чек;дата;точка;штрихкод;количество;цена;скидка\n"
                f"A1;{T.strftime('%d.%m.%Y')} 11:00;Салон «Центр»;{ref.rose.barcode};3;150;0\n"
                f"A1;{T.strftime('%d.%m.%Y')} 11:00;Салон «Центр»;{ref.rose.barcode};1;140,50;0\n"
                f"A2;{T.strftime('%d.%m.%Y')} 12:00;Салон «Центр»;{ref.rose.barcode};2;150;10\n")
    h = login("analyst")
    r = client.post("/api/sales/import", headers=h, files={"file": ("cheki.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2
    rows = client.get("/api/sales", headers=h).json()
    assert len(rows) == 2
    one = client.get(f"/api/sales/{rows[-1]['id']}", headers=h).json()
    assert sum(ln["qty"] for ln in one["lines"]) == 4


def test_manual_sale_uses_markdown_price(client, login, session):
    ref = reference(session)
    a, _ = _stock(session, ref)
    a.discount_pct = 30
    session.commit()
    r = client.post("/api/sales", headers=login("florist"), json={"location_id": ref.salon.id,
                                                                  "lines": [{"product_id": ref.rose.id, "qty": 2}]})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2 * 105.0
    assert client.post("/api/sales", headers=login("buyer"), json={"location_id": ref.salon.id,
                                                                   "lines": [{"product_id": ref.rose.id, "qty": 1}]}).status_code == 403


def test_inbox_folder_and_prices(client, login, session):
    ref = reference(session)
    a, _ = _stock(session, ref)
    inbox = get_settings().inbox_1c_dir
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "day1.json").write_text(json.dumps({"receipts": [
        {"id": "F1", "store": ref.salon.id, "lines": [{"barcode": ref.rose.barcode, "qty": 1}]}]}), encoding="utf-8")
    (inbox / "broken.json").write_text("{не json", encoding="utf-8")
    r = client.post("/api/onec/import-folder", headers=login("analyst")).json()
    assert r["created"] == 1 and r["files"] == 1 and len(r["errors"]) == 1
    assert (inbox / "processed" / "day1.json").exists()
    p = client.get("/api/onec/prices", headers=KEY).json()
    assert any(x["barcode"] == ref.rose.barcode for x in p["prices"])
