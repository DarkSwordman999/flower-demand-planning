"""Демонстрационные данные: справочники, пользователи всех ролей, история продаж за два года
и последние 8 недель полного товародвижения (поставки, партии, продажи по FEFO, списания).

Все организации и люди вымышлены. Запуск: floraplan demo (только в пустую БД или с --reset)."""
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from . import appsettings
from .bootstrap import ensure_base
from .models import (Base, Batch, CalendarEvent, DailySales, DiscrepancyAct, ForecastModel, HolidayScenario, Location,
                     OnlineOrder, Product, ProductGroup, PurchaseOrder, PurchaseOrderLine, Sale, SaleLine, StockMove,
                     StockoutDay, Supplier, SupplyCondition, User, Weather, WriteOff, WriteOffReason)
from .security import hash_password
from .services import weather as wx

DEMO_PASSWORD = "demo"
SIM_DAYS = 56
HISTORY_DAYS = 730

USERS = [("director", "Соколова Ирина Павловна", "director"), ("buyer", "Морозов Андрей Игоревич", "buyer"),
         ("storekeeper", "Белов Сергей Николаевич", "storekeeper"), ("florist", "Ковалёва Анна Сергеевна", "florist"),
         ("shop", "Лебедева Мария Олеговна", "shop_manager"), ("analyst", "Новиков Павел Андреевич", "analyst")]

LOCATIONS = [("Склад", "warehouse", 0), ("Салон «Центральный»", "salon", 1.3), ("Салон «Заречье»", "salon", 0.9),
             ("Салон «Пролетарский»", "salon", 0.8), ("Салон «Привокзальный»", "salon", 1.0),
             ("Интернет-магазин", "online", 0.7)]

# группа: (праздничные множители {(месяц, день): k}, чувствительность к температуре)
GROUPS = {
    "Розы": ({(2, 13): 2.5, (2, 14): 6, (3, 6): 2, (3, 7): 4, (3, 8): 5, (8, 31): 1.6, (9, 1): 2.2, (6, 25): 1.8,
              (12, 30): 1.4, (12, 31): 1.8}, 0.010),
    "Хризантемы": ({(3, 7): 2.5, (3, 8): 3, (8, 31): 2.5, (9, 1): 3.5, (12, 31): 1.5}, 0.0),
    "Тюльпаны": ({(3, 6): 3, (3, 7): 7, (3, 8): 9, (2, 14): 2}, 0.020),
    "Гвоздики": ({(3, 8): 2, (5, 8): 3, (5, 9): 5, (2, 23): 2}, 0.0),
    "Эустома и альстромерия": ({(3, 7): 3, (3, 8): 3.5, (2, 14): 2, (6, 25): 2.5, (9, 1): 2}, 0.015),
    "Зелень": ({(3, 7): 2.5, (3, 8): 3, (2, 14): 2.5, (9, 1): 2}, 0.0),
    "Горшечные растения": ({(3, 8): 1.8, (12, 30): 1.5, (12, 31): 1.6}, -0.010),
    "Сопутствующие товары": ({(2, 14): 3, (3, 7): 3, (3, 8): 3, (12, 31): 2}, 0.0),
}

