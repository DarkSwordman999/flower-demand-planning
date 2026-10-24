from datetime import date, timedelta

from factories import reference
from floraplan.models import Batch, OnlineOrder, Sale, User
from floraplan.services import inventory as inv

T = date.today()
KEY = {"X-API-Key": "shop-demo-key"}


def _stock(s, ref):
    u = s.query(User).filter_by(login="storekeeper").one()
    short_life = inv.create_batch(s, ref.rose, ref.online.id, 10, 60, T - timedelta(days=5), T + timedelta(days=1), u)
    long_life = inv.create_batch(s, ref.rose, ref.online.id, 20, 60, T, T + timedelta(days=7), u)
    s.commit()
    return short_life, long_life


def _order(ext, qty, days=3, **kw):
    return {"id": ext, "delivery_date": str(T + timedelta(days=days)), "customer_name": "Петрова",
            "phone": "+79001234567", "lines": [{"barcode": "4600000000011", "qty": qty}], **kw}


def test_stock_and_prices_require_key(client, session):
    ref = reference(session)
    _stock(session, ref)
    assert client.get("/api/shop/stock").status_code == 401
    st = client.get("/api/shop/stock", headers=KEY).json()
    rose = next(x for x in st["items"] if x["product_id"] == ref.rose.id)
    assert rose["available"] == 30
    pr = client.get("/api/shop/prices", headers=KEY).json()
    assert next(x for x in pr["items"] if x["product_id"] == ref.rose.id)["price"] == 150


def test_order_reserves_batches_fresh_on_delivery(client, session):
    ref = reference(session)
    short, long_ = _stock(session, ref)
    r = client.post("/api/shop/orders", headers=KEY, json=_order("W-1", 15))
    assert r.status_code == 200 and r.json()["status"] == "reserved"
    session.expire_all()
    # партия, истекающая до доставки, не резервируется
    assert session.get(Batch, short.id).reserved == 0 and session.get(Batch, long_.id).reserved == 15
    assert client.get("/api/shop/stock", headers=KEY).json()["items"][0]["available"] == 15
    # повтор номера заказа
    assert client.post("/api/shop/orders", headers=KEY, json=_order("W-1", 15)).json()["created"] is False


def test_shortage_preorder_or_conflict(client, login, session):
    ref = reference(session)
    _stock(session, ref)
    r = client.post("/api/shop/orders", headers=KEY, json=_order("W-2", 50, allow_preorder=False))
    assert r.status_code == 409 and r.json()["shortage"][0]["available"] == 20
    r = client.post("/api/shop/orders", headers=KEY, json=_order("W-3", 50))
    assert r.json()["status"] == "preorder"
    oid = r.json()["order_id"]
    h = login("shop_manager")
    assert client.post(f"/api/online-orders/{oid}/reserve", headers=h).status_code == 409
    u = session.query(User).filter_by(login="storekeeper").one()
    inv.create_batch(session, ref.rose, ref.online.id, 40, 60, T, T + timedelta(days=8), u)
    session.commit()
    assert client.post(f"/api/online-orders/{oid}/reserve", headers=h).json()["status"] == "reserved"


def test_complete_turns_reservation_into_sale(client, login, session):
    ref = reference(session)
    _, long_ = _stock(session, ref)
    oid = client.post("/api/shop/orders", headers=KEY, json=_order("W-4", 12)).json()["order_id"]
    h = login("shop_manager")
    r = client.post(f"/api/online-orders/{oid}/complete", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "completed"
    session.expire_all()
    b = session.get(Batch, long_.id)
    assert b.qty == 8 and b.reserved == 0
    sale = session.query(Sale).one()
    assert sale.channel == "online" and sale.total == 12 * 150
    assert client.get("/api/shop/orders/W-4", headers=KEY).json()["status"] == "completed"


def test_cancel_releases_and_pd_masked(client, login, session):
    ref = reference(session)
    _, long_ = _stock(session, ref)
    oid = client.post("/api/shop/orders", headers=KEY, json=_order("W-5", 5)).json()["order_id"]
    rows = client.get("/api/online-orders", headers=login("director")).json()
    assert rows[0]["phone"] != "+79001234567" and rows[0]["phone"].endswith("67")
    assert client.get("/api/online-orders", headers=login("shop_manager")).json()[0]["phone"] == "+79001234567"
    assert client.post(f"/api/online-orders/{oid}/cancel", headers=login("shop_manager")).json()["status"] == "cancelled"
    session.expire_all()
    assert session.get(Batch, long_.id).reserved == 0
    assert session.get(OnlineOrder, oid).status == "cancelled"



def test_closed_orders_anonymized_after_retention(client, login, session):
    """Б-1, 152-ФЗ: закрытые заказы старше срока хранения обезличиваются, открытые и свежие — нет."""
    from datetime import datetime
    from floraplan import db
    from floraplan.services import shop
    ref = reference(session)
    _stock(session, ref)
    ids = {e: client.post("/api/shop/orders", headers=KEY, json=_order(e, 2, comment="ул. Ленина, 1")).json()["order_id"]
           for e in ("OLD-C", "OLD-OPEN", "NEW-C")}
    for e in ("OLD-C", "NEW-C"):
        client.post(f"/api/online-orders/{ids[e]}/cancel", headers=login("shop_manager"))
    with db.session() as s:
        for e in ("OLD-C", "OLD-OPEN"):
            s.get(OnlineOrder, ids[e]).created_at = datetime.now() - timedelta(days=400)
        s.commit()
        assert shop.anonymize_closed(s) == 1
        s.commit()
        assert shop.anonymize_closed(s) == 0          # повторный запуск ничего не меняет
    session.expire_all()
    old = session.get(OnlineOrder, ids["OLD-C"])
    assert (old.customer_name, old.phone, old.comment) == (shop.ANONYMIZED, "", "")
    assert old.total > 0 and old.lines                 # состав и сумма остаются для отчётов
    for e in ("OLD-OPEN", "NEW-C"):
        assert session.get(OnlineOrder, ids[e]).phone == "+79001234567"


def test_past_delivery_date_rejected(client, session):
    ref = reference(session)
    _stock(session, ref)
    assert client.post("/api/shop/orders", headers=KEY, json=_order("W-6", 1, days=-1)).status_code == 400
