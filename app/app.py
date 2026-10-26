"""ФлораПлан — учёт продаж и планирование закупок цветочного салона.

Запуск: python app.py, затем открыть http://127.0.0.1:5000/
"""
import os
import secrets
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import db
import logic


def secret_key() -> str:
    """Ключ подписи сессии: из переменной SECRET_KEY или из файла secret.key, который создаётся при первом запуске."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = Path(__file__).parent / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="ascii")
    return path.read_text(encoding="ascii").strip()


app = Flask(__name__)
app.config["SECRET_KEY"] = secret_key()
app.config["DATABASE"] = str(Path(__file__).parent / "floraplan.db")
app.teardown_appcontext(db.close_db)


def login_required(view):
    """Пускает на страницу только после входа."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


# ---------- вход ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db.get_db().execute(
            "SELECT * FROM users WHERE login = ?", (request.form["login"],)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session["user"] = user["login"]
            return redirect(url_for("stock"))
        flash("Неверный логин или пароль")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- остатки ----------

@app.route("/")
@login_required
def stock():
    today = date.today()
    batches = db.get_db().execute(
        "SELECT b.*, p.name FROM batches b JOIN products p ON p.id = b.product_id "
        "WHERE b.remaining > 0 ORDER BY b.expiry_date"
    ).fetchall()
    rows = [dict(b, status=logic.batch_status(b["expiry_date"], today)) for b in batches]
    return render_template("stock.html", batches=rows)


@app.route("/writeoff/<int:batch_id>", methods=["POST"])
@login_required
def writeoff(batch_id):
    conn = db.get_db()
    batch = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch and batch["remaining"] > 0:
        conn.execute(
            "INSERT INTO writeoffs (batch_id, writeoff_date, quantity, reason) VALUES (?, ?, ?, ?)",
            (batch_id, date.today().isoformat(), batch["remaining"], request.form["reason"]),
        )
        conn.execute("UPDATE batches SET remaining = 0 WHERE id = ?", (batch_id,))
        conn.commit()
        flash(f"Партия №{batch_id} списана")
    return redirect(url_for("stock"))


# ---------- товары и поставщики ----------

@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    conn = db.get_db()
    if request.method == "POST":
        f = request.form
        conn.execute(
            "INSERT INTO products (name, category, price, purchase_price, shelf_life_days, pack_size, supplier_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f["name"], f["category"], float(f["price"]), float(f["purchase_price"]),
             int(f["shelf_life_days"]), int(f["pack_size"]), int(f["supplier_id"])),
        )
        conn.commit()
        flash("Товар добавлен")
        return redirect(url_for("products"))
    items = conn.execute(
        "SELECT p.*, s.name AS supplier FROM products p LEFT JOIN suppliers s ON s.id = p.supplier_id "
        "ORDER BY p.category, p.name"
    ).fetchall()
    suppliers = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    return render_template("products.html", products=items, suppliers=suppliers)


@app.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    conn = db.get_db()
    if request.method == "POST":
        f = request.form
        conn.execute("INSERT INTO suppliers (name, phone, lead_time_days) VALUES (?, ?, ?)",
                     (f["name"], f["phone"], int(f["lead_time_days"])))
        conn.commit()
        flash("Поставщик добавлен")
        return redirect(url_for("suppliers"))
    items = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    return render_template("suppliers.html", suppliers=items)


# ---------- поставка (приход партии) ----------

@app.route("/receive", methods=["GET", "POST"])
@login_required
def receive():
    conn = db.get_db()
    if request.method == "POST":
        product = conn.execute("SELECT * FROM products WHERE id = ?",
                               (int(request.form["product_id"]),)).fetchone()
        qty = int(request.form["quantity"])
        if qty <= 0:
            flash("Количество должно быть больше нуля")
        else:
            today = date.today()
            expiry = today + timedelta(days=product["shelf_life_days"])
            conn.execute(
                "INSERT INTO batches (product_id, received_date, expiry_date, quantity, remaining) "
                "VALUES (?, ?, ?, ?, ?)",
                (product["id"], today.isoformat(), expiry.isoformat(), qty, qty),
            )
            conn.commit()
            flash(f"Принято: {product['name']}, {qty} шт., годен до {expiry:%d.%m.%Y}")
        return redirect(url_for("receive"))
    items = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("receive.html", products=items)


# ---------- продажи ----------

@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    conn = db.get_db()
    if request.method == "POST":
        try:
            logic.sell(conn, int(request.form["product_id"]), int(request.form["quantity"]), date.today())
            flash("Продажа записана")
        except ValueError as e:
            flash(str(e))
        return redirect(url_for("sales"))
    items = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    last = conn.execute(
        "SELECT s.*, p.name FROM sales s JOIN products p ON p.id = s.product_id "
        "ORDER BY s.id DESC LIMIT 20"
    ).fetchall()
    return render_template("sales.html", products=items, sales=last)


# ---------- прогноз и заказ ----------

@app.route("/forecast")
@login_required
def forecast():
    conn = db.get_db()
    today = date.today()
    rows = []
    for p in conn.execute("SELECT * FROM products ORDER BY category, name").fetchall():
        history = logic.daily_sales(conn, p["id"], today)
        avg = logic.average(history)
        rows.append({"name": p["name"], "history": history, "avg": avg, "week": avg * 7})
    return render_template("forecast.html", rows=rows, days=logic.FORECAST_DAYS)


@app.route("/order")
@login_required
def order():
    conn = db.get_db()
    all_suppliers = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    supplier_id = request.args.get("supplier_id", type=int)
    supplier = next((s for s in all_suppliers if s["id"] == supplier_id), None)
    cover_days, lines = (logic.order_for_supplier(conn, supplier, date.today()) if supplier else (0, []))
    return render_template("order.html", suppliers=all_suppliers, supplier=supplier, cover_days=cover_days,
                           lines=lines, total=sum(x["sum"] for x in lines), logic=logic)


# ---------- отчёт ----------

@app.route("/report")
@login_required
def report():
    conn = db.get_db()
    since = (date.today() - timedelta(days=30)).isoformat()
    sales_by_product = conn.execute(
        "SELECT p.name, SUM(s.quantity) AS qty, SUM(s.quantity * s.price) AS revenue "
        "FROM sales s JOIN products p ON p.id = s.product_id WHERE s.sale_date >= ? "
        "GROUP BY p.id ORDER BY revenue DESC", (since,)
    ).fetchall()
    writeoffs = conn.execute(
        "SELECT p.name, SUM(w.quantity) AS qty, SUM(w.quantity * p.purchase_price) AS loss "
        "FROM writeoffs w JOIN batches b ON b.id = w.batch_id JOIN products p ON p.id = b.product_id "
        "WHERE w.writeoff_date >= ? GROUP BY p.id ORDER BY loss DESC", (since,)
    ).fetchall()
    return render_template("report.html", sales=sales_by_product, writeoffs=writeoffs,
                           revenue=sum(r["revenue"] for r in sales_by_product),
                           loss=sum(r["loss"] for r in writeoffs))


if __name__ == "__main__":
    db.create_tables(app.config["DATABASE"])
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
