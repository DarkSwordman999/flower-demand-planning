# -*- coding: utf-8 -*-
"""IDEF0 / IDEF3 в бланке BPwin: шапка с полем КОНТЕКСТ, узел декомпозиции, ссылки-объекты.

Подменяет рамку diagrams._frame; перед каждой диаграммой заполняется FRAME (author, project, context)."""
import diagrams as dg
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

DATE = "17.10.2026"
FRAME = {}          # заполняется перед каждой диаграммой: author, project, context


def _context(ax, x0, y0, w, h, ctx):
    """Мини-схема родительской диаграммы; декомпозируемый блок закрашен чёрным."""
    if ctx is None:
        ax.text(x0 + w / 2, y0 + h / 2, "ВЕРХ", ha="center", va="center", fontsize=8, weight="bold")
        return
    rects, hi = ctx
    xs = [r[0] for r in rects] + [r[0] + r[2] for r in rects]
    ys = [r[1] for r in rects] + [r[1] + r[3] for r in rects]
    sx = (w * 0.86) / max(max(xs) - min(xs), 1e-6)
    sy = (h * 0.80) / max(max(ys) - min(ys), 1e-6)
    s = min(sx, sy, (w * 0.3) / max(max(xs) - min(xs), 1e-6) if len(rects) == 1 else 1e9, (h * 0.55) / max(max(ys) - min(ys), 1e-6) if len(rects) == 1 else 1e9)
    ox = x0 + (w - (max(xs) - min(xs)) * s) / 2
    oy = y0 + (h - (max(ys) - min(ys)) * s) / 2
    for k, (rx, ry, rw, rh) in enumerate(rects):
        ax.add_patch(Rectangle((ox + (rx - min(xs)) * s, oy + (ry - min(ys)) * s), rw * s, rh * s,
                               fc="black" if k == hi else "white", ec="black", lw=0.6))


def frame(ax, W, H, node, title, number, author="", project=""):
    f = FRAME
    author, project = f.get("author", author), f.get("project", project)
    top, hh = H + 0.6, 1.25
    T = top + hh
    ax.add_patch(Rectangle((0, -1.2), W, T + 1.2, fill=False, lw=1.2))
    ax.plot([0, W], [top, top], color="black", lw=0.8)
    ex = max(W - 16.0, 0)
    widths = [1.9, 4.6 + ex * 0.45, 2.2 + ex * 0.05, 2.9 + ex * 0.15, 1.3 + ex * 0.05, 0.9 + ex * 0.05]
    cols, acc = [0], 0
    for wd in widths:
        acc += wd
        cols.append(acc / W)
    cols.append(1.0)
    for c in cols[1:-1]:
        ax.plot([W * c, W * c], [top, T], color="black", lw=0.8)
    fs = 6.2
    ax.text(W * cols[0] + 0.1, T - 0.12, "ИСПОЛЬЗУЕТСЯ\nВ:", fontsize=fs - 0.6, va="top")
    x = W * cols[1] + 0.1
    ax.text(x, T - 0.12, f"АВТОР:  {author}", fontsize=fs, va="top")
    ax.text(x, T - 0.42, f"ПРОЕКТ:  {project}", fontsize=fs, va="top")
    ax.text(x, top + 0.12, "ПРИМЕЧАНИЯ:  1  2  3  4  5  6  7  8  9  10", fontsize=fs - 0.4, va="bottom")
    x = W * cols[2] + 0.1
    ax.text(x, T - 0.12, f"ДАТА:  {DATE}", fontsize=fs, va="top")
    ax.text(x, T - 0.42, f"РЕД.:   {DATE}", fontsize=fs, va="top")
    # статус
    xa, xb = W * cols[3], W * cols[4]
    rows = ["РАБОЧАЯ ВЕРСИЯ", "ЧЕРНОВИК", "РЕКОМЕНДОВАНО", "ПУБЛИКАЦИЯ"]
    rh = hh / 4
    for k, r in enumerate(rows):
        y = T - (k + 1) * rh
        if k:
            ax.plot([xa, xb], [y + rh, y + rh], color="black", lw=0.6)
        ax.add_patch(Rectangle((xa, y), 0.22, rh, fc="black" if k == 0 else "white", ec="black", lw=0.6))
        ax.text(xa + 0.32, y + rh / 2, r, fontsize=fs - 0.5, va="center")
    ax.plot([xa + 0.22, xa + 0.22], [top, T], color="black", lw=0.6)
    ax.text(W * cols[4] + 0.08, T - 0.12, "ЧИТАТЕЛЬ", fontsize=fs - 0.5, va="top")
    ax.text(W * cols[5] + 0.08, T - 0.12, "ДАТА", fontsize=fs - 0.5, va="top")
    ax.text(W * cols[6] + 0.08, T - 0.12, "КОНТЕКСТ:", fontsize=fs - 0.5, va="top")
    _context(ax, W * cols[6] + 0.1, top + 0.08, W * (1 - cols[6]) - 0.2, hh - 0.38, f.get("context"))
    # подвал
    ax.plot([0, W], [-0.5, -0.5], color="black", lw=0.8)
    ax.plot([W * 0.16, W * 0.16], [-1.2, -0.5], color="black", lw=0.8)
    ax.plot([W * 0.84, W * 0.84], [-1.2, -0.5], color="black", lw=0.8)
    ax.text(0.15, -0.6, "УЗЕЛ:", fontsize=6.5, va="top")
    ax.text(W * 0.08, -0.92, node, fontsize=11, ha="center", va="center", weight="bold")
    ax.text(W * 0.16 + 0.15, -0.6, "НАЗВАНИЕ:", fontsize=6.5, va="top")
    ax.text(W * 0.5, -0.9, dg.wrap(title, 95), fontsize=10, ha="center", va="center", weight="bold")
    ax.text(W * 0.84 + 0.15, -0.6, "НОМЕР:", fontsize=6.5, va="top")
    ax.text(W * 0.92, -0.92, number, fontsize=10, ha="center", va="center")
    ax.set_ylim(-1.3, T + 0.1)


