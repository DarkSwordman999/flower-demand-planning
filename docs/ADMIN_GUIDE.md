# Руководство администратора ФлораПлан

## Варианты установки

### 1. Windows без установки (один компьютер или небольшая сеть)

Скачайте `FloraPlan-<версия>-windows-x64.zip` со страницы [Releases](https://github.com/DarkSwordman999/flower-demand-planning/releases), распакуйте и запустите `ФлораПлан.exe`. База — SQLite в папке `data` рядом с программой, планировщик задач работает внутри программы. Для доступа с других компьютеров и ТСД задайте `FLORAPLAN_HOST=0.0.0.0` (файл `.env` рядом с exe) и откройте порт в брандмауэре.

### 2. Сервер в Docker (ПР 7-8, диаграмма размещения)

```bash
git clone https://github.com/DarkSwordman999/flower-demand-planning.git
cd flower-demand-planning/deploy
cp .env.example .env        # задайте DB_PASSWORD, SECRET_KEY, ADMIN_PASSWORD, почту
docker compose up -d --build
docker compose exec api floraplan demo     # при необходимости — демо-данные
```

Сервисы: `db` (PostgreSQL 16), `api` (FastAPI), `scheduler` (задачи по расписанию), `web` (nginx + интерфейс, порт `HTTP_PORT`, по умолчанию 8080). Данные — тома `pgdata` и `floradata`. Для HTTPS (требование Б-1) поставьте перед `web` обратный прокси с сертификатом (nginx, Caddy, Traefik) или терминатор TLS провайдера.

### 3. Из исходников

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
cd ../frontend && npm ci && npm run build      # интерфейс → backend/floraplan/static
cd ../backend && floraplan demo && floraplan run --host 0.0.0.0
```

## Настройки (переменные окружения `FLORAPLAN_*` или файл `.env`)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/flora_db`; пусто — SQLite в `DATA_DIR` |
| `DATA_DIR` | каталог данных: БД SQLite, `backup`, `outbox`, `inbox_1c` |
| `SECRET_KEY` | ключ подписи токенов входа — обязательно смените |
| `TOKEN_HOURS` | срок действия входа, часов (12) |
| `SHOP_API_KEY`, `ONEC_API_KEY` | ключи интернет-магазина и «1С» (заголовок `X-API-Key`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | почта для заказов поставщикам |
| `SHOP_WEBHOOK_URL` | адрес сайта для выгрузки остатков и цен каждые 15 минут |
| `WEATHER_ENABLED`, `LATITUDE`, `LONGITUDE` | погодный сервис Open-Meteo (по умолчанию — Тула) |
| `SCHEDULER_ENABLED` | планировщик внутри веб-сервера (в Docker — `false`, работает сервис `scheduler`) |
| `TIMEZONE` | часовой пояс расписания (`Europe/Moscow`) |

Параметры работы (бюджет недели, пороги уценки и расхождений, 30 % для причины изменения заказа, горизонт и час расчёта прогноза, границы уровня обслуживания) меняет директор в интерфейсе: «Администрирование → Параметры».

## Пользователи и роли

«Администрирование → Пользователи» (только администратор): логин, ФИО, роль, салон (для продавца-флориста — его рабочая точка), пароль, блокировка. Из командной строки: `floraplan create-user <логин> <пароль> <роль>`; роли: `admin`, `director`, `buyer`, `storekeeper`, `florist`, `shop_manager`, `analyst`. Места хранения (склад, салоны, интернет-магазин) и причины списания заводит администратор в «Справочниках».

## Задачи по расписанию

| Задача | Когда |
|---|---|
| Прогноз спроса (С-6) | ежедневно в 03:00 (час — параметр «Час ежедневного расчёта») |
| Чеки «1С» из папки обмена (С-5) | ежечасно |
| Прогноз погоды | каждые 6 часов |
| Выгрузка остатков и цен на сайт (С-14) | каждые 15 минут, если задан `SHOP_WEBHOOK_URL` |
| Резервная копия (Н-1) | ежедневно в 02:00, хранятся 14 последних |

Результаты и ошибки — «Администрирование → Обмен и расписание».

## Резервное копирование и восстановление

Копии создаются автоматически и по кнопке («Администрирование → Резервные копии»), их можно скачать. SQLite — файл `floraplan-*.db`: для восстановления остановите программу и замените `data/floraplan.db`. PostgreSQL — `floraplan-*.dump` (нужен `pg_dump` в PATH): `pg_restore -c -d flora_db floraplan-....dump`.

## Обновление

Новая версия применяет изменения схемы БД сама при запуске (`floraplan init-db` — миграции Alembic). Перед обновлением сделайте резервную копию. Windows: замените файлы программы, папку `data` оставьте. Docker: `git pull && docker compose up -d --build`.

## Интеграция

Описание обмена с «1С:Розница», кассами и интернет-магазином — [INTEGRATION.md](INTEGRATION.md); интерактивная спецификация OpenAPI — `/api/docs`.
