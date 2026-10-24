"""Тесты бизнес-логики. Запуск: python -m pytest"""
from datetime import date, timedelta

import pytest

import db
import logic

TODAY = date(2026, 3, 1)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "test.db"
    db.create_tables(path)
    c = db.connect(path)
    c.execute("INSERT INTO products (name, price, purchase_price, shelf_life_days, pack_size) "
              "VALUES ('Роза', 100, 40, 7, 10)")
    c.commit()
    yield c
    c.close()


def add_batch(conn, expiry, qty):
    conn.execute("INSERT INTO batches (product_id, received_date, expiry_date, quantity, remaining) "
                 "VALUES (1, ?, ?, ?, ?)", (TODAY.isoformat(), expiry.isoformat(), qty, qty))
    conn.commit()


def test_average():
    assert logic.average([2, 4, 6]) == 4
    assert logic.average([]) == 0


def test_order_quantity_rounds_up_to_pack():
    # нужно 10 × 5 × 1,2 = 60, остаток 25 → 35 → упаковки по 10 → 40
    assert logic.order_quantity(10, 5, 25, 10) == 40


def test_order_quantity_zero_when_enough_stock():
    assert logic.order_quantity(10, 5, 100, 10) == 0


def test_sell_uses_fefo(conn):
    add_batch(conn, TODAY + timedelta(days=5), 10)   # партия 1 — поздний срок
    add_batch(conn, TODAY + timedelta(days=1), 3)    # партия 2 — ранний срок
    logic.sell(conn, 1, 5, TODAY)
    left = {r["id"]: r["remaining"] for r in conn.execute("SELECT id, remaining FROM batches")}
    assert left == {1: 8, 2: 0}                       # сначала вся партия 2, потом 2 шт. из партии 1


def test_sell_ignores_expired_batches(conn):
    add_batch(conn, TODAY - timedelta(days=1), 10)    # просрочена
    with pytest.raises(ValueError):
        logic.sell(conn, 1, 1, TODAY)


def test_daily_sales_fills_missing_days(conn):
    conn.execute("INSERT INTO sales (product_id, sale_date, quantity, price) VALUES (1, ?, 4, 100)",
                 ((TODAY - timedelta(days=1)).isoformat(),))
    conn.commit()
    history = logic.daily_sales(conn, 1, TODAY, days=3)
    assert history == [0, 0, 4]
