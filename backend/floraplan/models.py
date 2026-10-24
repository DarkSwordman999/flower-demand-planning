"""Информационная модель системы (ПР 4, рисунок 4.3; ПР 7-8, диаграмма классов)."""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# ---------------------------------------------------------------- справочники значений
ROLES = {
    "admin": "Администратор",
    "director": "Директор",
    "buyer": "Менеджер по закупкам",
    "storekeeper": "Кладовщик",
    "florist": "Продавец-флорист",
    "shop_manager": "Менеджер интернет-магазина",
    "analyst": "Аналитик",
}

LOCATION_TYPES = {"warehouse": "Склад", "salon": "Салон", "online": "Интернет-магазин"}

# С-11: статусы заказа поставщику
ORDER_STATUSES = {
    "draft": "Черновик",
    "approval": "На согласовании",
    "approved": "Утверждён",
    "sent": "Отправлен",
    "confirmed": "Подтверждён",
    "in_transit": "В пути",
    "received": "Принят",
    "closed": "Закрыт",
    "cancelled": "Отменён",
}

# ПР 7-8, таблица 7.10: состояния партии
BATCH_STATES = {
    "fresh": "Свежая",
    "expiring": "Срок истекает",
    "marked_down": "Уценена",
    "expired": "Срок истёк",
    "sold": "Продана",
    "written_off": "Списана",
}

ONLINE_STATUSES = {
    "new": "Новый",
    "preorder": "Предзаказ",
    "reserved": "Зарезервирован",
    "completed": "Выполнен",
    "cancelled": "Отменён",
}

MODEL_STATUSES = {"candidate": "Кандидат", "published": "Опубликована", "archived": "В архиве", "rejected": "Отклонена"}
ALGORITHMS = {
    "auto": "Автовыбор по ряду",
    "seasonal_naive": "Сезонная наивная",
    "holt_winters": "Хольт–Уинтерс",
    "croston": "Метод Кростона",
}


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------- пользователи и журнал
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(200))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_login: Mapped[str] = mapped_column(String(64), default="система")
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(50), default="")
    details: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- НСИ
class ProductGroup(Base):
    __tablename__ = "product_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Product(Base):
    """С-1: карточка товара."""
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(100), default="")          # вид: роза, тюльпан…
    variety: Mapped[str] = mapped_column(String(100), default="")       # сорт
    stem_length: Mapped[int | None] = mapped_column(Integer, nullable=True)  # см
    color: Mapped[str] = mapped_column(String(50), default="")
    unit: Mapped[str] = mapped_column(String(20), default="шт")
    shelf_life_days: Mapped[int] = mapped_column(Integer, default=7)
    pack_multiple: Mapped[int] = mapped_column(Integer, default=1)
    group_id: Mapped[int] = mapped_column(ForeignKey("product_groups.id"))
    barcode: Mapped[str] = mapped_column(String(50), default="", index=True)
    price: Mapped[float] = mapped_column(Float, default=0)              # розничная цена
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    group: Mapped[ProductGroup] = relationship()


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(100), default="Россия")
    lead_time_days: Mapped[int] = mapped_column(Integer, default=2)
    min_order_sum: Mapped[float] = mapped_column(Float, default=0)
    email: Mapped[str] = mapped_column(String(200), default="")
    # способ отправки заказа (Р-4, адаптеры services/supplier_send.py): email — XLSX письмом, api — JSON в API
    order_method: Mapped[str] = mapped_column(String(20), default="email", server_default="email")
    order_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    order_api_key: Mapped[str] = mapped_column(String(200), default="", server_default="")
    order_weekdays: Mapped[str] = mapped_column(String(20), default="0,3")  # дни формирования заказа, 0 — пн
    reliability: Mapped[float] = mapped_column(Float, default=0.95)        # доля поставок в срок
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def imported(self) -> bool:
        return self.country.strip().lower() not in ("россия", "рф", "russia")


