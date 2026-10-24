"""Сквозные тесты интерфейса (Playwright): основные варианты использования ПР 7-8 в браузере.

Запуск: pytest tests_e2e (нужны собранный интерфейс в floraplan/static и `playwright install chromium`).
Сервер поднимается на временной БД с небольшими демо-данными."""
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api")
STATIC = os.path.join(os.path.dirname(__file__), "..", "floraplan", "static", "index.html")
pytestmark = pytest.mark.skipif(not os.path.exists(STATIC), reason="интерфейс не собран (npm run build)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e")
    env = dict(os.environ, FLORAPLAN_DATA_DIR=str(data), FLORAPLAN_SCHEDULER_ENABLED="false",
               FLORAPLAN_WEATHER_ENABLED="false", PYTHONIOENCODING="utf-8")
    prep = ("from floraplan import db, migrate\n"
            "from floraplan.demo import generate\n"
            "from floraplan.services import forecasting\n"
            "migrate.upgrade()\n"
            "s = db.session()\n"
            "generate(s, history_days=200, sim_days=21, log=lambda m: None)\n"
            "forecasting.run(s)\n")
    subprocess.run([sys.executable, "-c", prep], env=env, check=True, timeout=600)
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "floraplan.main:app", "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def login(browser, base, user, password="demo"):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    page.fill("#login", user)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_selector(".ant-layout-sider")
    page.errors = errors
    return page


def success(page, text: str):
    page.wait_for_selector(f".ant-message-success:has-text('{text}')", timeout=20000)