dg._frame = frame


def _diag(ax, x, y, s=0.32):
    """Диагональная черта в левом верхнем углу — работа не декомпозирована."""
    ax.plot([x, x + s], [y - s, y], color="black", lw=0.9, zorder=5)


# --------------------------------------------------------------------------- IDEF0
def idef0(spec, out_png, decomposed=()):
    """Обёртка над исходной функцией + диагональ у недекомпозированных блоков."""
    orig_add = None
    blocks = spec["blocks"]
    # перехватываем отрисовку блоков, чтобы поставить отметку
    import matplotlib.axes
    real_add_patch = matplotlib.axes.Axes.add_patch

    def add_patch(self, p, *a, **k):
        r = real_add_patch(self, p, *a, **k)
        if isinstance(p, Rectangle) and p.get_linewidth() == 1.4 and p.get_zorder() == 3:
            i = add_patch.n
            add_patch.n += 1
            if i < len(blocks) and blocks[i]["id"] not in decomposed:
                x, y = p.get_xy()
                _diag(self, x, y + p.get_height())
        return r
    add_patch.n = 0
    matplotlib.axes.Axes.add_patch = add_patch
    try:
        return dg.idef0(spec, out_png)
    finally:
        matplotlib.axes.Axes.add_patch = real_add_patch


def a0_context(spec, hi_id):
    """Прямоугольники блоков диаграммы A0 (лесенка) для поля КОНТЕКСТ."""
    n = len(spec["blocks"])
    rects = [(k * 3.1, -k * 1.95, 2.3, 1.45) for k in range(n)]
    hi = [b["id"] for b in spec["blocks"]].index(hi_id)
    return rects, hi


def i3_context(spec, hi_num):
    rects, hi = [], None
    for n in spec["nodes"]:
        if n["kind"] == "uow":
            if n["num"] == hi_num:
                hi = len(rects)
            rects.append((n["x"] * 3.1, -n["y"] * 1.9, 2.4, 1.3))
        else:
            rects.append((n["x"] * 3.1 + 0.9, -n["y"] * 1.9 + 0.2, 0.6, 0.9))
    return rects, hi