# товар: группа, вид, сорт, длина, цвет, срок, кратность, цена, продаж в день на салон, сезонность (весна, лето, осень, зима)
PRODUCTS = [
    ("Роза Freedom 60 см", "Розы", "Роза", "Freedom", 60, "красный", 8, 10, 160, 9, (1.0, 0.8, 0.9, 1.1)),
    ("Роза Freedom 80 см", "Розы", "Роза", "Freedom", 80, "красный", 8, 10, 230, 4, (1.0, 0.8, 0.9, 1.1)),
    ("Роза Avalanche 60 см", "Розы", "Роза", "Avalanche", 60, "белый", 8, 10, 170, 5, (1.0, 1.1, 0.9, 1.0)),
    ("Роза Pink Floyd 60 см", "Розы", "Роза", "Pink Floyd", 60, "розовый", 8, 10, 180, 4, (1.1, 1.0, 0.9, 0.9)),
    ("Роза кустовая Lydia", "Розы", "Роза кустовая", "Lydia", 50, "розовый", 7, 10, 150, 5, (1.1, 1.1, 0.9, 0.8)),
    ("Роза местная 50 см", "Розы", "Роза", "Тульская", 50, "красный", 6, 10, 110, 5, (0.9, 1.3, 1.0, 0.7)),
    ("Хризантема кустовая Baltica", "Хризантемы", "Хризантема", "Baltica", 70, "белый", 14, 10, 140, 5, (0.8, 0.8, 1.4, 1.0)),
    ("Хризантема одноголовая Антонов", "Хризантемы", "Хризантема", "Антонов", 70, "белый", 14, 10, 190, 2, (0.8, 0.8, 1.4, 1.0)),
    ("Хризантема Сантини", "Хризантемы", "Хризантема", "Santini", 50, "жёлтый", 12, 10, 120, 3, (0.9, 0.9, 1.3, 0.9)),
    ("Тюльпан Strong Gold", "Тюльпаны", "Тюльпан", "Strong Gold", 40, "жёлтый", 6, 25, 95, 4, (2.8, 0.1, 0.1, 1.0)),
    ("Тюльпан Ile de France", "Тюльпаны", "Тюльпан", "Ile de France", 40, "красный", 6, 25, 95, 4, (2.8, 0.1, 0.1, 1.0)),
    ("Тюльпан пионовидный", "Тюльпаны", "Тюльпан", "Angelique", 40, "розовый", 5, 25, 140, 2, (2.8, 0.1, 0.1, 1.0)),
    ("Гвоздика Spray", "Гвоздики", "Гвоздика", "Spray", 60, "красный", 14, 25, 75, 3, (1.1, 1.0, 1.0, 0.9)),
    ("Гвоздика одноголовая", "Гвоздики", "Гвоздика", "Standard", 60, "красный", 14, 25, 70, 2, (1.2, 0.9, 1.0, 0.9)),
    ("Эустома белая", "Эустома и альстромерия", "Эустома", "Rosita", 60, "белый", 10, 10, 210, 3, (1.0, 1.3, 1.0, 0.7)),
    ("Эустома сиреневая", "Эустома и альстромерия", "Эустома", "Rosita", 60, "сиреневый", 10, 10, 210, 2, (1.0, 1.3, 1.0, 0.7)),
    ("Альстромерия", "Эустома и альстромерия", "Альстромерия", "Virginia", 60, "белый", 12, 10, 130, 3, (1.0, 1.1, 1.0, 0.9)),
    ("Гипсофила", "Зелень", "Гипсофила", "Million Star", 70, "белый", 12, 5, 180, 2, (1.0, 1.2, 1.0, 0.9)),
    ("Эвкалипт Цинерея", "Зелень", "Эвкалипт", "Cinerea", 60, "зелёный", 14, 5, 160, 3, (1.0, 1.0, 1.0, 1.1)),
    ("Писташ", "Зелень", "Фисташка", "Pistache", 50, "зелёный", 14, 10, 90, 2, (1.0, 1.0, 1.0, 1.0)),
    ("Рускус", "Зелень", "Рускус", "Italian", 60, "зелёный", 21, 10, 70, 2, (1.0, 1.0, 1.0, 1.0)),
    ("Орхидея фаленопсис", "Горшечные растения", "Орхидея", "Phalaenopsis", None, "микс", 60, 1, 1650, 0.6, (1.0, 0.9, 1.0, 1.2)),
    ("Антуриум в горшке", "Горшечные растения", "Антуриум", "Andreanum", None, "красный", 60, 1, 1450, 0.3, (1.0, 0.9, 1.0, 1.1)),
    ("Кашпо керамическое", "Сопутствующие товары", "Кашпо", "", None, "белый", 365, 1, 650, 0.5, (1.0, 1.0, 1.0, 1.0)),
    ("Лента атласная", "Сопутствующие товары", "Лента", "", None, "", 365, 1, 120, 1.5, (1.0, 1.0, 1.0, 1.0)),
    ("Открытка", "Сопутствующие товары", "Открытка", "", None, "", 365, 10, 150, 1.5, (1.0, 1.0, 1.0, 1.0)),
    ("Подкормка для срезанных цветов", "Сопутствующие товары", "Подкормка", "", None, "", 365, 10, 60, 1.2, (1.0, 1.0, 1.0, 1.0)),
]

