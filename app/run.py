"""Запуск базовой редакции одной командой: python run.py (или двойной щелчок по run.bat).

При первом запуске создаёт окружение .venv и ставит Flask (из папки wheels, если она есть,
иначе из интернета), а если базы ещё нет — загружает демо-данные. Затем открывает браузер.
"""
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
VENV = HERE / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
URL = "http://127.0.0.1:5000/"


def run(*args):
    subprocess.run([str(a) for a in args], cwd=HERE, check=True)


def main():
    if sys.version_info < (3, 11):
        sys.exit("Нужен Python 3.11 или новее: https://www.python.org/downloads/")

    if not PYTHON.exists():
        print("Первый запуск: подготовка окружения...")
        run(sys.executable, "-m", "venv", VENV)
        wheels = HERE / "wheels"
        offline = ["--no-index", "--find-links", wheels] if wheels.is_dir() else []
        run(PYTHON, "-m", "pip", "install", "--quiet", *offline, "-r", HERE / "requirements.txt")

    if not (HERE / "floraplan.db").exists():
        run(PYTHON, "demo.py")

    print(f"ФлораПлан: {URL} (вход admin / admin). Чтобы остановить, закройте это окно.")
    threading.Timer(3, webbrowser.open, [URL]).start()
    run(PYTHON, "app.py")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        sys.exit("Не удалось запустить. Если это первый запуск, проверьте подключение к интернету "
                 "и удалите папку .venv перед повтором.")
    except KeyboardInterrupt:
        pass
