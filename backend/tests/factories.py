"""Небольшой набор справочников для тестов."""
from types import SimpleNamespace

from floraplan.models import Location, Product, ProductGroup, Supplier, SupplyCondition


def reference(s) -> SimpleNamespace:
    roses, chrys, green = ProductGroup(name="Розы"), ProductGroup(name="Хризантемы"), ProductGroup(name="Зелень")
    s.add_all([roses, chrys, green])
    s.flush()
    rose = Product(name="Роза Freedom 60 см", kind="Роза", variety="Freedom", stem_length=60, color="красный",
                   shelf_life_days=7, pack_multiple=10, group_id=roses.id, barcode="4600000000011", price=150)
    chr_ = Product(name="Хризантема кустовая", kind="Хризантема", shelf_life_days=12, pack_multiple=5,
                   group_id=chrys.id, barcode="4600000000028", price=120)
    euc = Product(name="Эвкалипт", kind="Зелень", shelf_life_days=10, pack_multiple=5, group_id=green.id,
                  barcode="4600000000035", price=60)
    s.add_all([rose, chr_, euc])
    wh = Location(name="Склад", type="warehouse")
    salon = Location(name="Салон «Центр»", type="salon")
    online = Location(name="Интернет-магазин", type="online")
    s.add_all([wh, salon, online])
    imp = Supplier(name="Holland Flowers B.V.", country="Нидерланды", lead_time_days=5, min_order_sum=20000,
                   email="orders@holland.example", order_weekdays="0,3")
    ru = Supplier(name="Тепличный комбинат", country="Россия", lead_time_days=1, min_order_sum=5000,
                  email="sale@teplica.example", order_weekdays="0,2,4")
    s.add_all([imp, ru])
    s.flush()
    s.add_all([
        SupplyCondition(supplier_id=imp.id, product_id=rose.id, price=60, pack_multiple=20),
        SupplyCondition(supplier_id=ru.id, product_id=chr_.id, price=55, pack_multiple=10),
        SupplyCondition(supplier_id=ru.id, product_id=euc.id, price=20, pack_multiple=10),
    ])
    s.commit()
    return SimpleNamespace(roses=roses, chrys=chrys, green=green, rose=rose, chr=chr_, euc=euc,
                           wh=wh, salon=salon, online=online, imp=imp, ru=ru)
