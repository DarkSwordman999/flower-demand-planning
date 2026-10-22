"""Планирование закупок (П-6…П-8, П-12; С-7…С-11, С-15; IDEF3 A4 и 4.3; ПР 7-8 «Сформировать план закупок»).

Расчёт рекомендуемого заказа поставщику:
  4.3.1  α = Cu / (Cu + Co) — целевой уровень обслуживания («продавец газет»);
  4.3.2  сценарий праздника — коэффициенты спроса групп в пиковые дни;
  4.3.3  D — квантиль α спроса на период до следующей поставки (L + T);
  4.3.4  Q = max(0, D − S − Z), S — запас, который успеет продаться до истечения срока, Z — заказы в пути;
  4.5    округление вверх до кратности упаковки, дозаказ до минимальной суммы поставщика (С-9);
  4.4    при превышении недельного бюджета — сокращение по ABC (сначала C, затем B); если не хватает —
         заказ утверждает директор (П-8).
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
import math

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import appsettings, audit
from ..errors import DomainError, NotFound
from ..models import (Batch, DailySales, Forecast, HolidayScenario, Location, Product, PurchaseOrder,
                      PurchaseOrderLine, Supplier, SupplyCondition, User)
from . import forecasting as fs
from . import mail, tsmodels as tm, xlsx
from .numbering import next_number

IN_TRANSIT = ("approved", "sent", "confirmed", "in_transit")
COMMITTED = ("approved", "sent", "confirmed", "in_transit", "received", "closed")
TRANSITIONS = {
    "submit": ({"draft"}, None),
    "approve": ({"approval"}, "approved"),
    "reject": ({"approval"}, "draft"),
    "send": ({"approved"}, "sent"),
    "confirm": ({"sent"}, "confirmed"),
    "in_transit": ({"sent", "confirmed"}, "in_transit"),
    "close": ({"received"}, "closed"),
    "cancel": ({"draft", "approval", "approved", "sent", "confirmed"}, "cancelled"),
}


# ---------------------------------------------------------------- вспомогательные расчёты
def next_delivery(supplier: Supplier, order_date: date) -> date:
    """Следующая поставка: ближайший следующий день заказа по графику поставщика + срок поставки."""
    days = sorted(int(x) for x in supplier.order_weekdays.split(",") if x.strip()) or [order_date.weekday()]
    d = order_date + timedelta(days=1)
    while d.weekday() not in days:
        d += timedelta(days=1)
    return d + timedelta(days=supplier.lead_time_days)


def abc_classes(db: Session, until: date, days: int = 90) -> dict[int, str]:
    """ABC по выручке за период: A — до 80 % выручки, B — до 95 %, C — остальное."""
    rows = (db.query(DailySales.product_id, func.sum(DailySales.revenue))
            .filter(DailySales.day > until - timedelta(days=days), DailySales.day <= until)
            .group_by(DailySales.product_id).all())
    total = sum(max(0, r[1] or 0) for r in rows)
    out, acc = {}, 0.0
    for pid, rev in sorted(rows, key=lambda r: -(r[1] or 0)):
        share = acc / total if total > 0 else 1
        out[pid] = "A" if share < 0.8 else ("B" if share < 0.95 else "C")
        acc += max(0, rev or 0)
    return out


def service_level(price: float, cost: float, salvage: float, lo: float, hi: float) -> float:
    cu = max(price - cost, 0.0)
    co = max(cost * (1 - salvage), 0.01)
    return min(max(cu / (cu + co), lo), hi)


def ceil_to(q: float, pack: int) -> float:
    pack = max(int(pack), 1)
    return float(math.ceil(q / pack - 1e-9) * pack) if q > 1e-9 else 0.0


def week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def committed_this_week(db: Session, d: date, exclude_id: int | None = None) -> float:
    a, b = week_bounds(d)
    q = db.query(func.coalesce(func.sum(PurchaseOrder.total), 0.0)).filter(
        PurchaseOrder.status.in_(COMMITTED), PurchaseOrder.order_date >= a, PurchaseOrder.order_date <= b)
    if exclude_id:
        q = q.filter(PurchaseOrder.id != exclude_id)
    return float(q.scalar())


def find_scenario(db: Session, start: date, end: date) -> HolidayScenario | None:
    """Утверждённый сценарий, пиковые дни которого попадают в период [start, end)."""
    for s in db.query(HolidayScenario).filter(HolidayScenario.approved.is_(True)):
        peak_from = s.event_date - timedelta(days=s.days_before)
        if peak_from < end and s.event_date >= start:
            return s
    return None


def daily_demand(db: Session, run_id: int, product_ids: list[int], start: date, end: date) -> tuple[dict, dict, dict]:
    """P50 по дням (сумма по точкам продаж), относительная ошибка и коэффициент события по товарам.
    Дни за горизонтом прогноза — средним последней недели прогноза по дню недели."""
    locs = [x.id for x in db.query(Location).filter(Location.type.in_(fs.SALE_LOCATIONS))]
    p50 = defaultdict(lambda: defaultdict(float))
    sig_w = defaultdict(lambda: [0.0, 0.0])
    coef = defaultdict(dict)
    for f in db.query(Forecast).filter(Forecast.run_id == run_id, Forecast.product_id.in_(product_ids),
                                       Forecast.location_id.in_(locs)):
        p50[f.product_id][f.day] += f.p50
        sig_w[f.product_id][0] += f.sigma * f.p50
        sig_w[f.product_id][1] += f.p50
        coef[f.product_id][f.day] = f.event_coef
    out = {}
    for pid in product_ids:
        days = p50.get(pid, {})
        last = max(days) if days else None
        series = {}
        d = start
        while d < end:
            if d in days:
                series[d] = days[d]
            elif last is not None:
                same = [days[x] / max(coef[pid].get(x, 1.0), 1e-6) for x in days if x.weekday() == d.weekday()
                        and (last - x).days < 7]
                series[d] = same[0] if same else 0.0
            else:
                series[d] = 0.0
            d += timedelta(days=1)
        out[pid] = series
    sigma = {pid: (w[0] / w[1] if w[1] > 0 else 0.5) for pid, w in sig_w.items()}
    return out, sigma, coef


def usable_stock(batches: list[Batch], demand: dict[date, float], start: date) -> float:
    """Сколько имеющегося запаса продастся до истечения срока (FEFO по прогнозу P50) — S в формуле С-7."""
    pool = sorted(([b.expiry_date, b.available] for b in batches if b.available > 1e-9), key=lambda x: x[0])
    used = 0.0
    for d in sorted(demand):
        need = demand[d]
        for item in pool:
            if need <= 1e-9:
                break
            if item[0] < d or item[1] <= 1e-9:
                continue
            t = min(item[1], need)
            item[1] -= t
            need -= t
            used += t
    return used


# ---------------------------------------------------------------- расчёт плана
def plan(db: Session, supplier_id: int, order_date: date | None = None, delivery_date: date | None = None,
         scenario_id: int | None = None, location_id: int | None = None) -> dict:
    order_date = order_date or date.today()
    sup = db.get(Supplier, supplier_id)
    if sup is None or not sup.active:
        raise NotFound("Поставщик не найден")
    delivery = delivery_date or order_date + timedelta(days=sup.lead_time_days)
    if delivery < order_date + timedelta(days=sup.lead_time_days):
        raise DomainError(f"Поставщик не успеет: срок поставки {sup.lead_time_days} дн.")
    nxt = next_delivery(sup, delivery - timedelta(days=sup.lead_time_days))
    if nxt <= delivery:
        nxt = delivery + timedelta(days=1)
    run = fs.current_run(db)
    if run is None:
        raise DomainError("Прогноз спроса ещё не рассчитан — рассчитайте прогноз")
    warnings = []
    if run.base_date < order_date:
        warnings.append(f"Используется прогноз от {run.base_date:%d.%m.%Y}: на сегодня прогноз не рассчитан")
    s = appsettings.get_all(db)
    conds = (db.query(SupplyCondition).options(joinedload(SupplyCondition.product).joinedload(Product.group))
             .filter(SupplyCondition.supplier_id == sup.id).all())
    conds = [c for c in conds if c.product.active]
    if not conds:
        raise DomainError("У поставщика не заданы условия поставки товаров")
    pids = [c.product_id for c in conds]
    window_end = nxt                      # спрос с сегодняшнего дня до следующей поставки (L + T)
    shelf_end = delivery + timedelta(days=max(c.product.shelf_life_days for c in conds))
    demand, sigma, ev_coef = daily_demand(db, run.id, pids, order_date, max(window_end, shelf_end))
    if scenario_id:
        scen = db.get(HolidayScenario, scenario_id)
        if scen is None:
            raise NotFound("Сценарий не найден")
        if not scen.approved:
            raise DomainError("Сценарий праздника не утверждён")
    else:
        scen = find_scenario(db, order_date, window_end)
    if scen and delivery > scen.last_delivery_date and scen.event_date >= delivery:
        warnings.append(f"Поставка {delivery:%d.%m} позже последней даты поставки по сценарию «{scen.name}» "
                        f"({scen.last_delivery_date:%d.%m})")
    abc = abc_classes(db, order_date - timedelta(days=1))
    stock = defaultdict(list)
    for b in db.query(Batch).filter(Batch.product_id.in_(pids), Batch.qty - Batch.reserved > 1e-9,
                                    Batch.expiry_date >= order_date):
        stock[b.product_id].append(b)
    transit = defaultdict(float)
    for ln in (db.query(PurchaseOrderLine).join(PurchaseOrder)
               .filter(PurchaseOrder.status.in_(IN_TRANSIT), PurchaseOrder.expected_date < window_end,
                       PurchaseOrderLine.product_id.in_(pids))):
        transit[ln.product_id] += ln.ordered_qty
    lines = []
    for c in conds:
        p = c.product
        dem = dict(demand[p.id])
        factor_days = []
        if scen:
            k = float(scen.coefficients.get(str(p.group_id), scen.coefficients.get(p.group_id, 1.0)))
            peak_from = scen.event_date - timedelta(days=scen.days_before)
            for d in list(dem):
                if peak_from <= d <= scen.event_date:
                    base_coef = ev_coef.get(p.id, {}).get(d, 1.0)
                    dem[d] = dem[d] / max(base_coef, 1e-6) * k     # 4.3.2: коэффициент сценария вместо календарного
                    factor_days.append(d)
        window = [dem[d] for d in sorted(dem) if d < window_end]
        alpha = service_level(p.price, c.price, float(s["salvage_share"]), float(s["service_level_min"]),
                              float(s["service_level_max"]))
        D = tm.period_quantile(window, sigma.get(p.id, 0.5), alpha)
        S = usable_stock(stock[p.id], {d: v for d, v in dem.items() if d < window_end}, order_date)
        Z = transit[p.id]
        q_raw = max(0.0, D - S - Z)
        cap_days = [dem[d] for d in sorted(dem) if delivery <= d < delivery + timedelta(days=p.shelf_life_days)]
        cap = tm.period_quantile(cap_days, sigma.get(p.id, 0.5), 0.95) if cap_days else q_raw
        q_cap = min(q_raw, cap)
        q = ceil_to(q_cap, c.pack_multiple)
        lines.append({
            "product_id": p.id, "product": p.name, "group_id": p.group_id, "group": p.group.name, "unit": p.unit,
            "abc": abc.get(p.id, "C"), "price": c.price, "pack_multiple": c.pack_multiple,
            "recommended_qty": q, "ordered_qty": q,
            "calc": {"D": round(D, 1), "S": round(S, 1), "Z": round(Z, 1), "alpha": round(alpha, 3),
                     "mean_demand": round(sum(window), 1), "q_raw": round(q_raw, 1),
                     "cap_shelf_life": round(cap, 1), "days": len(window),
                     "scenario_days": [str(d) for d in sorted(factor_days)], "notes": []},
        })
        if q_raw > cap + 1e-9:
            lines[-1]["calc"]["notes"].append(f"ограничено продажами за срок годности ({p.shelf_life_days} дн.)")
    total = lambda: sum(x["ordered_qty"] * x["price"] for x in lines)  # noqa: E731

    # С-9: дозаказ до минимальной суммы поставщика — позиции группы A с наибольшим прогнозом
    if 0 < total() < sup.min_order_sum:
        a_lines = sorted([x for x in lines if x["abc"] == "A"] or lines, key=lambda x: -x["calc"]["mean_demand"])
        i = 0
        while total() < sup.min_order_sum and i < 10000:
            x = a_lines[i % len(a_lines)]
            x["ordered_qty"] += x["pack_multiple"]
            x["recommended_qty"] = x["ordered_qty"]
            note = "дозаказ до минимальной суммы поставщика"
            if note not in x["calc"]["notes"]:
                x["calc"]["notes"].append(note)
            i += 1
        warnings.append(f"Сумма заказа доведена до минимальной суммы поставщика {sup.min_order_sum:,.0f} руб.".replace(",", " "))
        for x in lines:
            if x["ordered_qty"] > x["calc"]["cap_shelf_life"] + x["pack_multiple"]:
                x["calc"]["notes"].append("больше, чем продастся за срок годности — риск списания")
                warnings.append(f"«{x['product']}»: дозаказ превышает продажи за срок годности — риск списания")

    # 4.4: бюджет недели — сокращение по ABC
    budget = float(s["weekly_budget"])
    committed = committed_this_week(db, order_date)
    cuts = []
    for cls in ("C", "B"):
        for x in sorted([x for x in lines if x["abc"] == cls], key=lambda x: -x["ordered_qty"] * x["price"]):
            while committed + total() > budget and x["ordered_qty"] > 0:
                x["ordered_qty"] -= x["pack_multiple"]
                x["recommended_qty"] = max(0.0, x["ordered_qty"])
                x["ordered_qty"] = x["recommended_qty"]
                if x["product"] not in cuts:
                    cuts.append(x["product"])
                    x["calc"]["notes"].append(f"сокращено по бюджету (группа {cls})")
    over = committed + total() > budget + 1e-6
    if cuts:
        warnings.append("Превышен бюджет недели: сокращены позиции групп C/B — " + ", ".join(cuts))
    if over:
        warnings.append("Сумма заказов недели превышает бюджет — заказ утверждает директор")
    if total() < sup.min_order_sum and total() > 0:
        warnings.append("После сокращения по бюджету сумма заказа меньше минимальной суммы поставщика")
    return {"supplier_id": sup.id, "supplier": sup.name, "order_date": order_date, "delivery_date": delivery,
            "next_delivery_date": nxt, "location_id": location_id or _warehouse(db),
            "scenario_id": scen.id if scen else None, "scenario": scen.name if scen else None,
            "forecast_run_id": run.id, "forecast_base": run.base_date, "lines": lines, "total": round(total(), 2),
            "budget": budget, "committed_week": round(committed, 2), "over_budget": over, "warnings": warnings,
            "min_order_sum": sup.min_order_sum}


def _warehouse(db: Session) -> int:
    w = db.query(Location).filter(Location.type == "warehouse").order_by(Location.id).first()
    if w is None:
        raise DomainError("Не задан склад для приёмки поставок")
    return w.id


# ---------------------------------------------------------------- заказ поставщику
def create_order(db: Session, p: dict, user: User) -> PurchaseOrder:
    lines = [x for x in p["lines"] if x["ordered_qty"] > 0 or x["recommended_qty"] > 0]
    if not lines:
        raise DomainError("Заказывать нечего: рекомендуемые объёмы нулевые")
    o = PurchaseOrder(number=next_number(db, "ЗП", PurchaseOrder.number, p["order_date"]), supplier_id=p["supplier_id"],
                      location_id=p["location_id"], order_date=p["order_date"], expected_date=p["delivery_date"],
                      next_delivery_date=p["next_delivery_date"], status="draft", scenario_id=p["scenario_id"],
                      created_by=user.id, over_budget=p["over_budget"],
                      plan_info={k: (str(v) if isinstance(v, date) else v) for k, v in p.items() if k != "lines"})
    db.add(o)
    db.flush()
    for x in lines:
        db.add(PurchaseOrderLine(order_id=o.id, product_id=x["product_id"], recommended_qty=x["recommended_qty"],
                                 ordered_qty=x["ordered_qty"], price=x["price"], pack_multiple=x["pack_multiple"],
                                 calc=dict(x["calc"], abc=x["abc"])))
    db.flush()
    db.refresh(o)
    recalc(o)
    audit.log(db, user, "Сформирован заказ поставщику", "order", o.number,
              f"{p['supplier']}, сумма {o.total:.2f}, поставка {o.expected_date:%d.%m.%Y}")
    return o


def recalc(o: PurchaseOrder) -> None:
    o.total = round(sum(ln.ordered_qty * ln.price for ln in o.lines), 2)


def update_lines(db: Session, o: PurchaseOrder, items: list[dict], user: User) -> PurchaseOrder:
    """Корректировка менеджером (П-7): кратность упаковки, причина при отклонении больше 30 % (С-10)."""
    if o.status != "draft":
        raise DomainError("Изменять можно только черновик заказа")
    limit = float(appsettings.get(db, "change_reason_pct"))
    by_id = {ln.id: ln for ln in o.lines}
    by_product = {ln.product_id: ln for ln in o.lines}
    for it in items:
        ln = by_id.get(it.get("line_id")) or by_product.get(it.get("product_id"))
        if ln is None:
            if not it.get("product_id"):
                raise DomainError("Не указана строка заказа")
            c = (db.query(SupplyCondition)
                 .filter_by(supplier_id=o.supplier_id, product_id=it["product_id"]).first())
            if c is None:
                raise DomainError("Товар не поставляется этим поставщиком")
            ln = PurchaseOrderLine(order_id=o.id, product_id=c.product_id, recommended_qty=0, ordered_qty=0,
                                   price=c.price, pack_multiple=c.pack_multiple, calc={})
            db.add(ln)
            o.lines.append(ln)
        q = float(it["ordered_qty"])
        if q < 0:
            raise DomainError("Количество не может быть отрицательным")
        if abs(q / ln.pack_multiple - round(q / ln.pack_multiple)) > 1e-9:
            raise DomainError(f"Количество должно быть кратно упаковке ({ln.pack_multiple})")
        base = max(ln.recommended_qty, 1.0)
        reason = (it.get("change_reason") or "").strip()
        if abs(q - ln.recommended_qty) / base * 100 > limit + 1e-9 and not reason:
            name = db.get(Product, ln.product_id).name
            raise DomainError(f"«{name}»: изменение рекомендации больше чем на {limit:g} % — укажите причину")
        ln.ordered_qty = q
        ln.change_reason = reason
    recalc(o)
    audit.log(db, user, "Скорректирован заказ", "order", o.number, f"сумма {o.total:.2f}")
    return o


def order_xlsx(db: Session, o: PurchaseOrder) -> bytes:
    company = appsettings.get(db, "company_name")
    return xlsx.build(
        f"Заказ поставщику № {o.number}",
        ["№", "Товар", "Штрихкод", "Ед.", "Количество", "Кратность", "Цена", "Сумма"],
        [[i + 1, ln.product.name, ln.product.barcode, ln.product.unit, ln.ordered_qty, ln.pack_multiple, ln.price,
          ln.ordered_qty * ln.price] for i, ln in enumerate(o.lines) if ln.ordered_qty > 0],
        meta=[("Покупатель", company), ("Поставщик", o.supplier.name), ("Дата заказа", o.order_date.strftime("%d.%m.%Y")),
              ("Дата поставки", o.expected_date.strftime("%d.%m.%Y")), ("Адрес поставки", o.location.name)],
        footer=[f"Итого: {o.total:,.2f} руб.".replace(",", " "), "Просим подтвердить заказ ответным письмом."],
        sheet="Заказ")


def transition(db: Session, o: PurchaseOrder, action: str, user: User, comment: str = "") -> PurchaseOrder:
    if action not in TRANSITIONS:
        raise DomainError("Неизвестное действие")
    allowed, target = TRANSITIONS[action]
    if o.status not in allowed:
        raise DomainError(f"Действие недоступно для заказа в статусе «{_status_name(o.status)}»")
    if action in ("approve", "reject") and user.role not in ("director", "admin"):
        raise DomainError("Утверждает заказы сверх бюджета директор", status=403)
    if action == "submit":
        if o.total <= 0:
            raise DomainError("Пустой заказ отправлять на согласование нельзя")
        budget = float(appsettings.get(db, "weekly_budget"))
        o.over_budget = committed_this_week(db, o.order_date, o.id) + o.total > budget + 1e-6
        target = "approval" if o.over_budget else "approved"
        if not o.over_budget:
            o.approved_by = user.id
    if action == "approve":
        o.approved_by = user.id
    if action == "send":
        data = order_xlsx(db, o)
        where = mail.send(o.supplier.email, f"Заказ {o.number} от {o.order_date:%d.%m.%Y}",
                          f"Здравствуйте!\n\nНаправляем заказ № {o.number}. Поставка {o.expected_date:%d.%m.%Y}, "
                          f"адрес: {o.location.name}.\nСумма {o.total:.2f} руб.\n\n"
                          f"{appsettings.get(db, 'company_name')}", data, f"{o.number}.xlsx")
        o.sent_at = datetime.now()
        comment = (comment + "; " if comment else "") + ("отправлен по e-mail" if where == "smtp" else f"письмо: {where}")
    if comment:
        o.comment = (o.comment + "\n" if o.comment else "") + f"{datetime.now():%d.%m %H:%M} {user.login}: {comment}"
    o.status = target
    audit.log(db, user, f"Заказ: {_status_name(target)}", "order", o.number, comment)
    return o


def _status_name(code: str) -> str:
    from ..models import ORDER_STATUSES
    return ORDER_STATUSES.get(code, code)