# поставщик: страна, срок, мин. сумма, дни заказа, товары → закупочная доля от розничной цены и кратность
SUPPLIERS = [
    ("Holland Flowers B.V.", "Нидерланды", 5, 60000, "0,3", "orders@holland-flowers.example",
     ["Тюльпан", "Хризантема одноголовая", "Хризантема Сантини", "Эустома", "Альстромерия", "Гипсофила", "Орхидея",
      "Антуриум", "Роза кустовая"], 0.42),
    ("Ecuador Premium Roses", "Эквадор", 7, 80000, "1", "sales@ecuador-roses.example",
     ["Роза Freedom", "Роза Avalanche", "Роза Pink Floyd"], 0.40),
    ("Kenya Highland Flowers", "Кения", 6, 50000, "3", "export@kenya-highland.example",
     ["Гвоздика", "Роза кустовая"], 0.38),
    ("ООО «Тепличный комбинат „Подмосковье“»", "Россия", 1, 15000, "0,2,4", "zakaz@teplica-pm.example",
     ["Роза местная", "Хризантема кустовая", "Тюльпан", "Эвкалипт", "Писташ", "Рускус"], 0.48),
    ("ООО «Агрофирма „Тульские цветы“»", "Россия", 1, 10000, "1,3,5", "opt@tula-cvety.example",
     ["Хризантема кустовая", "Хризантема Сантини", "Гвоздика", "Альстромерия"], 0.50),
    ("ООО «Упаковка и декор»", "Россия", 2, 5000, "2", "b2b@upakovka.example",
     ["Кашпо", "Лента", "Открытка", "Подкормка"], 0.45),
]

EVENTS = [((2, 13), "Канун Дня святого Валентина"), ((2, 14), "День святого Валентина"),
          ((2, 23), "День защитника Отечества"), ((3, 6), "8 Марта: предпраздничный день"),
          ((3, 7), "8 Марта: канун"), ((3, 8), "Международный женский день"), ((5, 8), "Канун Дня Победы"),
          ((5, 9), "День Победы"), ((6, 25), "Выпускные вечера"), ((8, 31), "Канун 1 Сентября"),
          ((9, 1), "День знаний"), ((12, 30), "Канун Нового года"), ((12, 31), "Новый год")]


def ean13(n: int) -> str:
    body = f"46012345{n:04d}"
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - s % 10) % 10)


def _season(d: date, prof: tuple) -> float:
    """Плавная сезонность: значения профиля в серединах сезонов (апрель, июль, октябрь, январь)."""
    anchors = [(105, prof[0]), (196, prof[1]), (288, prof[2]), (15, prof[3])]
    doy = d.timetuple().tm_yday
    vals = sorted(anchors)
    for i in range(len(vals)):
        a, b = vals[i], vals[(i + 1) % len(vals)]
        span = (b[0] - a[0]) % 365
        off = (doy - a[0]) % 365
        if off <= span:
            t = off / span if span else 0
            return a[1] + (b[1] - a[1]) * (0.5 - 0.5 * math.cos(math.pi * t))
    return 1.0


WEEK = [0.85, 0.85, 0.9, 0.95, 1.2, 1.35, 0.9]


def _rate(prod: tuple, group: str, loc_k: float, d: date, temp_anom: float, start: date) -> float:
    holidays, beta = GROUPS[group]
    lvl = prod[9] * loc_k * WEEK[d.weekday()] * _season(d, prod[10])
    lvl *= holidays.get((d.month, d.day), 1.0)
    lvl *= math.exp(beta * temp_anom)
    lvl *= 1 + 0.06 * (d - start).days / 365           # рост бизнеса ~6 % в год
    return lvl


def reset(db: Session) -> None:
    """Очистка всех таблиц (кроме служебной таблицы миграций)."""
    for t in reversed(Base.metadata.sorted_tables):
        db.execute(t.delete())
    db.commit()


