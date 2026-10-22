"""Синтетическая история продаж для тестов прогноза (DailySales напрямую — быстро)."""
from datetime import date, timedelta

import numpy as np
from sqlalchemy import insert

from floraplan.models import CalendarEvent, DailySales

WEEK = [0.8, 0.85, 0.9, 1.0, 1.25, 1.4, 0.8]   # пн … вс


def roses_level(d: date) -> float:
    lvl = 20 * WEEK[d.weekday()]
    if (d.month, d.day) == (3, 8):
        lvl *= 6
    if (d.month, d.day) == (3, 7):
        lvl *= 4
    return lvl


def make(session, ref, end: date, days: int = 800, seed: int = 1, events: bool = True) -> None:
    rng = np.random.default_rng(seed)
    rows = []
    start = end - timedelta(days=days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        q = rng.poisson(roses_level(d))
        rows.append({"product_id": ref.rose.id, "location_id": ref.salon.id, "day": d, "qty": float(q),
                     "revenue": q * 150.0})
        q2 = rng.poisson(8 * WEEK[d.weekday()])
        rows.append({"product_id": ref.chr.id, "location_id": ref.salon.id, "day": d, "qty": float(q2),
                     "revenue": q2 * 120.0})
        if rng.random() < 0.25:   # прерывистый спрос
            q3 = int(rng.integers(1, 6))
            rows.append({"product_id": ref.euc.id, "location_id": ref.salon.id, "day": d, "qty": float(q3),
                         "revenue": q3 * 60.0})
    session.execute(insert(DailySales), rows)
    if events:
        session.add_all([CalendarEvent(date=date(2026, 3, 7), name="Канун 8 Марта"),
                         CalendarEvent(date=date(2026, 3, 8), name="8 Марта")])
    session.commit()
