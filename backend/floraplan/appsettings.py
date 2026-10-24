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


# допустимые значения: (целое ли, минимум, максимум, название для сообщения)
LIMITS: dict[str, tuple[bool, float, float, str]] = {
    "weekly_budget": (False, 0, 1e12, "Бюджет закупок на неделю"),
    "expiring_days": (True, 0, 14, "«Срок истекает», дней"),
    "markdown_min": (False, 1, 100, "Минимальная уценка, %"),
    "markdown_max": (False, 1, 100, "Максимальная уценка, %"),
    "discrepancy_pct": (False, 0, 100, "Порог акта расхождений, %"),
    "change_reason_pct": (False, 0, 100, "Порог причины изменения заказа, %"),
    "forecast_horizon": (True, 7, 60, "Горизонт прогноза, дней"),
    "forecast_hour": (True, 0, 23, "Час расчёта прогноза"),
    "history_days": (True, 90, 1500, "Глубина истории, дней"),
    "service_level_min": (False, 0.5, 0.99, "Уровень обслуживания: не ниже"),
    "service_level_max": (False, 0.5, 0.995, "Уровень обслуживания: не выше"),
    "salvage_share": (False, 0, 1, "Доля себестоимости при списании"),
    "pd_retention_days": (True, 30, 3650, "Срок обезличивания, дней"),
}


def validate(db: Session, values: dict) -> dict:
    """Проверяет и приводит типы новых значений; ValueError — с текстом для пользователя."""
    out = {}
    for k, v in values.items():
        if k not in DEFAULTS:
            raise ValueError(f"Неизвестный параметр {k}")
        if k == "company_name":
            if not isinstance(v, str) or not v.strip() or len(v) > 200:
                raise ValueError("Название организации: от 1 до 200 символов")
            out[k] = v.strip()
            continue
        integer, lo, hi, name = LIMITS[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name}: нужно число")
        if integer and v != int(v):
            raise ValueError(f"{name}: нужно целое число")
        if not lo <= v <= hi:
            raise ValueError(f"{name}: от {lo:g} до {hi:g}")
        out[k] = int(v) if integer else float(v)
    merged = {**get_all(db), **out}
    if merged["markdown_min"] > merged["markdown_max"]:
        raise ValueError("Минимальная уценка больше максимальной")
    if merged["service_level_min"] > merged["service_level_max"]:
        raise ValueError("Нижняя граница уровня обслуживания больше верхней")
    return out


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
