-- Структура базы данных ФлораПлан

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    phone          TEXT NOT NULL DEFAULT '',
    lead_time_days INTEGER NOT NULL DEFAULT 2       -- через сколько дней приходит поставка
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    price           REAL NOT NULL,                  -- цена продажи
    purchase_price  REAL NOT NULL,                  -- цена закупки
    shelf_life_days INTEGER NOT NULL,               -- сколько дней цветок можно продавать
    pack_size       INTEGER NOT NULL DEFAULT 1,     -- по сколько штук поставщик продаёт
    supplier_id     INTEGER REFERENCES suppliers(id)
);

-- Партия: товар из одной поставки с одним сроком годности
CREATE TABLE IF NOT EXISTS batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL REFERENCES products(id),
    received_date TEXT NOT NULL,                    -- даты храним строкой 'ГГГГ-ММ-ДД'
    expiry_date   TEXT NOT NULL,
    quantity      INTEGER NOT NULL,                 -- сколько пришло
    remaining     INTEGER NOT NULL                  -- сколько осталось
);

CREATE TABLE IF NOT EXISTS sales (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id   INTEGER REFERENCES batches(id),
    sale_date  TEXT NOT NULL,
    quantity   INTEGER NOT NULL,
    price      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS writeoffs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES batches(id),
    writeoff_date TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    reason        TEXT NOT NULL
);