def generate(db: Session, today: date | None = None, seed: int = 2026, log=print, history_days: int = HISTORY_DAYS,
             sim_days: int = SIM_DAYS) -> dict:
    today = today or date.today()
    rng = np.random.default_rng(seed)
    random.seed(seed)
    if db.query(Product).count() > 0:
        raise RuntimeError("В БД уже есть данные — демо загружается только в пустую БД (floraplan demo --reset)")
    ensure_base(db)
    appsettings.set_many(db, {"company_name": "Цветочная компания «Флора» (демо)", "weekly_budget": 900000.0})

    # ------------------------------------------------ справочники
    groups = {}
    for name in GROUPS:
        groups[name] = ProductGroup(name=name)
        db.add(groups[name])
    locs = []
    for name, typ, _ in LOCATIONS:
        x = Location(name=name, type=typ)
        db.add(x)
        locs.append(x)
    db.flush()
    loc_k = {x.id: LOCATIONS[i][2] for i, x in enumerate(locs)}
    sale_locs = [x for x in locs if x.type != "warehouse"]
    wh = locs[0]
    prods = []
    for i, p in enumerate(PRODUCTS):
        prods.append(Product(name=p[0], group_id=groups[p[1]].id, kind=p[2], variety=p[3], stem_length=p[4], color=p[5],
                             shelf_life_days=p[6], pack_multiple=p[7], price=p[8], barcode=ean13(i + 1),
                             unit="шт"))
    db.add_all(prods)
    db.flush()
    spec = {pr.id: PRODUCTS[i] for i, pr in enumerate(prods)}
    sups, cond = [], {}
    for name, country, lead, mn, days, email, keys, share in SUPPLIERS:
        s = Supplier(name=name, country=country, lead_time_days=lead, min_order_sum=mn, order_weekdays=days,
                     email=email, reliability=0.93 if country != "Россия" else 0.97)
        db.add(s)
        db.flush()
        sups.append(s)
        for pr in prods:
            if any(pr.name.startswith(k) for k in keys) and pr.id not in cond:
                pack = pr.pack_multiple * (2 if country != "Россия" and pr.pack_multiple >= 10 else 1)
                c = SupplyCondition(supplier_id=s.id, product_id=pr.id, price=round(pr.price * share, 2),
                                    pack_multiple=pack)
                db.add(c)
                cond[pr.id] = (s, c)
    db.flush()
    for (m, d), name in EVENTS:
        db.add(CalendarEvent(date=date(today.year, m, d), name=name, type="holiday", recurring=True))
    db.add(CalendarEvent(date=today + timedelta(days=9), name="Акция «Неделя хризантем»", type="promo",
                         recurring=False, coefficient=1.5, group_id=groups["Хризантемы"].id))
    users = []
    for login, full, role in USERS:   # уже заведённых пользователей не трогаем
        x = db.query(User).filter(User.login == login).first()
        if x is None:
            x = User(login=login, full_name=full, role=role, password_hash=hash_password(DEMO_PASSWORD),
                     location_id=locs[1].id if role == "florist" else None)
            db.add(x)
        users.append(x)
    db.flush()
    u = {x.role: x for x in users}
    log("справочники и пользователи — готово")

    # ------------------------------------------------ погода (история — синтетическая, вокруг нормы)
    start = today - timedelta(days=history_days)
    anom, w_rows = {}, []
    a = 0.0
    for i in range(history_days + 14):
        d = start + timedelta(days=i)
        a = 0.75 * a + rng.normal(0, 2.0)
        anom[d] = a
        w_rows.append({"day": d, "temp": round(wx.normal(d) + a, 1), "precip": float(max(0, rng.normal(1.2, 2.5))),
                       "source": "demo", "fetched_at": datetime.now()})
    db.execute(insert(Weather), w_rows)

    # ------------------------------------------------ история продаж (до окна полного товародвижения)
    sim_start = today - timedelta(days=sim_days)
    sale_id = 0
    line_rows, sale_rows, daily = [], [], defaultdict(lambda: [0.0, 0.0])
    for i in range((sim_start - start).days):
        d = start + timedelta(days=i)
        for loc in sale_locs:
            lines = []
            for pr in prods:
                q = int(rng.poisson(_rate(spec[pr.id], spec[pr.id][1], loc_k[loc.id], d, anom[d], start)))
                if q > 0:
                    cost = cond[pr.id][1].price
                    lines.append({"product_id": pr.id, "batch_id": None, "qty": float(q), "price": pr.price,
                                  "discount": 0.0, "cost": cost})
                    daily[(pr.id, loc.id, d)][0] += q
                    daily[(pr.id, loc.id, d)][1] += q * pr.price
            if lines:
                sale_id += 1
                sale_rows.append({"id": sale_id, "external_id": None, "location_id": loc.id, "day": d,
                                  "ts": datetime.combine(d, datetime.min.time()) + timedelta(hours=20),
                                  "channel": "history", "total": sum(x["qty"] * x["price"] for x in lines)})
                for x in lines:
                    line_rows.append(dict(x, sale_id=sale_id))
    log(f"история продаж: {len(line_rows)} строк за {(sim_start - start).days} дн.")

    # ------------------------------------------------ последние 8 недель: поставки, партии, продажи, списания
    batches: list[dict] = []      # в памяти: id, product, location, expiry, qty, cost, received, parent, line
    moves, writeoffs, stockouts = [], [], set()
    orders, order_lines = [], []
    bid = 0
    expired_reason = db.query(WriteOffReason).filter_by(name="Истёк срок реализации").one().id
    look_reason = db.query(WriteOffReason).filter_by(name="Потеря товарного вида").one().id
    wo_n = 0
    order_n = 0

    def new_batch(pid, lid, qty, cost, received, expiry, parent=None, line=None, kind="receipt", ref=""):
        nonlocal bid
        bid += 1
        b = {"id": bid, "product_id": pid, "location_id": lid, "qty": float(qty), "qty_initial": float(qty),
             "cost": cost, "received_at": received, "expiry_date": expiry, "parent_id": parent, "order_line_id": line,
             "written_off": False}
        batches.append(b)
        moves.append({"kind": kind, "batch_id": bid, "product_id": pid, "location_id": lid, "qty": float(qty),
                      "cost": cost, "day": received, "ts": datetime.combine(received, datetime.min.time()) +
                      timedelta(hours=8), "ref": ref, "user_id": u["storekeeper"].id})
        return b

    def mean_rate(pr, d):
        return sum(_rate(spec[pr.id], spec[pr.id][1], loc_k[x.id], d, 0, start) for x in sale_locs)

    # стартовые остатки — по 3 дня спроса в каждой точке
    for pr in prods:
        s, c = cond[pr.id]
        for loc in sale_locs:
            r = _rate(spec[pr.id], spec[pr.id][1], loc_k[loc.id], sim_start, 0, start)
            q = math.ceil(r * 3)
            if q > 0:
                new_batch(pr.id, loc.id, q, c.price, sim_start - timedelta(days=1),
                          sim_start - timedelta(days=1) + timedelta(days=pr.shelf_life_days), ref="начальный остаток")
    by_pl = defaultdict(list)
    for b in batches:
        by_pl[(b["product_id"], b["location_id"])].append(b)

    for i in range(sim_days):
        d = sim_start + timedelta(days=i)
        # поставки: заказ в день по графику поставщика, приход через срок поставки
        for s in sups:
            days = {int(x) for x in s.order_weekdays.split(",")}
            od = d - timedelta(days=s.lead_time_days)
            if od.weekday() not in days or od < sim_start - timedelta(days=s.lead_time_days):
                continue
            nxt = od + timedelta(days=1)
            while nxt.weekday() not in days:
                nxt += timedelta(days=1)
            cover = (nxt - od).days + s.lead_time_days
            order_n += 1
            o_id = order_n
            o_lines = []
            for pr in prods:
                if cond[pr.id][0].id != s.id:
                    continue
                c = cond[pr.id][1]
                horizon = min(cover, pr.shelf_life_days)          # «ручная» закупка: не дальше срока годности
                need = sum(mean_rate(pr, d + timedelta(days=k)) for k in range(horizon)) * 1.1
                have = sum(b["qty"] for loc in sale_locs for b in by_pl[(pr.id, loc.id)]
                           if b["expiry_date"] >= d)
                q = max(0, need - have * 0.6)
                q = math.ceil(q / c.pack_multiple) * c.pack_multiple if q > 0 else 0
                if q > 0:
                    o_lines.append((pr, c, q))
            if not o_lines:
                order_n -= 1
                continue
            num = f"ЗП-{od.year}-{o_id:06d}"
            total = sum(c.price * q for _, c, q in o_lines)
            orders.append({"id": o_id, "number": num, "supplier_id": s.id, "location_id": wh.id, "order_date": od,
                           "expected_date": d, "next_delivery_date": nxt + timedelta(days=s.lead_time_days),
                           "status": "closed", "total": total, "over_budget": False, "created_by": u["buyer"].id,
                           "approved_by": u["buyer"].id, "sent_at": datetime.combine(od, datetime.min.time()) +
                           timedelta(hours=11), "comment": "", "plan_info": {}})
            for pr, c, q in o_lines:
                lid = len(order_lines) + 1
                received = q if rng.random() > 0.08 else q - c.pack_multiple
                order_lines.append({"id": lid, "order_id": o_id, "product_id": pr.id, "recommended_qty": q,
                                    "ordered_qty": q, "price": c.price, "pack_multiple": c.pack_multiple,
                                    "change_reason": "", "calc": {}, "received_qty": received})
                if received <= 0:
                    continue
                wb = new_batch(pr.id, wh.id, received, c.price, d, d + timedelta(days=pr.shelf_life_days),
                               line=lid, ref=f"приёмка {num}")
                # в тот же день — распределение по точкам пропорционально спросу (10 % остаётся на складе)
                rates = {loc.id: _rate(spec[pr.id], spec[pr.id][1], loc_k[loc.id], d, 0, start) for loc in sale_locs}
                tot = sum(rates.values()) or 1
                for loc in sale_locs:
                    q_loc = math.floor(received * 0.9 * rates[loc.id] / tot)
                    if q_loc <= 0:
                        continue
                    wb["qty"] -= q_loc
                    moves.append({"kind": "transfer_out", "batch_id": wb["id"], "product_id": pr.id,
                                  "location_id": wh.id, "qty": -float(q_loc), "cost": c.price, "day": d,
                                  "ts": datetime.combine(d, datetime.min.time()) + timedelta(hours=10),
                                  "ref": f"перемещение {wh.id}→{loc.id}", "user_id": u["storekeeper"].id})
                    nb = new_batch(pr.id, loc.id, q_loc, c.price, d, wb["expiry_date"], parent=wb["id"], line=lid,
                                   kind="transfer_in", ref=f"перемещение {wh.id}→{loc.id}")
                    by_pl[(pr.id, loc.id)].append(nb)
                by_pl[(pr.id, wh.id)].append(wb)
        # продажи дня по FEFO
        for loc in sale_locs:
            lines = []
            for pr in prods:
                q = int(rng.poisson(_rate(spec[pr.id], spec[pr.id][1], loc_k[loc.id], d, anom[d], start)))
                if q <= 0:
                    continue
                pool = sorted([b for b in by_pl[(pr.id, loc.id)] if b["qty"] > 0 and b["expiry_date"] >= d],
                              key=lambda b: (b["expiry_date"], b["id"]))
                if not pool:   # пополнение со склада
                    wpool = sorted([b for b in by_pl[(pr.id, wh.id)] if b["qty"] > 0 and b["expiry_date"] >= d],
                                   key=lambda b: (b["expiry_date"], b["id"]))
                    for wb in wpool[:1]:
                        t = min(wb["qty"], q * 2)
                        wb["qty"] -= t
                        moves.append({"kind": "transfer_out", "batch_id": wb["id"], "product_id": pr.id,
                                      "location_id": wh.id, "qty": -float(t), "cost": wb["cost"], "day": d,
                                      "ts": datetime.combine(d, datetime.min.time()) + timedelta(hours=9),
                                      "ref": f"перемещение {wh.id}→{loc.id}", "user_id": u["storekeeper"].id})
                        nb = new_batch(pr.id, loc.id, t, wb["cost"], d, wb["expiry_date"], parent=wb["id"],
                                       line=wb["order_line_id"], kind="transfer_in", ref=f"перемещение {wh.id}→{loc.id}")
                        by_pl[(pr.id, loc.id)].append(nb)
                        pool = [nb]
                left = q
                for b in pool:
                    t = min(b["qty"], left)
                    if t <= 0:
                        continue
                    b["qty"] -= t
                    left -= t
                    lines.append({"product_id": pr.id, "batch_id": b["id"], "qty": float(t), "price": pr.price,
                                  "discount": 0.0, "cost": b["cost"], "location_id": loc.id})
                    if left <= 0:
                        break
                sold = q - left
                if sold > 0:
                    daily[(pr.id, loc.id, d)][0] += sold
                    daily[(pr.id, loc.id, d)][1] += sold * pr.price
                if left > 0 or not any(b["qty"] > 0 and b["expiry_date"] >= d for b in by_pl[(pr.id, loc.id)]):
                    stockouts.add((pr.id, loc.id, d))
            if lines:
                sale_id += 1
                ts = datetime.combine(d, datetime.min.time()) + timedelta(hours=20)
                sale_rows.append({"id": sale_id, "external_id": f"1c:{loc.id}-{d:%Y%m%d}", "location_id": loc.id,
                                  "day": d, "ts": ts, "channel": "pos",
                                  "total": sum(x["qty"] * x["price"] for x in lines)})
                for x in lines:
                    moves.append({"kind": "sale", "batch_id": x["batch_id"], "product_id": x["product_id"],
                                  "location_id": loc.id, "qty": -x["qty"], "cost": x["cost"], "day": d, "ts": ts,
                                  "ref": f"чек 1c:{loc.id}-{d:%Y%m%d}", "user_id": None})
                    line_rows.append({k: v for k, v in x.items() if k != "location_id"} | {"sale_id": sale_id})
        # конец дня: списание просроченного и иногда — потерявшего вид
        for b in batches:
            if b["qty"] <= 1e-9:
                continue
            if b["expiry_date"] == d and spec[b["product_id"]][6] < 100:   # последний день срока — списание
                reason = expired_reason
            elif b["qty"] > 3 and spec[b["product_id"]][6] < 30 and rng.random() < 0.004:
                reason = look_reason
            else:
                continue
            q = b["qty"] if reason == expired_reason else float(math.ceil(b["qty"] * 0.2))
            wo_n += 1
            act = f"АС-{d.year}-{wo_n:06d}"
            writeoffs.append({"act_number": act, "ts": datetime.combine(d, datetime.min.time()) + timedelta(hours=21),
                              "batch_id": b["id"], "qty": q, "cost": b["cost"], "reason_id": reason,
                              "user_id": u["storekeeper"].id if b["location_id"] == wh.id else u["florist"].id,
                              "comment": ""})
            moves.append({"kind": "writeoff", "batch_id": b["id"], "product_id": b["product_id"],
                          "location_id": b["location_id"], "qty": -q, "cost": b["cost"], "day": d,
                          "ts": datetime.combine(d, datetime.min.time()) + timedelta(hours=21), "ref": act,
                          "user_id": u["storekeeper"].id})
            b["qty"] -= q
            if b["qty"] <= 1e-9:
                b["written_off"] = True
    log(f"товародвижение за {sim_days} дн.: заказов {len(orders)}, партий {len(batches)}, списаний {len(writeoffs)}")

    # ------------------------------------------------ запись в БД
    for b in batches:
        b["reserved"] = 0.0
        b["discount_pct"] = 0.0
        b["quality"] = "норма"
    db.execute(insert(PurchaseOrder), orders)
    db.execute(insert(PurchaseOrderLine), order_lines)
    _chunks(db, Batch, batches)      # родительская партия всегда создана раньше (меньший id)
    _chunks(db, Sale, sale_rows)
    _chunks(db, SaleLine, line_rows)
    _chunks(db, StockMove, moves)
    _chunks(db, WriteOff, writeoffs)
    _chunks(db, DailySales, [{"product_id": p, "location_id": l, "day": d, "qty": v[0], "revenue": v[1]}
                             for (p, l, d), v in daily.items()])
    _chunks(db, StockoutDay, [{"product_id": p, "location_id": l, "day": d} for p, l, d in stockouts])
    _fix_sequences(db)
    db.commit()
    log(f"записано: продаж {len(sale_rows)}, строк {len(line_rows)}, движений {len(moves)}")

    _current_state(db, today, prods, cond, sups, locs, u, rng, spec)
    log("текущие заказы, онлайн-заказы и партии с истекающим сроком — готово")
    return {"products": len(prods), "sales_lines": len(line_rows), "batches": len(batches), "orders": len(orders)}


