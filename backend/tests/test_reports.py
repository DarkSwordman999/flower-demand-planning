from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import insert

from factories import reference
from floraplan.models import Forecast, ForecastRun, User
from floraplan.services import analytics as an
from floraplan.services import inventory as inv
from floraplan.services.sales import record_sale

T = date.today()
D1 = T - timedelta(days=3)


@pytest.fixture
def data(session):
    ref = reference(session)
    u = session.query(User).filter_by(login="storekeeper").one()
    b = inv.create_batch(session, ref.rose, ref.salon.id, 100, 60, D1, T + timedelta(days=4), u)   # закуплено 6000
    c = inv.create_batch(session, ref.chr, ref.salon.id, 50, 50, D1, T + timedelta(days=9), u)     # закуплено 2500
    record_sale(session, ref.salon.id, [{"product_id": ref.rose.id, "qty": 10, "price": 150}],
                datetime.combine(D1, datetime.min.time()), user=u)
    record_sale(session, ref.salon.id, [{"product_id": ref.rose.id, "qty": 20, "price": 150},
                                        {"product_id": ref.chr.id, "qty": 5, "price": 120, "discount": 50}],
                datetime.combine(D1 + timedelta(days=1), datetime.min.time()), user=u)
    reason = session.query(__import__("floraplan.models", fromlist=["WriteOffReason"]).WriteOffReason).first()
    inv.writeoff(session, [{"batch_id": b.id, "qty": 5}], reason.id, u, day=D1 + timedelta(days=1))
    session.commit()
    return ref


def test_sales_report_margin(session, data):
    r = an.sales(session, D1, T, "product")
    rose = next(x for x in r["rows"] if x["key"] == data.rose.name)
    assert rose["qty"] == 30 and rose["revenue"] == 4500 and rose["cost"] == 1800 and rose["margin_pct"] == 60
    assert r["totals"]["revenue"] == 4500 + 600 - 50
    by_day = an.sales(session, D1, T, "day")
    assert [x["key"] for x in by_day["rows"]] == [str(D1), str(D1 + timedelta(days=1))]


def test_writeoff_share_of_purchases(session, data):
    r = an.writeoffs(session, D1, T, "reason")
    assert r["totals"]["cost"] == 300 and r["totals"]["share_pct"] == round(300 / 8500 * 100, 2)


def test_turnover(session, data):
    r = an.turnover(session, D1, D1 + timedelta(days=1), "product")
    rose = next(x for x in r["rows"] if x["key"] == data.rose.name)
    # конец дня 1: 90, конец дня 2: 65 → средний запас 77,5; продано 30 за 2 дня
    assert rose["avg_stock"] == 77.5 and rose["per_day"] == 15 and rose["turnover_days"] == pytest.approx(5.2, abs=0.1)


def test_accuracy_weekly_wape(session, data):
    run = ForecastRun(base_date=D1, status="ok", model_id=1)
    session.add(run)
    session.flush()
    session.execute(insert(Forecast), [
        {"run_id": run.id, "product_id": data.rose.id, "location_id": data.salon.id, "day": D1 + timedelta(days=i),
         "p50": 12.0, "p80": 14, "p95": 16, "sigma": 0.2, "event_coef": 1, "algorithm": "x"} for i in range(2)])
    session.commit()
    r = an.accuracy(session, D1, D1 + timedelta(days=1), "group")
    roses = next(x for x in r["rows"] if x["key"] == data.roses.name)
    assert roses["actual"] == 30 and roses["forecast"] == 24
    # одна неделя (если оба дня в одной ISO-неделе) — WAPE 20 %
    if D1.isocalendar()[1] == (D1 + timedelta(days=1)).isocalendar()[1]:
        assert roses["wape_pct"] == 20.0 and roses["bias_pct"] == -20.0


def test_abcxyz(session, data):
    r = an.abcxyz(session, D1, T)
    assert r["rows"][0]["key"] == data.rose.name and r["rows"][0]["abc"] == "A"


def test_api_reports_and_xlsx(client, login, session, data):
    h = login("director")
    assert len(client.get("/api/reports", headers=h).json()) == 6
    r = client.get("/api/reports/sales", headers=h, params={"date_from": str(D1), "group_by": "group"}).json()
    assert r["columns"][0]["title"] == "Группа" and r["totals"]["revenue"] > 0
    x = client.get("/api/reports/writeoffs/xlsx", headers=h, params={"date_from": str(D1), "group_by": "reason"})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.get("/api/reports/sales", headers=h, params={"group_by": "нет"}).status_code == 400
    assert client.get("/api/reports/nope", headers=h).status_code == 404
    assert client.get("/api/reports/sales", headers=login("florist")).status_code == 403
    d = client.get("/api/dashboard", headers=login("florist")).json()
    assert d["sales_week"] > 0 and d["writeoff_share_pct"] is not None


def test_every_report_exports_to_xlsx(client, login, data):
    """Все отчёты выгружаются в XLSX — в том числе с «/» в названии (ABC/XYZ-анализ)."""
    h = login("analyst")
    for rep in client.get("/api/reports", headers=h).json():
        x = client.get(f"/api/reports/{rep['code']}/xlsx", headers=h, params={"date_from": str(D1)})
        assert x.status_code == 200 and x.content[:2] == b"PK", rep["code"]
        assert "/" not in x.headers["content-disposition"].split("''", 1)[1]
