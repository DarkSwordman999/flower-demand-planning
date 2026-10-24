"""Бизнес-логика: продажа по FEFO, прогноз спроса и расчёт заказа."""
import math
from datetime import date, timedelta

FORECAST_DAYS = 14     # прогноз — среднее продаж за последние 14 дней
ORDER_INTERVAL = 3     # заказ делаем раз в 3 дня
SAFETY = 0.2           # страховой запас 20 %
EXPIRING_DAYS = 2      # «срок истекает», если осталось 2 дня или меньше


# ---------- остатки ----------

def stock(db, product_id, today):
    """Сколько товара можно продать: остатки непросроченных партий."""
    row = db.execute(
        "SELECT COALESCE(SUM(remaining), 0) FROM batches "
        "WHERE product_id = ? AND remaining > 0 AND expiry_date >= ?",
        (product_id, today.isoformat()),
    ).fetchone()
    return row[0]


def batch_status(expiry_date, today):
    """Состояние партии по сроку годности."""
    days_left = (date.fromisoformat(expiry_date) - today).days
    if days_left < 0:
        return "просрочена"
    if days_left <= EXPIRING_DAYS:
        return "истекает"
    return "свежая"


# ---------- продажа ----------

def sell(db, product_id, quantity, today):
    """Продажа по правилу FEFO (First Expired — First Out):
    сначала берём товар из партии, у которой раньше кончается срок."""
    if quantity <= 0:
        raise ValueError("Количество должно быть больше нуля")
    available = stock(db, product_id, today)
    if quantity > available:
        raise ValueError(f"Недостаточно товара: в наличии {available} шт.")

    price = db.execute("SELECT price FROM products WHERE id = ?", (product_id,)).fetchone()["price"]
    batches = db.execute(
        "SELECT id, remaining FROM batches "
        "WHERE product_id = ? AND remaining > 0 AND expiry_date >= ? "
        "ORDER BY expiry_date, id",
        (product_id, today.isoformat()),
    ).fetchall()

    left = quantity
    for b in batches:
        if left == 0:
            break
        take = min(left, b["remaining"])
        db.execute("UPDATE batches SET remaining = remaining - ? WHERE id = ?", (take, b["id"]))
        db.execute(
            "INSERT INTO sales (product_id, batch_id, sale_date, quantity, price) VALUES (?, ?, ?, ?, ?)",
            (product_id, b["id"], today.isoformat(), take, price),
        )
        left -= take
    db.commit()


# ---------- прогноз ----------

def daily_sales(db, product_id, today, days=FORECAST_DAYS):
    """Продажи товара по дням за последние `days` дней (сегодня не считаем — день не закончился)."""
    start = today - timedelta(days=days)
    rows = db.execute(
        "SELECT sale_date, SUM(quantity) AS qty FROM sales "
        "WHERE product_id = ? AND sale_date >= ? AND sale_date < ? GROUP BY sale_date",
        (product_id, start.isoformat(), today.isoformat()),
    ).fetchall()
    by_day = {r["sale_date"]: r["qty"] for r in rows}
    return [by_day.get((start + timedelta(days=i)).isoformat(), 0) for i in range(days)]


def average(values):
    """Прогноз методом скользящего среднего: сколько в среднем продаём в день."""
    return sum(values) / len(values) if values else 0


# ---------- заказ ----------

def order_quantity(avg_per_day, cover_days, in_stock, pack_size):
    """Сколько заказать.
    Нужно = средний спрос × число дней до следующей поставки × (1 + страховой запас).
    Заказ = нужно − остаток, округлённое вверх до упаковки."""
    need = avg_per_day * cover_days * (1 + SAFETY)
    qty = need - in_stock
    if qty <= 0:
        return 0
    return math.ceil(qty / pack_size) * pack_size


def order_for_supplier(db, supplier, today):
    """Рекомендуемый заказ по всем товарам поставщика."""
    cover_days = supplier["lead_time_days"] + ORDER_INTERVAL
    products = db.execute(
        "SELECT * FROM products WHERE supplier_id = ? ORDER BY name", (supplier["id"],)
    ).fetchall()
    lines = []
    for p in products:
        avg = average(daily_sales(db, p["id"], today))
        in_stock = stock(db, p["id"], today)
        qty = order_quantity(avg, cover_days, in_stock, p["pack_size"])
        lines.append({
            "product": p["name"],
            "avg": avg,
            "need": avg * cover_days * (1 + SAFETY),
            "stock": in_stock,
            "pack_size": p["pack_size"],
            "qty": qty,
            "sum": qty * p["purchase_price"],
        })
    return cover_days, lines
