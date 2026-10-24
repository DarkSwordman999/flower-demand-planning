"""Заполняет базу демонстрационными данными: поставщики, товары, продажи за 60 дней, остатки.

Запуск: python demo.py  (старая база удаляется). Вход: admin / admin.
"""
import random
from datetime import date, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

import db

DB_PATH = Path(__file__).parent / "floraplan.db"

SUPPLIERS = [
    ("ООО «Голландские цветы»", "+7 (900) 111-22-33", 5),
    ("ООО «Тепличный комбинат»", "+7 (900) 222-33-44", 1),
    ("ИП Смирнов (упаковка)", "+7 (900) 333-44-55", 2),
]

# название, категория, цена, закупка, срок (дней), упаковка, поставщик (номер), продаж в день
PRODUCTS = [
    ("Роза красная 60 см", "Розы", 160, 70, 8, 10, 1, 9),
    ("Роза белая 60 см", "Розы", 170, 75, 8, 10, 1, 5),
    ("Роза кустовая", "Розы", 150, 65, 7, 10, 2, 4),
    ("Тюльпан", "Тюльпаны", 95, 40, 6, 25, 1, 6),
    ("Хризантема кустовая", "Хризантемы", 140, 60, 14, 10, 2, 4),
    ("Гвоздика", "Гвоздики", 75, 30, 14, 25, 2, 3),
    ("Эустома", "Эустома", 210, 95, 10, 10, 1, 3),
    ("Эвкалипт", "Зелень", 160, 70, 14, 5, 2, 2),
    ("Лента атласная", "Упаковка", 120, 50, 365, 1, 3, 2),
    ("Открытка", "Упаковка", 150, 60, 365, 10, 3, 2),
]

WEEKDAY = [0.8, 0.8, 0.9, 1.0, 1.2, 1.4, 0.9]   # в пятницу и субботу покупают больше


def main():
    random.seed(1)
    if DB_PATH.exists():
        DB_PATH.unlink()
    db.create_tables(DB_PATH)
    conn = db.connect(DB_PATH)
    today = date.today()

    conn.execute("INSERT INTO users (login, password_hash) VALUES (?, ?)",
                 ("admin", generate_password_hash("admin")))
    for name, phone, lead in SUPPLIERS:
        conn.execute("INSERT INTO suppliers (name, phone, lead_time_days) VALUES (?, ?, ?)", (name, phone, lead))
    for name, cat, price, cost, shelf, pack, sup, _ in PRODUCTS:
        conn.execute(
            "INSERT INTO products (name, category, price, purchase_price, shelf_life_days, pack_size, supplier_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (name, cat, price, cost, shelf, pack, sup))

    # продажи за 60 дней (история, без привязки к партиям)
    for days_ago in range(60, 0, -1):
        day = today - timedelta(days=days_ago)
        for product_id, p in enumerate(PRODUCTS, start=1):
            mean = p[7] * WEEKDAY[day.weekday()]
            qty = max(0, round(random.gauss(mean, mean * 0.3)))
            if qty:
                conn.execute("INSERT INTO sales (product_id, batch_id, sale_date, quantity, price) "
                             "VALUES (?, NULL, ?, ?, ?)", (product_id, day.isoformat(), qty, p[2]))

    # текущие остатки: у некоторых товаров партии с истекающим и истёкшим сроком
    for product_id, p in enumerate(PRODUCTS, start=1):
        received = today - timedelta(days=random.randint(0, 3))
        qty = p[7] * 3
        conn.execute("INSERT INTO batches (product_id, received_date, expiry_date, quantity, remaining) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (product_id, received.isoformat(), (received + timedelta(days=p[4])).isoformat(), qty, qty))
    for product_id, days_left in [(1, 1), (4, 0), (7, -1)]:
        received = today - timedelta(days=PRODUCTS[product_id - 1][4] - days_left)
        conn.execute("INSERT INTO batches (product_id, received_date, expiry_date, quantity, remaining) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (product_id, received.isoformat(), (today + timedelta(days=days_left)).isoformat(), 20, 8))

    conn.commit()
    conn.close()
    print("Демо-данные загружены. Вход: admin / admin")


if __name__ == "__main__":
    main()