def _chunks(db: Session, model, rows: list[dict], size: int = 5000) -> None:
    for i in range(0, len(rows), size):
        db.execute(insert(model), rows[i:i + size])


def _fix_sequences(db: Session) -> None:
    """После вставки с явными id в PostgreSQL нужно сдвинуть последовательности."""
    if db.bind.dialect.name != "postgresql":
        return
    for t in Base.metadata.sorted_tables:
        if "id" not in t.c:
            continue
        seq = db.execute(text(f"SELECT pg_get_serial_sequence('{t.name}', 'id')")).scalar()
        if seq:
            db.execute(text(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))


def _current_state(db: Session, today: date, prods, cond, sups, locs, u, rng, spec) -> None:
    from .services import inventory as inv, shop
    from .services.numbering import next_number
    wh = locs[0]
    salon = locs[1]
    # партии с истекающим сроком в салоне — для уценки
    for name in ("Роза Freedom 60 см", "Эустома белая", "Хризантема Сантини"):
        pr = next(p for p in prods if p.name == name)
        inv.create_batch(db, pr, salon.id, 40, cond[pr.id][1].price, today - timedelta(days=pr.shelf_life_days - 1),
                         today + timedelta(days=1), u["storekeeper"], quality="норма", ref="демо: истекает срок")
    # остатки интернет-магазина под онлайн-заказы
    online = next(x for x in locs if x.type == "online")
    for name in ("Роза Freedom 60 см", "Роза Avalanche 60 см", "Эвкалипт Цинерея"):
        pr = next(p for p in prods if p.name == name)
        inv.create_batch(db, pr, online.id, 60, cond[pr.id][1].price, today, today + timedelta(days=pr.shelf_life_days),
                         u["storekeeper"], quality="норма", ref="демо")
    db.flush()
    shop.create_order(db, "SITE-10021", today + timedelta(days=1), [{"product_id": next(
        p for p in prods if p.name == "Роза Freedom 60 см").id, "qty": 25}], "Покупатель 1", "+70000000001")
    shop.create_order(db, "SITE-10022", today + timedelta(days=2), [{"product_id": next(
        p for p in prods if p.name == "Эвкалипт Цинерея").id, "qty": 10}], "Покупатель 2", "+70000000002")
    shop.create_order(db, "SITE-10023", today + timedelta(days=5), [{"product_id": next(
        p for p in prods if p.name == "Тюльпан пионовидный").id, "qty": 51}], "Покупатель 3", "+70000000003",
        comment="предзаказ к празднику")
    # заказ в пути — для приёмки
    s_ru = next(s for s in sups if s.name.startswith("ООО «Тепличный"))
    o = PurchaseOrder(number=next_number(db, "ЗП", PurchaseOrder.number, today), supplier_id=s_ru.id,
                      location_id=wh.id, order_date=today - timedelta(days=1), expected_date=today, status="in_transit",
                      created_by=u["buyer"].id, approved_by=u["buyer"].id, sent_at=datetime.now() - timedelta(hours=20))
    db.add(o)
    db.flush()
    for pr in prods:
        if cond[pr.id][0].id == s_ru.id:
            c = cond[pr.id][1]
            q = c.pack_multiple * int(rng.integers(3, 8))
            db.add(PurchaseOrderLine(order_id=o.id, product_id=pr.id, recommended_qty=q, ordered_qty=q, price=c.price,
                                     pack_multiple=c.pack_multiple, calc={}))
    db.flush()
    db.refresh(o)
    o.total = round(sum(ln.ordered_qty * ln.price for ln in o.lines), 2)
    # сценарий ближайшего крупного праздника
    for (m, d), name in [((2, 14), "День святого Валентина"), ((3, 8), "8 Марта"), ((9, 1), "1 Сентября"),
                         ((12, 31), "Новый год")]:
        ev = date(today.year, m, d)
        if ev < today:
            ev = date(today.year + 1, m, d)
        if (ev - today).days <= 200:
            g = {x.name: x.id for x in db.query(ProductGroup)}
            coefs = {"8 Марта": {"Тюльпаны": 9, "Розы": 5, "Эустома и альстромерия": 3.5},
                     "День святого Валентина": {"Розы": 6, "Тюльпаны": 2},
                     "1 Сентября": {"Хризантемы": 3.5, "Розы": 2.2},
                     "Новый год": {"Розы": 1.8, "Горшечные растения": 1.6}}[name]
            db.add(HolidayScenario(name=f"{name} {ev.year}", event_date=ev, days_before=2,
                                   last_delivery_date=ev - timedelta(days=3),
                                   coefficients={str(g[k]): v for k, v in coefs.items()}, approved=True,
                                   comment="Коэффициенты утверждены менеджером по закупкам"))
            break
    db.commit()