class SupplyCondition(Base):
    __tablename__ = "supply_conditions"
    __table_args__ = (UniqueConstraint("supplier_id", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price: Mapped[float] = mapped_column(Float)
    pack_multiple: Mapped[int] = mapped_column(Integer, default=1)
    supplier: Mapped[Supplier] = relationship()
    product: Mapped[Product] = relationship()


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(20), default="salon")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CalendarEvent(Base):
    """Праздник или акция; coefficient — множитель спроса (если не задан, оценивается по истории)."""
    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="holiday")  # holiday | promo
    recurring: Mapped[bool] = mapped_column(Boolean, default=True)     # повторяется ежегодно
    coefficient: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("product_groups.id"), nullable=True)  # акция на группу


class HolidayScenario(Base):
    """С-15: сценарий праздника — коэффициенты спроса по группам и дата последней поставки."""
    __tablename__ = "holiday_scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    event_date: Mapped[date] = mapped_column(Date)
    days_before: Mapped[int] = mapped_column(Integer, default=2)       # пик начинается за N дней
    last_delivery_date: Mapped[date] = mapped_column(Date)
    coefficients: Mapped[dict] = mapped_column(JSON, default=dict)     # {group_id: коэффициент}
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(Text, default="")


class WriteOffReason(Base):
    __tablename__ = "writeoff_reasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)


# ---------------------------------------------------------------- закупки
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))   # куда поставка (склад)
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date] = mapped_column(Date)
    next_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    over_budget: Mapped[bool] = mapped_column(Boolean, default=False)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("holiday_scenarios.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    plan_info: Mapped[dict] = mapped_column(JSON, default=dict)          # параметры расчёта
    supplier: Mapped[Supplier] = relationship()
    location: Mapped[Location] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan",
                                                            order_by="PurchaseOrderLine.id")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    recommended_qty: Mapped[float] = mapped_column(Float, default=0)
    ordered_qty: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    pack_multiple: Mapped[int] = mapped_column(Integer, default=1)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    calc: Mapped[dict] = mapped_column(JSON, default=dict)               # D, S, Z, α — обоснование
    received_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class DiscrepancyAct(Base):
    """С-2: акт расхождений при приёмке."""
    __tablename__ = "discrepancy_acts"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    lines: Mapped[list] = mapped_column(JSON, default=list)   # [{product, ordered, received, diff, reason}]
    order: Mapped[PurchaseOrder] = relationship()


# ---------------------------------------------------------------- запасы
class Batch(Base):
    """Партия: количество товара одной поставки с общим сроком реализации."""
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)  # при перемещении
    received_at: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    qty_initial: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)            # остаток
    reserved: Mapped[float] = mapped_column(Float, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)   # себестоимость единицы
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    quality: Mapped[str] = mapped_column(String(100), default="")
    written_off: Mapped[bool] = mapped_column(Boolean, default=False)
    product: Mapped[Product] = relationship()
    location: Mapped[Location] = relationship()

    @property
    def available(self) -> float:
        return max(0.0, self.qty - self.reserved)


class StockMove(Base):
    """Движение запаса по партии: + приход, − расход (для остатков на дату и оборачиваемости)."""
    __tablename__ = "stock_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))   # receipt sale writeoff transfer_out transfer_in inventory return
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    qty: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ref: Mapped[str] = mapped_column(String(100), default="")