# --------------------------------------------------------------------------- IDEF3
def idef3(spec, out_png, node, title, number, refs=(), decomposed=()):
    """refs: [{"text", "x", "y", "to"/"frm": id узла}] — объекты-ссылки (входы/выходы родительского блока)."""
    allpts = [(n["x"], n["y"]) for n in spec["nodes"]] + [(r["x"], r["y"]) for r in refs]
    sx, sy = 3.1, 1.9
    xmin, xmax = min(p[0] for p in allpts), max(p[0] for p in allpts)
    ymin, ymax = min(p[1] for p in allpts), max(p[1] for p in allpts)
    W = max((xmax - xmin) * sx + 3.4, 16.0)
    H = (ymax - ymin) * sy + 2.4
    offx = (W - ((xmax - xmin) * sx + 3.4)) / 2

    def c(x, y):
        return ((x - xmin) * sx + 1.7 + offx, (ymax - y) * sy + 1.2)

    fig, ax = plt.subplots(figsize=(W * 0.62, (H + 3.1) * 0.62))
    ax.axis("off")
    ax.set_aspect("equal")
    ax.set_xlim(-0.1, W + 0.1)
    frame(ax, W, H, node, title, number)

    bw, bh, jr = 2.4, 1.5, 0.34
    geo = {}
    for n in spec["nodes"]:
        cx, cy = c(n["x"], n["y"])
        if n["kind"] == "uow":
            x0, y0 = cx - bw / 2, cy - bh / 2
            ax.add_patch(Rectangle((x0 + 0.06, y0 - 0.06), bw, bh, fc="#9a9a9a", ec="none", zorder=2))
            ax.add_patch(Rectangle((x0, y0), bw, bh, fc="white", ec="black", lw=1.3, zorder=3))
            ax.text(cx, cy + 0.08, dg.wrap(n["name"], dg._chars(bw - 0.5, 7.8)), ha="center", va="center",
                    fontsize=7.8, zorder=4, linespacing=1.05)
            ax.text(x0 + 0.34, y0 + bh - 0.05, "0р.", fontsize=5.5, va="top", zorder=4)
            ax.plot([x0, x0 + bw], [y0 + 0.28, y0 + 0.28], color="black", lw=0.8, zorder=4)
            ax.plot([x0 + 0.66, x0 + 0.66], [y0, y0 + 0.28], color="black", lw=0.8, zorder=4)
            ax.plot([x0 + 1.55, x0 + 1.55], [y0, y0 + 0.28], color="black", lw=0.8, zorder=4)
            ax.text(x0 + 0.33, y0 + 0.14, n["num"], ha="center", va="center", fontsize=7, zorder=5)
            if n["num"] not in decomposed:
                _diag(ax, x0, y0 + bh, 0.28)
            geo[n["id"]] = (cx, cy, bw / 2, bh / 2)
        else:
            sym = {"and": "&", "or": "O", "xor": "X"}[n["kind"]]
            ax.add_patch(Rectangle((cx - jr, cy - jr * 1.3), 2 * jr, 2.6 * jr, fc="white", ec="black", lw=1.3, zorder=3))
            ax.plot([cx - jr * 0.55] * 2, [cy - jr * 1.3, cy + jr * 1.3], color="black", lw=0.8, zorder=4)
            ax.text(cx + 0.08, cy, sym, ha="center", va="center", fontsize=11, weight="bold", zorder=4)
            ax.text(cx + jr + 0.05, cy - jr * 1.3 - 0.05, n["num"], ha="left", va="top", fontsize=7.5, weight="bold")
            geo[n["id"]] = (cx, cy, jr, jr * 1.3)

    def arrow(pts, ls="-"):
        xs_, ys_ = zip(*pts)
        ax.plot(xs_, ys_, color="black", lw=1.0, ls=ls, zorder=1)
        ax.annotate("", xy=pts[-1], xytext=pts[-2],
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.0, mutation_scale=9, shrinkA=0, shrinkB=0))

    nodes = {n["id"]: n for n in spec["nodes"]}
    for l in spec["links"]:
        a, b = geo[l[0]], geo[l[1]]
        ax0, ay0 = a[0] + a[2], a[1]
        bx0, by0 = b[0] - b[2], b[1]
        if abs(ay0 - by0) < 1e-6:
            pts = [(ax0, ay0), (bx0, by0)]
        elif nodes[l[0]]["kind"] != "uow":
            pts = [(a[0], a[1] + (a[3] if by0 > ay0 else -a[3])), (a[0], by0), (bx0, by0)]
        elif nodes[l[1]]["kind"] != "uow":
            pts = [(ax0, ay0), (b[0], ay0), (b[0], b[1] + (b[3] if ay0 > by0 else -b[3]))]
        else:
            mx = (ax0 + bx0) / 2
            pts = [(ax0, ay0), (mx, ay0), (mx, by0), (bx0, by0)]
        arrow(pts)
        if len(l) > 2:
            mx = (pts[-2][0] + pts[-1][0]) / 2
            ax.text(mx, pts[-1][1] + 0.08, dg.wrap(l[2], 16), fontsize=7, ha="center", va="bottom")

    # объекты-ссылки: входы/выходы декомпозируемого блока (пунктир)
    rw, rh = 2.3, 0.75
    for r in refs:
        cx, cy = c(r["x"], r["y"])
        ax.add_patch(Rectangle((cx - rw / 2 + 0.05, cy - rh / 2 - 0.05), rw, rh, fc="#9a9a9a", ec="none", zorder=2))
        ax.add_patch(Rectangle((cx - rw / 2, cy - rh / 2), rw, rh, fc="white", ec="black", lw=0.9, zorder=3))
        ax.text(cx, cy, dg.wrap(r["text"], dg._chars(rw - 0.5, 7.6)), ha="center", va="center", fontsize=7.6,
                zorder=4, linespacing=1.05)
        R = (cx, cy, rw / 2, rh / 2)
        g = geo[r.get("to") or r["frm"]]
        g = (g[0] + r.get("off", 0), g[1], g[2], g[3])
        src, dst = (R, g) if "to" in r else (g, R)
        pts = _route(src, dst, r.get("via"))
        arrow(pts, ls=(0, (4, 3)))

    fig.savefig(out_png, dpi=dg.DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def _route(a, b, via=None):
    """Ортогональный путь из a в b (центры и полуразмеры)."""
    ax_, ay_, aw, ah = a
    bx_, by_, bw, bh = b
    if via == "h" or (via is None and abs(ay_ - by_) < 0.05):
        if bx_ > ax_:
            return [(ax_ + aw, ay_), (bx_ - bw, ay_)] if abs(ay_ - by_) < 0.05 else \
                [(ax_ + aw, ay_), (bx_, ay_), (bx_, by_ + (bh if ay_ > by_ else -bh))]
        return [(ax_ - aw, ay_), (bx_ + bw, ay_)]
    if via == "hv":  # горизонтально от a, затем вертикально в b
        sx_ = ax_ + aw if bx_ > ax_ else ax_ - aw
        return [(sx_, ay_), (bx_, ay_), (bx_, by_ + (bh if ay_ > by_ else -bh))]
    if via == "vh":  # вертикально от a, затем горизонтально в b
        sy_ = ay_ - ah if by_ < ay_ else ay_ + ah
        ex = bx_ - bw if bx_ > ax_ else bx_ + bw
        return [(ax_, sy_), (ax_, by_), (ex, by_)]
    # вертикально
    sy_ = ay_ - ah if by_ < ay_ else ay_ + ah
    return [(ax_, sy_), (ax_, by_ + (bh if ay_ > by_ else -bh))] if abs(ax_ - bx_) < 0.05 else \
        [(ax_, sy_), (ax_, (sy_ + by_) / 2), (bx_, (sy_ + by_) / 2), (bx_, by_ + (bh if ay_ > by_ else -bh))]
