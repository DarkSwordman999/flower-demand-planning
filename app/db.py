"""Работа с базой данных SQLite."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).parent / "schema.sql"


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # строки как словари: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Одно подключение на запрос; закрывается в close_db."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def create_tables(path):
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
