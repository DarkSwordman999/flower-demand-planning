from datetime import date, timedelta

import numpy as np
import pytest

import history
from factories import reference
from floraplan.models import Forecast, ForecastModel, ForecastRun, StockoutDay
from floraplan.services import forecasting as fs
from floraplan.services import tsmodels as tm

T = date.today()


# ---------------------------------------------------------------- модели временных рядов
def test_seasonal_naive_repeats_week():
    y = np.tile([1, 2, 3, 4, 5, 6, 7], 4).astype(float)
    assert list(tm.seasonal_naive(y, 9)) == [1, 2, 3, 4, 5, 6, 7, 1, 2]


def test_holt_winters_follows_season():
    rng = np.random.default_rng(0)
    y = np.tile([10, 10, 12, 14, 20, 25, 9], 20) + rng.normal(0, 0.5, 140)
    f = tm.holt_winters(y, 7)
    assert np.allclose(f, [10, 10, 12, 14, 20, 25, 9], atol=1.5)


def test_croston_intermittent_rate():
    y = np.array([0, 0, 4, 0, 0, 0, 4, 0, 0, 4, 0, 0, 0, 4] * 10, dtype=float)
    assert tm.is_intermittent(y)
    rate = tm.croston(y, 3)[0]
    assert 1.0 < rate < 1.4         # 4 шт. в среднем раз в 3,5 дня ≈ 1,14 (SBA немного занижает)


def test_metrics_and_quantiles():
    assert tm.wape([10, 10], [8, 12]) == pytest.approx(0.2)
    assert tm.bias([10, 10], [12, 12]) == pytest.approx(0.2)
    assert tm.wape([0, 0], [1, 1]) is None
    p50 = np.array([10.0, 0.0, 50.0])
    p80, p95 = tm.quantiles(p50, {"sigma": 0.3, "k80": 0.2, "k95": 0.5})
    assert np.all(p50 <= p80) and np.all(p80 <= p95)
    assert p95[2] == pytest.approx(75.0)
    assert tm.period_quantile([10] * 7, 0.3, 0.9) > 70


def test_prepare_fills_stockout_days():
    y = np.array([10, 10, 10, 10, 10, 10, 10] * 4 + [2], dtype=float)
    so = np.zeros(len(y), dtype=bool)
    so[-1] = True
    out = fs.prepare(y, so, np.ones(len(y)))
    assert out[-1] == 10


# ---------------------------------------------------------------- расчёт по БД
def test_run_creates_quantiles_and_estimates_holiday(session):
    ref = reference(session)
    base = date(2026, 3, 2)               # прогноз на неделю с 8 Марта
    history.make(session, ref, base - timedelta(days=1))
    r = fs.run(session, base=base)
    assert r.status == "ok", r.message
    rows = session.query(Forecast).filter_by(run_id=r.id, product_id=ref.rose.id).order_by(Forecast.day).all()
    assert len(rows) == 14
    assert all(x.p50 <= x.p80 <= x.p95 for x in rows)
    by_day = {x.day: x for x in rows}
    mar8, mar4 = by_day[date(2026, 3, 8)], by_day[date(2026, 3, 4)]
    # коэффициент 8 Марта оценён по прошлым годам (≈ 6)
    assert 4.0 < mar8.event_coef < 8.0
    assert mar8.p50 > 3 * mar4.p50
    eu = session.query(Forecast).filter_by(run_id=r.id, product_id=ref.euc.id).first()
    assert eu.algorithm in ("croston", "seasonal_naive", "holt_winters")


def test_manual_coefficient_and_stockout(session):
    ref = reference(session)
    base = date(2026, 3, 2)
    history.make(session, ref, base - timedelta(days=1), events=False)
    from floraplan.models import CalendarEvent
    session.add(CalendarEvent(date=date(2026, 3, 8), name="8 Марта", coefficient=2.0))
    session.add(StockoutDay(product_id=ref.rose.id, location_id=ref.salon.id, day=base - timedelta(days=1)))
    session.commit()
    r = fs.run(session, base=base)
    f8 = session.query(Forecast).filter_by(run_id=r.id, product_id=ref.rose.id, day=date(2026, 3, 8)).one()
    assert f8.event_coef == 2.0


