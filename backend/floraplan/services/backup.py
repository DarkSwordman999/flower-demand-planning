"""Резервное копирование и восстановление БД (Н-1): SQLite — встроенным backup API, PostgreSQL — pg_dump и pg_restore."""
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

from ..config import get_settings
from ..errors import DomainError

KEEP = 14


def _url() -> str:
    """Адрес подключённой БД (тот же, с которым работает программа)."""
    from .. import db
    return db.engine().url.render_as_string(hide_password=False)


def _sqlite_path(url: str) -> str:
    return url.split("///", 1)[1]


def _pg(tool: str, url: str, args: list[str]) -> None:
    exe = shutil.which(tool)
    if exe is None:
        raise DomainError(f"{tool} не найден: установите клиент PostgreSQL или используйте резервирование СУБД")
    u = urlparse(url.replace("postgresql+psycopg", "postgresql"))
    env = dict(os.environ, PGPASSWORD=unquote(u.password or ""))
    cmd = [exe, "-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", unquote(u.username or ""),
           "-d", u.path.lstrip("/"), *args]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=4 * 3600)   # Н-1: не более 4 часов
    if r.returncode != 0:
        raise DomainError(f"{tool}: {r.stderr.strip()[:500]}")


def make(suffix: str = "") -> Path:
    s = get_settings()
    s.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + suffix
    url = _url()
    ext = ".db" if url.startswith("sqlite") else ".dump"
    dst, n = s.backup_dir / f"floraplan-{stamp}{ext}", 1
    while dst.exists():                     # две копии в одну секунду не перезаписывают друг друга
        n += 1
        dst = s.backup_dir / f"floraplan-{stamp}-{n}{ext}"
    if url.startswith("sqlite"):
        _sqlite_copy(_sqlite_path(url), dst)
    else:
        _pg("pg_dump", url, ["-Fc", "-f", str(dst)])
    _rotate(s.backup_dir)
    return dst


def resolve(name_or_path: str) -> Path:
    """Имя копии из папки backup или путь к файлу."""
    p = Path(name_or_path)
    if p.is_file():
        return p.resolve()
    return path_of(name_or_path)


def restore(src: Path) -> Path:
    """Восстановление БД из копии (Н-1). Программа и планировщик на это время должны быть остановлены.
    Перед заменой текущее состояние сохраняется копией «…-before-restore»; после — схема обновляется
    миграциями до текущей версии (копия могла быть сделана старой версией программы). Возвращает путь
    страховочной копии."""
    from .. import db, migrate
    url = _url()
    if url.startswith("sqlite"):
        _check_sqlite(src)
        safety = make("-before-restore")
        db.engine().dispose()
        _sqlite_copy(src, _sqlite_path(url))
    else:
        if src.suffix != ".dump":
            raise DomainError("Для PostgreSQL нужна копия в формате pg_dump (*.dump)")
        safety = make("-before-restore")
        db.engine().dispose()
        _pg("pg_restore", url, ["--clean", "--if-exists", "--no-owner", "-j", "4", str(src)])
    migrate.upgrade(url)
    db.engine().dispose()
    return safety


def _sqlite_copy(src, dst) -> None:
    with closing(sqlite3.connect(src)) as a, closing(sqlite3.connect(dst)) as b:
        a.backup(b)


def _check_sqlite(src: Path) -> None:
    with open(src, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise DomainError("Файл не является базой SQLite")
    with closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as c:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DomainError("Копия повреждена (integrity_check)")
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone():
            raise DomainError("Файл не является базой ФлораПлан")


def _rotate(folder: Path) -> None:
    files = sorted(folder.glob("floraplan-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[KEEP:]:
        f.unlink(missing_ok=True)


def listing() -> list[dict]:
    s = get_settings()
    s.ensure_dirs()
    return [{"name": f.name, "size": f.stat().st_size, "created": datetime.fromtimestamp(f.stat().st_mtime)}
            for f in sorted(s.backup_dir.glob("floraplan-*"), key=lambda p: p.stat().st_mtime, reverse=True)]


def path_of(name: str) -> Path:
    s = get_settings()
    p = (s.backup_dir / name).resolve()
    if p.parent != s.backup_dir.resolve() or not p.is_file():
        raise DomainError("Копия не найдена", status=404)
    return p
