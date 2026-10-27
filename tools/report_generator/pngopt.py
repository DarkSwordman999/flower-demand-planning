"""Сжатие PNG-диаграмм без видимой потери качества.

Диаграммы почти одноцветные, поэтому сначала пробуется палитра из 256 цветов. Она принимается, только если
ни один пиксель не изменился больше чем на MAX_DIFF из 255 и заметно изменившихся пикселей не больше
MAX_SHARE. Иначе (снимки экранов с градиентами) файл сжимается без потерь. Затем, если установлен
pyoxipng, файл дожимается без потерь.

Генератор вызывает ensure() для каждой картинки перед вставкой в документ. Вручную:
    python pngopt.py <папка или файл> ...
"""
import hashlib
import io
import json
import os
import sys

from PIL import Image

try:
    import numpy as np
except ImportError:   # без numpy проверка отличий невозможна — только сжатие без потерь
    np = None
try:
    import oxipng
except ImportError:
    oxipng = None

MAX_DIFF = 24        # наибольшее допустимое отличие канала пикселя, из 255
MAX_SHARE = 0.01     # доля пикселей, отличающихся больше чем на 8
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pngopt.json")
_cache = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(_cache, f)
    except OSError:
        pass


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _palette_ok(src: Image.Image, pal: Image.Image) -> bool:
    if np is None:
        return False
    a = np.asarray(src.convert("RGBA"), np.int16)
    b = np.asarray(pal.convert("RGBA"), np.int16)
    d = np.abs(a - b).max(axis=2)
    return int(d.max()) <= MAX_DIFF and float((d > 8).mean()) <= MAX_SHARE


def compress(data: bytes) -> bytes:
    """Сжатый PNG; если выиграть не удалось — исходные байты."""
    im = Image.open(io.BytesIO(data))
    im.load()
    best = data
    if im.mode != "P":
        rgba = im.convert("RGBA")
        pal = rgba.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        candidate = _png(pal) if _palette_ok(rgba, pal) else _png(im)
    else:
        candidate = _png(im)
    if len(candidate) < len(best):
        best = candidate
    if oxipng is not None:
        best = min(best, oxipng.optimize_from_memory(best, level=2, strip=oxipng.StripChunks.safe()), key=len)
    return best


def ensure(path: str) -> None:
    """Сжать файл на месте, если он ещё не сжат (уже сжатые запоминаются по хэшу)."""
    cache = _load_cache()
    with open(path, "rb") as f:
        data = f.read()
    h = hashlib.sha1(data).hexdigest()
    if cache.get(h):
        return
    out = compress(data)
    if len(out) < len(data):
        with open(path, "wb") as f:
            f.write(out)
        h = hashlib.sha1(out).hexdigest()
    cache[h] = 1
    _save_cache()


def main(paths: list[str]) -> None:
    before = after = 0
    for p in paths:
        files = [p] if os.path.isfile(p) else [os.path.join(d, n) for d, _, ns in os.walk(p) for n in ns
                                                if n.lower().endswith(".png")]
        for f in files:
            before += os.path.getsize(f)
            ensure(f)
            after += os.path.getsize(f)
    if before:
        print(f"{before / 1e6:.1f} МБ -> {after / 1e6:.1f} МБ ({after / before * 100:.0f} %)")


if __name__ == "__main__":
    main(sys.argv[1:] or [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "diagrams")])
