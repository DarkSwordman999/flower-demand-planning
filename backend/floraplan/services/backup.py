"""Резервное копирование БД (Н-1): SQLite — встроенным backup API, PostgreSQL — pg_dump."""
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

from ..config import get_settings
from ..errors import DomainError

KEEP = 14


def make() -> Path:
    s = get_settings()
    s.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    url = s.db_url
    if url.startswith("sqlite"):
        src = url.split("///", 1)[1]
        dst = s.backup_dir / f"floraplan-{stamp}.db"
        with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
            a.backup(b)
    else:
        exe = shutil.which("pg_dump")
        if exe is None:
            raise DomainError("pg_dump не найден: установите клиент PostgreSQL или используйте резервирование СУБД")
        u = urlparse(url.replace("postgresql+psycopg", "postgresql"))
        dst = s.backup_dir / f"floraplan-{stamp}.dump"
        env = dict(os.environ, PGPASSWORD=unquote(u.password or ""))
        cmd = [exe, "-Fc", "-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", unquote(u.username or ""),
               "-f", str(dst), u.path.lstrip("/")]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            raise DomainError(f"pg_dump: {r.stderr.strip()[:500]}")
    _rotate(s.backup_dir)
    return dst


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
