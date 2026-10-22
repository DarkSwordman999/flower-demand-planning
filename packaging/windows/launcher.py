"""ФлораПлан для Windows: запуск без установки.

ФлораПлан.exe            — подготовить БД (data\\floraplan.db рядом с программой), запустить сервер, открыть браузер;
ФлораПлан.exe demo       — загрузить демонстрационные данные (в пустую БД);
ФлораПлан.exe <команда>  — любая команда floraplan (init-db, backup, create-user, …).
"""
import os
import socket
import sys
import threading
import time
import webbrowser


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _ask_demo() -> bool:
    from floraplan import db
    from floraplan.models import Product
    with db.session() as s:
        if s.query(Product).count() > 0:
            return False
    try:
        ans = input("База пуста. Загрузить демонстрационные данные (около 1–2 минут)? [Д/н]: ").strip().lower()
    except EOFError:
        return False
    return ans in ("", "д", "да", "y", "yes")


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    from floraplan.cli import main as cli
    args = sys.argv[1:]
    if args:
        cli(args)
        return
    cli(["init-db"])
    if _ask_demo():
        cli(["demo"])
    port = int(os.environ.get("FLORAPLAN_PORT", "8000"))
    while not _port_free(port):
        port += 1
    url = f"http://127.0.0.1:{port}/"
    print(f"\nФлораПлан работает: {url}\nНе закрывайте это окно, пока работаете с программой.\n")
    if not os.environ.get("FLORAPLAN_NO_BROWSER"):
        threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(url)), daemon=True).start()
    import uvicorn
    from floraplan.main import app
    uvicorn.run(app, host=os.environ.get("FLORAPLAN_HOST", "127.0.0.1"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
