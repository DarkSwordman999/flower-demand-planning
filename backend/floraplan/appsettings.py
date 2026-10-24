"""Параметры работы системы, которые меняет администратор (хранятся в таблице settings)."""
import json

from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, object] = {
    "company_name": "Цветочная компания",
    "weekly_budget": 600000.0,          # бюджет закупок на неделю, руб. (П-8)
    "expiring_days": 2,                 # С-12: «срок истекает» — не более N дней до «годен до»
    "markdown_min": 10,                 # С-12: уценка 10–50 %
    "markdown_max": 50,
    "discrepancy_pct": 2.0,             # С-2: акт расхождений при отклонении больше 2 %
    "change_reason_pct": 30.0,          # С-10: причина при изменении рекомендации больше чем на 30 %
    "forecast_horizon": 14,             # С-6: горизонт прогноза, дней
    "forecast_hour": 3,                 # С-6: ежедневный расчёт в 03:00
    "history_days": 730,                # глубина истории для прогноза
    "service_level_min": 0.5,           # границы целевого уровня обслуживания (newsvendor)
    "service_level_max": 0.95,
    "salvage_share": 0.0,               # доля себестоимости, возвращаемая при списании
    "pd_retention_days": 365,           # Б-1, 152-ФЗ: через сколько дней обезличивать закрытые онлайн-заказы
}


def get(db: Session, key: str):
    row = db.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row.value)


def get_all(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = json.loads(row.value)
    return out


def set_many(db: Session, values: dict) -> None:
    for k, v in values.items():
        if k not in DEFAULTS:
            raise KeyError(k)
        row = db.get(Setting, k)
        if row is None:
            db.add(Setting(key=k, value=json.dumps(v, ensure_ascii=False)))
        else:
            row.value = json.dumps(v, ensure_ascii=False)
