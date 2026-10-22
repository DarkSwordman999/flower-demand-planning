"""Командная строка: floraplan init-db | run | create-user | …"""
import argparse
import sys


def cmd_init_db(args) -> None:
    from . import db, migrate
    from .bootstrap import ensure_base
    migrate.upgrade()
    with db.session() as s:
        for line in ensure_base(s, args.admin_password):
            print("  ·", line)
    print("БД готова:", _safe_url())


def cmd_run(args) -> None:
    import uvicorn
    cmd_init_db(argparse.Namespace(admin_password="admin"))
    print(f"ФлораПлан: http://{args.host}:{args.port}/   (API: /api/docs)")
    uvicorn.run("floraplan.main:app", host=args.host, port=args.port, log_level="info")


def cmd_create_user(args) -> None:
    from . import db
    from .models import ROLES, User
    from .security import hash_password
    if args.role not in ROLES:
        sys.exit(f"роль: одна из {', '.join(ROLES)}")
    with db.session() as s:
        if s.query(User).filter(User.login == args.login).first():
            sys.exit("такой логин уже есть")
        s.add(User(login=args.login, full_name=args.name or args.login, role=args.role,
                   password_hash=hash_password(args.password)))
        s.commit()
    print("создан", args.login)


def cmd_demo(args) -> None:
    import time
    from . import db, migrate
    from .demo import DEMO_PASSWORD, generate, reset
    from .services import forecasting
    t0 = time.time()
    migrate.upgrade()
    with db.session() as s:
        if args.reset:
            reset(s)
        generate(s, log=lambda m: print("  ·", m, flush=True))
        from datetime import date, timedelta
        for back in (28, 14):   # прошлые расчёты — как будто планировщик уже работал (для отчёта о точности)
            forecasting.run(s, base=date.today() - timedelta(days=back), trigger="schedule")
        r = forecasting.run(s, trigger="manual")
        print("  · прогноз:", r.message, flush=True)
        m = forecasting.published_model(s)
        ev = forecasting.evaluate(s, m)
        m.wape, m.bias = ev["wape"], ev["bias"]
        m.details = {"candidate": {"wape": ev["wape"], "bias": ev["bias"],
                                   "period": [str(ev["period"][0]), str(ev["period"][1])],
                                   "groups": {str(k): v for k, v in ev["groups"].items()}}}
        s.commit()
        print(f"  · WAPE недельного прогноза по группам: {ev['wape'] * 100:.1f} %", flush=True)
    print(f"Демо-данные загружены за {time.time() - t0:.0f} с. Пользователи: admin/admin и "
          f"director, buyer, storekeeper, florist, shop, analyst — пароль «{DEMO_PASSWORD}»")


def cmd_scheduler(args) -> None:
    from .scheduler import run_forever
    run_forever()


def cmd_backup(args) -> None:
    from .services import backup
    print("резервная копия:", backup.make())


def cmd_forecast(args) -> None:
    from . import db
    from .services import forecasting
    with db.session() as s:
        r = forecasting.run(s, trigger="manual")
        print(r.status, r.message)


def _safe_url() -> str:
    from .config import get_settings
    url = get_settings().db_url
    if "@" in url:  # пароль в URL не печатаем
        head, tail = url.split("@", 1)
        url = head.split("://")[0] + "://***@" + tail
    return url


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="floraplan", description="ФлораПлан — планирование закупок и продаж цветов")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init-db", help="создать или обновить схему БД, завести администратора")
    a.add_argument("--admin-password", default="admin")
    a.set_defaults(func=cmd_init_db)

    a = sub.add_parser("run", help="запустить веб-сервер")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8000)
    a.set_defaults(func=cmd_run)

    a = sub.add_parser("create-user", help="добавить пользователя")
    a.add_argument("login")
    a.add_argument("password")
    a.add_argument("role")
    a.add_argument("--name", default="")
    a.set_defaults(func=cmd_create_user)

    a = sub.add_parser("demo", help="загрузить демонстрационные данные (в пустую БД)")
    a.add_argument("--reset", action="store_true", help="сначала удалить все данные")
    a.set_defaults(func=cmd_demo)
    sub.add_parser("scheduler", help="планировщик задач отдельным процессом").set_defaults(func=cmd_scheduler)
    sub.add_parser("backup", help="резервная копия БД").set_defaults(func=cmd_backup)
    sub.add_parser("forecast", help="рассчитать прогноз спроса").set_defaults(func=cmd_forecast)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