def test_wrong_password(server, browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(server + "/")
    page.fill("#login", "buyer")
    page.fill("#password", "нет")
    page.click("button[type=submit]")
    page.wait_for_selector("text=Неверный логин или пароль")
    ctx.close()


def test_buyer_plans_submits_and_sends_order(server, browser):
    page = login(browser, server, "buyer")
    page.goto(server + "/purchasing")
    page.click(".ant-tabs-tab:has-text('Расчёт заказа')")
    create = page.locator("button:has-text('Создать черновик заказа')")
    for i in range(6):   # первый поставщик, у которого есть что заказать (у остальных хватает запаса)
        page.locator(".ant-tabs-tabpane-active .ant-select").first.click()
        page.locator(".ant-select-dropdown:visible .ant-select-item-option").nth(i).click()
        page.click("button:has-text('Рассчитать')")
        page.wait_for_selector("text=Сумма заказа")
        if create.is_enabled():
            break
    create.click()
    page.wait_for_url("**/purchasing/orders/*")
    page.wait_for_selector(".ant-tag:has-text('Черновик')")
    page.click("button:has-text('На согласование')")
    page.wait_for_selector(".ant-tag:has-text('Утверждён')")
    page.click("button:has-text('Отправить поставщику')")
    page.wait_for_selector(".ant-tag:has-text('Отправлен')")
    assert "письмо" in page.inner_text("pre")
    assert not page.errors


def test_storekeeper_receives_delivery(server, browser):
    page = login(browser, server, "storekeeper")
    page.goto(server + "/receiving")
    page.click(".ant-card:has-text('ЗП-')")
    page.click("button:has-text('Всё поступило по заказу')")
    page.click("button:has-text('Завершить приёмку')")
    page.wait_for_selector("text=Принято партий")
    assert page.is_visible("button:has-text('Этикетки партий')")
    assert not page.errors


def test_florist_marks_down_expiring_batch(server, browser):
    page = login(browser, server, "florist")
    page.goto(server + "/expiry")
    row = page.locator("tr.ant-table-row:has(.ant-tag:has-text('уценить на'))").first
    row.locator("input[type=checkbox]").check()
    page.click("button:has-text('Уценить выбранные')")
    success(page, "Уценка подтверждена")
    assert not page.errors


def test_shop_manager_completes_online_order(server, browser):
    page = login(browser, server, "shop")
    page.goto(server + "/online")
    row = page.locator("tr.ant-table-row:has(.ant-tag:has-text('Зарезервирован'))").first
    row.locator("button:has-text('Выполнен')").click()
    success(page, "Заказ выполнен")
    assert not page.errors


def test_analyst_recalculates_forecast(server, browser):
    page = login(browser, server, "analyst")
    page.goto(server + "/forecast")
    page.click("button:has-text('Рассчитать сейчас')")
    page.wait_for_selector(".ant-modal:has-text('Прогноз рассчитан')", timeout=120000)
    page.click(".ant-modal button:has-text('OK')")
    page.click(".ant-tabs-tab:has-text('Версии модели')")
    page.wait_for_selector("td:has-text('Опубликована')")
    assert not page.errors


def test_director_sees_reports_and_audit(server, browser):
    page = login(browser, server, "director")
    page.goto(server + "/reports")
    page.wait_for_selector("tr.ant-table-row")
    page.goto(server + "/admin")
    page.click(".ant-tabs-tab:has-text('Журнал действий')")
    page.wait_for_selector("td:has-text('Вход в систему')")
    assert not page.errors


def test_admin_connects_sales_channel(server, browser):
    """Р-4: администратор подключает маркетплейс, получает ключ один раз; новый ключ отменяет старый."""
    page = login(browser, server, "admin", "admin")
    page.goto(server + "/admin")
    page.click(".ant-tabs-tab:has-text('Каналы продаж')")
    page.click("button:has-text('Подключить канал')")
    modal = page.locator(".ant-modal:visible")
    modal.locator(".ant-form-item:has-text('Название') input").fill("Маркетплейс")
    modal.locator(".ant-form-item:has-text('Код') input").fill("market")
    modal.locator(".ant-form-item:has-text('Место хранения') .ant-select").click()
    page.locator(".ant-select-dropdown:visible .ant-select-item-option:has-text('Интернет')").first.click()
    modal.locator("button:has-text('Сохранить')").click()
    key = page.locator(".ant-modal-confirm code:has-text('ch_')").inner_text().strip()
    assert key.startswith("ch_")
    page.click(".ant-modal-confirm button:has-text('OK')")
    page.wait_for_selector("td:has-text('market')")
    assert httpx.get(server + "/api/shop/stock", headers={"X-API-Key": key}).status_code == 200
    # новый ключ: старый перестаёт действовать
    page.click("tr.ant-table-row:has-text('market')")
    page.click(".ant-modal:visible button:has-text('Новый ключ API')")
    page.click(".ant-modal-confirm button:has-text('Выдать')")
    new_key = page.locator(".ant-modal-confirm code:has-text('ch_')").inner_text().strip()
    assert new_key != key
    assert httpx.get(server + "/api/shop/stock", headers={"X-API-Key": key}).status_code == 401
    assert httpx.get(server + "/api/shop/stock", headers={"X-API-Key": new_key}).status_code == 200
    assert not page.errors


def _supplier_method(page, method: str, url: str | None = None):
    page.locator(".ant-tabs-tabpane-active tr.ant-table-row").first.locator("button").first.click()
    modal = page.locator(".ant-modal:visible")
    modal.locator(".ant-form-item:has-text('Способ отправки заказа') .ant-select").click()
    page.locator(f".ant-select-dropdown:visible .ant-select-item-option:has-text('{method}')").click()
    if url is not None:
        modal.locator(".ant-form-item:has-text('Адрес API поставщика') input").fill(url)
    modal.locator("button:has-text('Сохранить')").click()


def test_buyer_sets_supplier_order_method(server, browser):
    """Р-4: способ отправки заказа в карточке поставщика; для API без адреса — понятная ошибка."""
    page = login(browser, server, "buyer")
    page.goto(server + "/nsi")
    page.click(".ant-tabs-tab:has-text('Поставщики')")
    page.wait_for_selector(".ant-tabs-tabpane-active tr.ant-table-row")
    _supplier_method(page, "API поставщика", "")
    page.wait_for_selector(".ant-message-error:has-text('укажите адрес')")
    page.locator(".ant-modal:visible .ant-form-item:has-text('Адрес API поставщика') input").fill("https://supplier.example/orders")
    page.click(".ant-modal:visible button:has-text('Сохранить')")
    success(page, "Сохранено")
    page.wait_for_selector(".ant-tabs-tabpane-active td:has-text('API поставщика')")
    _supplier_method(page, "E-mail")     # вернуть как было: заказы демо-поставщиков уходят письмом
    page.wait_for_selector(".ant-tabs-tabpane-active td:has-text('API поставщика')", state="detached")
    assert not page.errors
