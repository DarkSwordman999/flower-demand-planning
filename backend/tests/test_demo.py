from datetime import date, timedelta

import pytest

from floraplan import db
from floraplan.demo import generate
from floraplan.models import (Batch, DailySales, OnlineOrder, Product, PurchaseOrder, Sale, StockMove, User,
                              WriteOff)
from floraplan.services import forecasting as fs
from floraplan.services import purchasing as pur


def test_demo_generates_consistent_data(client, login, session):
    with db.session() as s:      # генерация — одной транзакцией, как в floraplan demo
        res = generate(s, history_days=150, sim_days=21, log=lambda m: None)
    assert res["products"] == session.query(Product).count() == 27
    # остаток каждой партии = сумма движений по ней
    for b in session.query(Batch).limit(300):
        moved = sum(m.qty for m in session.query(StockMove).filter_by(batch_id=b.id))
        assert moved == pytest.approx(b.qty, abs=1e-6), b.id
    assert session.query(WriteOff).count() > 0
    assert session.query(PurchaseOrder).filter_by(status="in_transit").count() == 1
    assert {o.status for o in session.query(OnlineOrder)} == {"reserved", "preorder"}
    daily = sum(r.qty for r in session.query(DailySales))
    sold = sum(ln.qty for s in session.query(Sale) for ln in s.lines)
    assert daily == pytest.approx(sold)
    # после демо новые записи вставляются (последовательности id в порядке)
    r = client.post("/api/sales", headers=login("florist"),
                    json={"location_id": 2, "lines": [{"product_id": 1, "qty": 1}]})
    assert r.status_code == 200, r.text
    run = fs.run(session)
    assert run.status == "ok" and run.series > 100
    sup = session.query(PurchaseOrder).first().supplier_id
    assert pur.plan(session, sup)["lines"]


def test_demo_refuses_non_empty_db(session):
    with db.session() as s:
        generate(s, history_days=40, sim_days=7, log=lambda m: None)
        with pytest.raises(RuntimeError):
            generate(s, history_days=40, sim_days=7, log=lambda m: None)
