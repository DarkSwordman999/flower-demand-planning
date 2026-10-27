"""Крайние случаи расчётов: модели прогноза и квантили (ТЗ 4.8.4), уровень обслуживания и кратность заказа
(С-7, С-9), погодный сервис и климатическая норма (В-1)."""
from datetime import date

import httpx
import numpy as np
import pytest

from floraplan.config import get_settings
from floraplan.models import Weather
from floraplan.services import purchasing, weather
from floraplan.services import tsmodels as tm


# ---------------------------------------------------------------- модели прогноза
def test_seasonal_naive_short_and_empty_series():
    assert list(tm.seasonal_naive(np.array([]), 3)) == [0, 0, 0]
    assert list(tm.seasonal_naive(np.array([2.0, 4.0]), 2)) == [3.0, 3.0]          # короче недели — среднее
    y = np.arange(10, dtype=float)                                                # одна полная неделя
    assert list(tm.seasonal_naive(y, 7)) == list(y[-7:])


def test_seasonal_naive_averages_two_weeks():
    y = np.array([1.0] * 7 + [3.0] * 7)
    assert list(tm.seasonal_naive(y, 7)) == [2.0] * 7


def test_holt_winters_falls_back_on_short_or_constant_series():
    short = np.array([5.0] * 20)
    assert list(tm.holt_winters(short, 3)) == list(tm.seasonal_naive(short, 3))
    const = np.array([4.0] * 60)
    assert list(tm.holt_winters(const, 3)) == [4.0, 4.0, 4.0]


def test_croston_edges():
    assert list(tm.croston(np.zeros(10), 2)) == [0, 0]
    f = tm.croston(np.array([0, 0, 4, 0, 0, 4, 0, 0, 4], dtype=float), 1)[0]
    assert 0 < f < 4 / 3 + 1e-9                     # SBA: чуть меньше «размер / интервал» = 4/3


def test_intermittent_classification_threshold():
    assert tm.is_intermittent(np.array([1, 0, 1, 0, 1, 0], dtype=float))         # ADI = 2
    assert not tm.is_intermittent(np.array([1, 1, 1, 1, 0], dtype=float))        # ADI = 1,25
    assert not tm.is_intermittent(np.zeros(5))


def test_wape_and_bias_without_sales():
    assert tm.wape([0, 0], [1, 1]) is None and tm.bias([0, 0], [1, 1]) is None
    assert tm.wape([10, 10], [8, 12]) == pytest.approx(0.2)
    assert tm.bias([10, 10], [12, 12]) == pytest.approx(0.2)


def test_select_on_short_history_takes_first_candidate():
    algo, test, f = tm.select(np.ones(20), 28, {}, ["seasonal_naive", "holt_winters"])
    assert algo == "seasonal_naive" and len(test) == 0 and len(f) == 0


def test_candidates_include_croston_only_for_intermittent_demand():
    assert "croston" in tm.candidates_for(np.array([0, 0, 1] * 40, dtype=float), "auto")
    assert "croston" not in tm.candidates_for(np.ones(120), "auto")
    assert tm.candidates_for(np.ones(120), "holt_winters") == ["holt_winters"]


def test_quantiles_use_sigma_when_no_errors_and_poisson_floor():
    prof = tm.error_profile(np.array([]), np.array([]))
    assert prof == {"sigma": 0.5, "k80": None, "k95": None}
    p80, p95 = tm.quantiles(np.array([100.0, 0.0]), prof)
    assert p80[0] == pytest.approx(100 * (1 + 0.8416 * 0.5)) and p95[0] >= p80[0]
    assert p80[1] == 0 and p95[1] == 0
    tight = {"sigma": 0.0, "k80": 0.0, "k95": 0.0}                                 # ошибок не было —
    p80, _ = tm.quantiles(np.array([100.0]), tight)                               # остаётся шум √P50
    assert p80[0] == pytest.approx(100 + 0.8416 * 10)


def test_period_quantile_grows_with_service_level_and_is_clipped():
    days = [10.0] * 7
    median = tm.period_quantile(days, 0.3, 0.5)
    assert median == pytest.approx(70)
    assert tm.period_quantile(days, 0.3, 0.8) < tm.period_quantile(days, 0.3, 0.95)
    assert tm.period_quantile(days, 0.3, 0.2) == median                          # ниже 0,5 не опускается
    assert tm.period_quantile(days, 0.3, 1.0) == tm.period_quantile(days, 0.3, 0.995)
    assert tm.period_quantile([], 0.3, 0.9) == 0


# ---------------------------------------------------------------- закупка
@pytest.mark.parametrize("price, cost, salvage, expected", [
    (250, 90, 0.0, 160 / 250),       # Cu = 160, Co = 90
    (100, 100, 0.0, 0.5),            # без наценки — нижняя граница
    (1000, 10, 0.0, 0.95),           # огромная наценка — верхняя граница
    (200, 100, 0.5, 100 / 150),      # половина себестоимости возвращается при списании
])
def test_service_level(price, cost, salvage, expected):
    assert purchasing.service_level(price, cost, salvage, 0.5, 0.95) == pytest.approx(expected)


def test_ceil_to_pack():
    assert purchasing.ceil_to(0, 10) == 0
    assert purchasing.ceil_to(1, 10) == 10
    assert purchasing.ceil_to(20, 10) == 20
    assert purchasing.ceil_to(20.0000000001, 10) == 20     # погрешность float не добавляет упаковку
    assert purchasing.ceil_to(3, 0) == 3                    # кратность 0 считается 1


# ---------------------------------------------------------------- погода
def test_climate_normal_is_continuous_and_matches_mid_month():
    assert weather.normal(date(2026, 7, 15)) == pytest.approx(weather.CLIMATE[6])
    prev = weather.normal(date(2026, 1, 1))
    d = date(2026, 1, 2)
    while d.year == 2026:
        cur = weather.normal(d)
        assert abs(cur - prev) < 0.3            # без скачков на границах месяцев (наибольший шаг ≈ 0,28)
        prev, d = cur, date.fromordinal(d.toordinal() + 1)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_saves_forecast(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "weather_enabled", True)
    data = {"daily": {"time": ["2026-10-27", "2026-10-28", "2026-10-29"],
                      "temperature_2m_mean": [5.5, None, 3.0], "precipitation_sum": [1.2, 0, None]}}
    r = weather.fetch(session, _client(lambda req: httpx.Response(200, json=data)))
    assert r == {"status": "ok", "days": 2}
    w = session.get(Weather, date(2026, 10, 29))
    assert w.temp == 3.0 and w.precip == 0 and w.source == "open-meteo"
    assert session.get(Weather, date(2026, 10, 28)) is None


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(503),
    lambda req: httpx.Response(200, json={"unexpected": True}),
])
def test_fetch_falls_back_to_climate(session, monkeypatch, handler):
    monkeypatch.setattr(get_settings(), "weather_enabled", True)
    r = weather.fetch(session, _client(handler))
    assert r["status"] == "fallback"
    t = weather.temps(session, date(2030, 7, 15), date(2030, 7, 15))
    assert t[date(2030, 7, 15)] == pytest.approx(weather.CLIMATE[6])


def test_fetch_disabled(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "weather_enabled", False)
    assert weather.fetch(session) == {"status": "off"}
