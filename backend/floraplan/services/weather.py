"""Погодный сервис (В-1): прогноз температуры и осадков на 14 дней из открытого API Open-Meteo.
Если сервис недоступен — климатические средние (ПР 7-8, раздел 4.2.4, поток 2а)."""
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..models import Weather

# средняя месячная температура (Тула), °C — климатическая норма
CLIMATE = [-7.5, -6.8, -1.4, 6.9, 13.5, 16.9, 18.9, 17.1, 11.4, 5.3, -0.8, -5.2]
URL = "https://api.open-meteo.com/v1/forecast"


def _mid(year: int, month: int) -> date:
    """15-е число месяца; month может выходить за 1…12 (соседний год)."""
    year += (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, 15)


def normal(day: date) -> float:
    """Норма на день: линейная интерполяция между серединами месяцев по фактическому числу дней
    (в феврале 28–29, в остальных 30–31), поэтому на границах месяцев нет скачков."""
    mid = _mid(day.year, day.month)
    a, b = (mid, _mid(day.year, day.month + 1)) if day >= mid else (_mid(day.year, day.month - 1), mid)
    t = (day - a).days / (b - a).days
    return CLIMATE[a.month - 1] + (CLIMATE[b.month - 1] - CLIMATE[a.month - 1]) * t


def fetch(db: Session, client: httpx.Client | None = None) -> dict:
    s = get_settings()
    if not s.weather_enabled:
        return {"status": "off"}
    params = {"latitude": s.latitude, "longitude": s.longitude, "daily": "temperature_2m_mean,precipitation_sum",
              "forecast_days": 14, "past_days": 31, "timezone": s.timezone}
    try:
        if client is None:
            with httpx.Client(timeout=15) as c:   # закрывается после запроса
                r = c.get(URL, params=params)
        else:
            r = client.get(URL, params=params)
        r.raise_for_status()
        d = r.json()["daily"]
        n = 0
        for day, t, p in zip(d["time"], d["temperature_2m_mean"], d["precipitation_sum"]):
            if t is None:
                continue
            day = date.fromisoformat(day)
            w = db.get(Weather, day) or Weather(day=day)
            w.temp, w.precip, w.source, w.fetched_at = float(t), float(p or 0), "open-meteo", datetime.now()
            db.merge(w)
            n += 1
        audit.integration(db, "weather", f"получено дней: {n}")
        db.commit()
        return {"status": "ok", "days": n}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        db.rollback()
        audit.integration(db, "weather", f"сервис недоступен, используются климатические средние: {e}", status="warn")
        db.commit()
        return {"status": "fallback", "error": str(e)}


def temps(db: Session, start: date, end: date) -> dict[date, float]:
    """Температура по дням: факт/прогноз из таблицы, иначе норма."""
    have = {w.day: w.temp for w in db.query(Weather).filter(Weather.day >= start, Weather.day <= end)}
    out = {}
    d = start
    while d <= end:
        out[d] = have.get(d, normal(d))
        d += timedelta(days=1)
    return out


def known_days(db: Session, start: date, end: date) -> set[date]:
    return {w.day for w in db.query(Weather.day).filter(Weather.day >= start, Weather.day <= end)}
