"""Отправка заказов поставщикам через адаптеры (С-11, Р-4).

Адаптер — функция (db, заказ) -> строка «куда ушёл заказ», зарегистрированная под кодом; код хранится
у поставщика (Supplier.order_method). Новый способ (ЭДО, портал поставщика) добавляется одним адаптером
без изменения расчёта и согласования заказов."""
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from .. import appsettings
from ..errors import DomainError
from ..models import PurchaseOrder
from . import mail


@dataclass(frozen=True)
class Adapter:
    code: str
    name: str
    send: Callable[[Session, PurchaseOrder], str]


ADAPTERS: dict[str, Adapter] = {}


def adapter(code: str, name: str):
    def reg(fn):
        ADAPTERS[code] = Adapter(code, name, fn)
        return fn
    return reg


def send(db: Session, o: PurchaseOrder) -> str:
    a = ADAPTERS.get(o.supplier.order_method or "email")
    if a is None:
        raise DomainError(f"Неизвестный способ отправки заказа: {o.supplier.order_method}")
    return a.send(db, o)


@adapter("email", "E-mail: заказ в XLSX")
def send_email(db: Session, o: PurchaseOrder) -> str:
    from .purchasing import order_xlsx
    where = mail.send(o.supplier.email, f"Заказ {o.number} от {o.order_date:%d.%m.%Y}",
                      f"Здравствуйте!\n\nНаправляем заказ № {o.number}. Поставка {o.expected_date:%d.%m.%Y}, "
                      f"адрес: {o.location.name}.\nСумма {o.total:.2f} руб.\n\n"
                      f"{appsettings.get(db, 'company_name')}", order_xlsx(db, o), f"{o.number}.xlsx")
    return "отправлен по e-mail" if where == "smtp" else f"письмо: {where}"


def order_json(db: Session, o: PurchaseOrder) -> dict:
    return {"number": o.number, "buyer": appsettings.get(db, "company_name"), "order_date": o.order_date.isoformat(),
            "delivery_date": o.expected_date.isoformat(), "delivery_address": o.location.name, "total": o.total,
            "lines": [{"barcode": ln.product.barcode, "name": ln.product.name, "unit": ln.product.unit,
                       "qty": ln.ordered_qty, "pack_multiple": ln.pack_multiple, "price": ln.price}
                      for ln in o.lines if ln.ordered_qty > 0]}


@adapter("api", "API поставщика: заказ в JSON")
def send_api(db: Session, o: PurchaseOrder) -> str:
    s = o.supplier
    if not s.order_url.startswith(("http://", "https://")):
        raise DomainError("У поставщика не задан адрес API для заказов")
    headers = {"Authorization": f"Bearer {s.order_api_key}"} if s.order_api_key else {}
    try:
        r = httpx.post(s.order_url, json=order_json(db, o), headers=headers, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise DomainError(f"API поставщика не приняло заказ: {e}", status=502)
    return f"передан в API поставщика (ответ {r.status_code})"
