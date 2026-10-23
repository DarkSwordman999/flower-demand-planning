"""Нагрузочный тест (ТЗ: П-1 — отклик интерфейса ≤ 2 с, П-2 — до 30 пользователей и 10 000 чеков в сутки;
ПР 3: «имитация пикового дня»). Запуск на демо-данных:

    pip install locust
    locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 -u 30 -r 5 -t 5m --headless

Пиковый день 8 Марта — ~9 000 чеков; кассы шлют чеки пачками раз в несколько минут."""
import random
import uuid
from datetime import datetime

from locust import HttpUser, between, task

BARCODES = [f"46012345{n:04d}" for n in range(1, 22)]


def ean(body: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - s % 10) % 10)


BARCODES = [ean(b) for b in BARCODES]
STORES = ["Салон «Центральный»", "Салон «Заречье»", "Салон «Пролетарский»", "Салон «Привокзальный»"]


class Staff(HttpUser):
    """Сотрудники: главная, остатки, прогноз, отчёты (П-1: отклик ≤ 2 с)."""
    weight = 3
    wait_time = between(2, 6)

    def on_start(self):
        login = random.choice(["director", "buyer"])   # роли с доступом ко всем проверяемым страницам
        r = self.client.post("/api/auth/token", data={"username": login, "password": "demo"})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    @task(3)
    def dashboard(self):
        self.client.get("/api/dashboard")

    @task(2)
    def batches(self):
        self.client.get("/api/inventory/batches")

    @task(2)
    def forecast(self):
        self.client.get("/api/forecast/series", params={"product_id": random.randint(1, 20)}, name="/api/forecast/series")

    @task(1)
    def expiry(self):
        self.client.get("/api/expiry/recommendations")

    @task(1)
    def report(self):
        self.client.get("/api/reports/sales", params={"group_by": "group"})


class Cashbox(HttpUser):
    """«1С» передаёт пачки чеков (пиковый день: ~10 000 чеков в сутки)."""
    weight = 1
    wait_time = between(5, 10)

    @task
    def receipts(self):
        batch = []
        for _ in range(random.randint(5, 20)):
            batch.append({"id": uuid.uuid4().hex[:12], "datetime": datetime.now().isoformat(timespec="seconds"),
                          "store": random.choice(STORES),
                          "lines": [{"barcode": random.choice(BARCODES), "qty": random.randint(1, 15)}
                                    for _ in range(random.randint(1, 3))]})
        self.client.post("/api/onec/receipts", json={"receipts": batch}, headers={"X-API-Key": "1c-demo-key"})
