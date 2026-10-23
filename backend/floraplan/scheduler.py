"""Планировщик задач (ПР 7-8, компонент scheduler): прогноз в 03:00 (С-6), чеки «1С» ежечасно (С-5),
погода, выгрузка остатков на сайт (С-14), резервная копия (Н-1)."""
import logging
from datetime import datetime

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import appsettings, audit, db
from .config import get_settings

log = logging.getLogger("floraplan.scheduler")


def _job(name: str, mode: str = "immediate"):
    def wrap(fn):
        def run():
            s = db.session(mode)
            try:
                msg = fn(s)
                if msg:
                    audit.integration(s, "scheduler", f"{name}: {msg}")
                s.commit()
            except Exception as e:  # задача не должна ронять планировщик
                s.rollback()
                audit.integration(s, "scheduler", f"{name}: ошибка {e}", status="error")
                s.commit()
                log.exception(name)
            finally:
                s.close()
        run.__name__ = name
        return run
    return wrap


@_job("прогноз спроса", mode="deferred")
def job_forecast(s):
    from .services import forecasting
    r = forecasting.run(s, trigger="schedule")
    return f"{r.status}: {r.message}"


@_job("чеки 1С из папки обмена")
def job_onec(s):
    from .services import onec
    r = onec.import_folder(s)
    return f"файлов {r['files']}, чеков {r['created']}" if r["files"] else ""


@_job("погода")
def job_weather(s):
    from .services import weather
    return str(weather.fetch(s))


@_job("остатки на сайт")
def job_shop_push(s):
    url = get_settings().shop_webhook_url
    if not url:
        return ""
    from .services import shop
    data = {"stock": shop.stock(s), "prices": shop.prices(s)}
    r = httpx.post(url, json=data, timeout=20, headers={"X-API-Key": get_settings().shop_api_key})
    r.raise_for_status()
    return f"передано позиций {len(data['stock']['items'])}"


@_job("резервная копия")
def job_backup(s):
    from .services import backup
    return f"создана {backup.make().name}"


def _add_jobs(sched) -> None:
    with db.session() as s:
        hour = int(appsettings.get(s, "forecast_hour"))
    tz = get_settings().timezone
    sched.add_job(job_forecast, CronTrigger(hour=hour, minute=0, timezone=tz), id="forecast", coalesce=True,
                  misfire_grace_time=6 * 3600)
    sched.add_job(job_onec, IntervalTrigger(hours=1), id="onec", next_run_time=datetime.now())
    sched.add_job(job_weather, IntervalTrigger(hours=6), id="weather", next_run_time=datetime.now())
    sched.add_job(job_shop_push, IntervalTrigger(minutes=15), id="shop")
    sched.add_job(job_backup, CronTrigger(hour=2, minute=0, timezone=tz), id="backup", coalesce=True,
                  misfire_grace_time=6 * 3600)


def start(paused: bool = False) -> BackgroundScheduler:
    """Планировщик внутри веб-сервера (однопользовательская установка, Windows-версия)."""
    sched = BackgroundScheduler(timezone=get_settings().timezone)
    _add_jobs(sched)
    sched.start(paused=paused)
    return sched


def run_forever() -> None:
    """Отдельный процесс-планировщик (docker-compose, сервис scheduler)."""
    logging.basicConfig(level=logging.INFO)
    sched = BlockingScheduler(timezone=get_settings().timezone)
    _add_jobs(sched)
    log.info("планировщик запущен: %s", ", ".join(j.id for j in sched.get_jobs()))
    sched.start()