def test_evaluate_weekly_wape(session):
    ref = reference(session)
    history.make(session, ref, T - timedelta(days=1), events=False)
    ev = fs.evaluate(session, fs.published_model(session))
    assert ev["wape"] is not None and ev["wape"] < 0.2      # пуассоновский шум на недельном уровне невелик
    assert set(ev["groups"]) == {ref.roses.id, ref.chrys.id, ref.green.id}


def test_failed_run_keeps_previous(session, monkeypatch):
    ref = reference(session)
    history.make(session, ref, T - timedelta(days=1), days=120, events=False)
    ok = fs.run(session, base=T - timedelta(days=1))
    monkeypatch.setattr(fs, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("сбой")))
    bad = fs.run(session, base=T)
    assert bad.status == "failed" and "предыдущий прогноз" in bad.message
    assert fs.current_run(session).id == ok.id


# ---------------------------------------------------------------- API
def test_api_run_series_table_and_status(client, login, session):
    ref = reference(session)
    history.make(session, ref, T - timedelta(days=1), days=200, events=False)
    h = login("analyst")
    assert client.get("/api/forecast/status", headers=h).json()["warning"] == "Прогноз ещё не рассчитан"
    r = client.post("/api/forecast/run", headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/forecast/status", headers=h).json()["warning"] == ""
    s = client.get("/api/forecast/series", headers=login("buyer"), params={"product_id": ref.rose.id}).json()
    fut = [p for p in s["points"] if "p50" in p]
    past = [p for p in s["points"] if p["actual"] is not None]
    assert len(fut) == 14 and len(past) >= 50
    t = client.get("/api/forecast/table", headers=h).json()
    assert t["rows"][0]["product"] == ref.rose.name
    assert client.post("/api/forecast/run", headers=login("florist")).status_code == 403


def test_model_candidate_is_evaluated(client, login, session):
    ref = reference(session)
    history.make(session, ref, T - timedelta(days=1), days=300, events=False)
    m = client.post("/api/forecast/models", headers=login("analyst"),
                    json={"algorithm": "holt_winters", "trend": True, "comment": "с трендом"}).json()
    assert m["status"] == "candidate" and m["version"] == 2 and m["params"]["trend"] is True
    assert m["wape"] is not None and m["details"]["published"]["wape"] is not None


def test_model_publish_only_if_not_worse(client, login, session, monkeypatch):
    """С-17: новая версия публикуется, только если её WAPE на отложенном периоде не хуже действующей."""
    reference(session)
    score = {}
    monkeypatch.setattr(fs, "evaluate", lambda db, m, **k: {"wape": score[m.algorithm], "bias": 0.0,
                                                              "period": [T, T], "groups": {}})
    score.update(auto=0.20, croston=0.25, holt_winters=0.20)
    h = login("analyst")
    bad = client.post("/api/forecast/models", headers=h, json={"algorithm": "croston"}).json()
    r = client.post(f"/api/forecast/models/{bad['id']}/publish", headers=h)
    assert r.status_code == 400 and "хуже действующей" in r.json()["detail"]
    assert session.get(ForecastModel, bad["id"]).status == "rejected"
    same = client.post("/api/forecast/models", headers=h, json={"algorithm": "holt_winters"}).json()
    r = client.post(f"/api/forecast/models/{same['id']}/publish", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "published"
    statuses = {m["version"]: m["status"] for m in client.get("/api/forecast/models", headers=h).json()}
    assert statuses[1] == "archived"
    assert client.post(f"/api/forecast/models/{bad['id']}/publish", headers=h).status_code == 400


def test_weather_without_service(client, login, session):
    reference(session)
    w = client.get("/api/forecast/weather", headers=login("buyer")).json()
    assert len(w) == 14 and all(x["source"] == "climate" for x in w)