class StockoutDay(Base):
    """День, когда товар закончился в точке: продажи этого дня не отражают спрос (цензурированный спрос)."""
    __tablename__ = "stockout_days"
    __table_args__ = (UniqueConstraint("product_id", "location_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    day: Mapped[date] = mapped_column(Date)


class WriteOff(Base):
    """С-13: списание по партии с причиной; act_number — акт списания."""
    __tablename__ = "writeoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    act_number: Mapped[str] = mapped_column(String(30), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    qty: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float, default=0)
    reason_id: Mapped[int] = mapped_column(ForeignKey("writeoff_reasons.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    batch: Mapped[Batch] = relationship()
    reason: Mapped[WriteOffReason] = relationship()


class Markdown(Base):
    """С-12: уценка партии (история цен для выгрузки в кассы)."""
    __tablename__ = "markdowns"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    discount_pct: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, default=False)
    batch: Mapped[Batch] = relationship()


# ---------------------------------------------------------------- продажи
class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)  # номер чека 1С
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="pos")   # pos | online | manual | history
    total: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[Location] = relationship()
    lines: Mapped[list["SaleLine"]] = relationship(back_populates="sale", cascade="all, delete-orphan")


class SaleLine(Base):
    __tablename__ = "sale_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float, default=0)   # сумма скидки по строке
    cost: Mapped[float] = mapped_column(Float, default=0)
    sale: Mapped[Sale] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class DailySales(Base):
    """Агрегат продаж по дням — источник рядов для прогноза (обновляется при записи продаж)."""
    __tablename__ = "daily_sales"
    __table_args__ = (UniqueConstraint("product_id", "location_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    qty: Mapped[float] = mapped_column(Float, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0)


class SalesChannel(Base):
    """Канал продаж (Р-4): маркетплейс или другой сайт, подключённый через API интернет-магазина
    со своим ключом, местом хранения (остатки и резерв) и коэффициентом цены."""
    __tablename__ = "sales_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)        # префикс номеров заказов канала
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)    # SHA-256 ключа API; сам ключ не хранится
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    price_factor: Mapped[float] = mapped_column(Float, default=1.0)   # цена канала = розничная × коэффициент
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    location: Mapped["Location"] = relationship()


class OnlineOrder(Base):
    __tablename__ = "online_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True)   # у каналов — «код:номер»
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("sales_channels.id"), nullable=True)
    channel: Mapped[SalesChannel | None] = relationship()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")      # персональные данные (152-ФЗ)
    delivery_date: Mapped[date] = mapped_column(Date)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    comment: Mapped[str] = mapped_column(Text, default="")
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"), nullable=True)
    lines: Mapped[list["OnlineOrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OnlineOrderLine(Base):
    __tablename__ = "online_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("online_orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    order: Mapped[OnlineOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("online_order_lines.id", ondelete="CASCADE"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    qty: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------- прогнозирование
class ForecastModel(Base):
    """Версия статистической модели прогнозирования: алгоритм, параметры, WAPE, статус (С-17)."""
    __tablename__ = "forecast_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    algorithm: Mapped[str] = mapped_column(String(30), default="auto")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    wape: Mapped[float | None] = mapped_column(Float, nullable=True)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)        # WAPE по группам, период оценки
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    base_date: Mapped[date] = mapped_column(Date)            # прогноз строится с этой даты
    model_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_models.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")   # running ok failed
    series: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(20), default="manual")   # schedule | manual


class Forecast(Base):
    """Прогноз спроса на дату для пары «товар — место»: P50, P80, P95."""
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("run_id", "product_id", "location_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    p50: Mapped[float] = mapped_column(Float)
    p80: Mapped[float] = mapped_column(Float)
    p95: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float, default=0)     # относительное СКО дневной ошибки ряда
    event_coef: Mapped[float] = mapped_column(Float, default=1)   # применённый календарный коэффициент дня
    algorithm: Mapped[str] = mapped_column(String(30), default="")


class Weather(Base):
    __tablename__ = "weather"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    temp: Mapped[float] = mapped_column(Float)
    precip: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(20), default="open-meteo")   # open-meteo | climate | demo
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class IntegrationLog(Base):
    __tablename__ = "integration_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    system: Mapped[str] = mapped_column(String(30))    # 1c shop weather mail scheduler
    direction: Mapped[str] = mapped_column(String(10), default="in")
    status: Mapped[str] = mapped_column(String(10), default="ok")
    message: Mapped[str] = mapped_column(Text, default="")
