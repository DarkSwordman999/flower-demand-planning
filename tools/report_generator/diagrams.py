# -*- coding: utf-8 -*-
"""Отрисовка диаграмм: IDEF0, IDEF3, VORD, сетевой график, диаграммы Ганта; запуск PlantUML."""
import os, subprocess, textwrap, datetime as dt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Ellipse, Circle, FancyArrowPatch

plt.rcParams["font.family"] = "Arial"
plt.rcParams["font.size"] = 9

_JDK = r"C:\Program Files\Microsoft\jdk-11.0.12.7-hotspot\bin\java.exe"
JAVA = os.environ.get("JAVA") or (_JDK if os.path.exists(_JDK) else "java")  # нужна Java 11+
PLANTUML = os.path.join(os.path.dirname(__file__), "plantuml.jar")
DPI = 200


def wrap(text, width):
    out = []
    for part in text.split("\n"):
        out.extend(textwrap.wrap(part, width, break_long_words=False, break_on_hyphens=True) or [""])
    return "\n".join(out)


def plantuml(src, out_png):
    """src — текст диаграммы без @startuml/@enduml."""
    puml = os.path.splitext(out_png)[0] + ".puml"
    body = ("@startuml\n!pragma layout smetana\nskinparam dpi 150\nskinparam defaultFontName Arial\n"
            "skinparam shadowing false\nskinparam monochrome true\n" + src.strip() + "\n@enduml\n")
    with open(puml, "w", encoding="utf-8") as f:
        f.write(body)
    r = subprocess.run([JAVA, "-jar", PLANTUML, "-charset", "UTF-8", "-tpng", puml],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError(f"PlantUML error {puml}: {r.stdout} {r.stderr}")
    return out_png


# =========================================================================== IDEF0
def _arrow(ax, pts, label=None, label_pos=None, ha="left", va="bottom", lw=1.0, fs=7.5):
    xs, ys = zip(*pts)
    ax.plot(xs[:-1] + (xs[-1],), ys, color="black", lw=lw, solid_joinstyle="miter")
    ax.annotate("", xy=pts[-1], xytext=pts[-2],
                arrowprops=dict(arrowstyle="-|>", color="black", lw=lw, mutation_scale=9,
                                shrinkA=0, shrinkB=0))
    if label:
        ax.text(*label_pos, label, ha=ha, va=va, fontsize=fs, linespacing=1.0,
                bbox=dict(fc="white", ec="none", pad=0.6))


def _frame(ax, W, H, node, title, number, author="", project=""):
    # бланк IDEF0: заголовок сверху, «подвал» с узлом/названием/номером
    ax.add_patch(Rectangle((0, -1.2), W, H + 2.4, fill=False, lw=1.2))
    ax.plot([0, W], [H + 0.6, H + 0.6], color="black", lw=0.8)
    ax.text(0.15, H + 1.0, f"АВТОР: {author}", fontsize=7, va="center")
    ax.text(0.15, H + 0.78, f"ПРОЕКТ: {project}", fontsize=7, va="center")
    ax.text(W * 0.62, H + 0.9, "РАБОЧАЯ ВЕРСИЯ   ЧЕРНОВИК   РЕКОМЕНДОВАНО   ПУБЛИКАЦИЯ",
            fontsize=6, va="center", color="black")
    ax.plot([0, W], [-0.5, -0.5], color="black", lw=0.8)
    ax.plot([W * 0.16, W * 0.16], [-1.2, -0.5], color="black", lw=0.8)
    ax.plot([W * 0.84, W * 0.84], [-1.2, -0.5], color="black", lw=0.8)
    ax.text(0.15, -0.65, "УЗЕЛ:", fontsize=6.5, va="top")
    ax.text(W * 0.08, -0.95, node, fontsize=10, ha="center", va="center", weight="bold")
    ax.text(W * 0.16 + 0.15, -0.65, "НАЗВАНИЕ:", fontsize=6.5, va="top")
    ax.text(W * 0.5, -0.92, wrap(title, 95), fontsize=9, ha="center", va="center", weight="bold")
    ax.text(W * 0.84 + 0.15, -0.65, "НОМЕР:", fontsize=6.5, va="top")
    ax.text(W * 0.92, -0.95, number, fontsize=9, ha="center", va="center")


def _chars(width_units, fs):
    # 1 ед. = 0.62 дюйма = 44.6 pt; средняя ширина символа ≈ 0.55·fs
    return max(8, int(width_units * 44.6 / (0.63 * fs)))


def idef0(spec, out_png):
    """spec = {
      node, title, number, project,
      blocks: [{id, name, num}],         # по диагонали
      ext: [{"to": id, "side": "I"/"C"/"M"/"O", "label": str}],  # внешние стрелки (O — из блока к правой рамке)
      links: [{"from": id, "to": id, "side": "I"/"C", "label": str}]  # выход блока from -> вход/управление блока to
    }"""
    blocks = spec["blocks"]
    n = len(blocks)
    context = n == 1
    W = 16.0
    if not context:
        W = max(16.0, 3.0 + 2.3 + 2.3 + (n - 1) * (2.3 + 0.8))
    if context:
        bw, bh = 9.0, 2.6
        H = 8.0
        pos = {blocks[0]["id"]: (W / 2 - bw / 2 + 0.3, H / 2 - bh / 2)}
    else:
        bw, bh = 2.3, 1.45
        L = 3.0
        dx = (W - L - 2.3 - bw) / max(n - 1, 1)
        dy = 1.95
        H = 2.6 + (n - 1) * dy + bh + 1.8
        pos = {}
        for k, b in enumerate(blocks):
            pos[b["id"]] = (L + k * dx, H - 2.3 - bh - k * dy)
    fig, ax = plt.subplots(figsize=(W * 0.62, (H + 2.6) * 0.62))
    plt.rcParams["font.size"] = 9
    ax.set_xlim(-0.1, W + 0.1)
    ax.set_ylim(-1.3, H + 1.3)
    ax.axis("off")
    ax.set_aspect("equal")
    _frame(ax, W, H, spec["node"], spec["title"], spec["number"],
           spec.get("author", ""), spec.get("project", ""))

    ports = {b["id"]: {"I": [], "C": [], "M": [], "O": []} for b in blocks}
    for e in spec.get("ext", []):
        ports[e["to"]][e["side"]].append(("ext", e))
    for l in spec.get("links", []):
        ports[l["from"]]["O"].append(("link", l))
        ports[l["to"]][l["side"]].append(("link", l))

    def port_xy(bid, side, item):
        x, y = pos[bid]
        lst = ports[bid][side]
        k = lst.index(item)
        m = len(lst)
        if side in ("I", "O"):
            yy = y + bh - (k + 1) * bh / (m + 1)
            return (x if side == "I" else x + bw, yy)
        xx = x + (k + 1) * bw / (m + 1)
        return (xx, y + bh if side == "C" else y)

    bfs = 10.5 if context else 8.6
    for b in blocks:
        x, y = pos[b["id"]]
        ax.add_patch(Rectangle((x, y), bw, bh, fc="white", ec="black", lw=1.4, zorder=3))
        ax.text(x + bw / 2, y + bh / 2 + 0.08, wrap(b["name"], _chars(bw - 0.3, bfs)),
                ha="center", va="center", fontsize=bfs, zorder=4, linespacing=1.1)
        ax.text(x + bw - 0.08, y + 0.08, b.get("num", ""), ha="right", va="bottom",
                fontsize=8, weight="bold", zorder=4)

    top, bot, left, right = H + 0.6, -0.5, 0, W
    fs = 7.8 if context else 7.6
    vx = {"C": sorted(port_xy(e["to"], "C", ("ext", e))[0] for e in spec.get("ext", []) if e["side"] == "C"),
          "M": sorted(port_xy(e["to"], "M", ("ext", e))[0] for e in spec.get("ext", []) if e["side"] == "M")}

    def avail(side, px):
        nxt = [x for x in vx[side] if x > px + 1e-6]
        return (nxt[0] - px - 0.25) if nxt else min(right - px - 0.4, 3.2)
    for e in spec.get("ext", []):
        item = ("ext", e)
        side = e["side"]
        px, py = port_xy(e["to"], side, item)
        if side == "I":
            lab = wrap(e["label"], _chars(px - left - 0.25, fs))
            _arrow(ax, [(left, py), (px, py)], lab, (left + 0.1, py + 0.05), fs=fs)
        elif side in ("C", "M"):
            lst = ports[e["to"]][side]
            m = len(lst)
            av = avail(side, px)
            need = len(e["label"]) * 0.6 * fs / 44.6
            left_side = av < min(need, 2.0) and lst.index(item) == 0 and m > 1
            if left_side:
                prv = [x for x in vx[side] if x < px - 1e-6]
                avl = (px - prv[-1] - 0.25) if prv else 2.4
                lab = wrap(e["label"], _chars(min(avl, 2.6), fs))
                lx, ha = px - 0.07, "right"
            else:
                lab = wrap(e["label"], _chars(av, fs))
                lx, ha = px + 0.07, "left"
            if side == "C":
                _arrow(ax, [(px, top), (px, py)], lab, (lx, top - 0.12), va="top", ha=ha, fs=fs)
            else:
                _arrow(ax, [(px, bot), (px, py)], lab, (lx, bot + 0.1), va="bottom", ha=ha, fs=fs)
        elif side == "O":
            lab = wrap(e["label"], _chars(right - px - 0.75, fs))
            _arrow(ax, [(px, py), (right, py)], lab, (right - 0.1, py + 0.05), ha="right", fs=fs)

    order = {b["id"]: k for k, b in enumerate(blocks)}
    fb = 0
    for l in spec.get("links", []):
        item = ("link", l)
        sx, sy = port_xy(l["from"], "O", item)
        tx, ty = port_xy(l["to"], l["side"], item)
        forward = order[l["to"]] > order[l["from"]]
        if forward and l["side"] == "I":
            k = ports[l["from"]]["O"].index(item)
            mid = sx + 0.22 + 0.2 * k
            lab = wrap(l.get("label", ""), 16)
            if mid < tx - 0.15:
                pts = [(sx, sy), (mid, sy), (mid, ty), (tx, ty)]
            else:  # цель левее: огибаем снизу блока-источника
                ybel = pos[l["from"]][1] - 0.15 - 0.12 * k
                xl = tx - 0.2 - 0.12 * k
                pts = [(sx, sy), (mid, sy), (mid, ybel), (xl, ybel), (xl, ty), (tx, ty)]
            _arrow(ax, pts, lab, (sx + 0.08, sy + 0.05), fs=7.2)
        elif forward and l["side"] == "C":
            lab = wrap(l.get("label", ""), 16)
            _arrow(ax, [(sx, sy), (tx, sy), (tx, ty)], lab, (sx + 0.08, sy + 0.05), fs=7.2)
        else:  # обратная связь: огибаем сверху
            fb += 1
            up = pos[l["to"]][1] + bh + 0.35 + 0.22 * fb
            xr = sx + 0.3 + 0.15 * fb
            if l["side"] == "C":
                pts = [(sx, sy), (xr, sy), (xr, up), (tx, up), (tx, ty)]
            else:
                xl = tx - 0.35 - 0.15 * fb
                pts = [(sx, sy), (xr, sy), (xr, up), (xl, up), (xl, ty), (tx, ty)]
            lab = wrap(l.get("label", ""), 30)
            _arrow(ax, pts, lab, ((xr + tx) / 2, up + 0.05), ha="center", fs=7.2)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


# =========================================================================== IDEF3
def idef3(spec, out_png):
    """spec = {title, nodes: [{id, kind: 'uow'|'and'|'or'|'xor', name, num, x, y}],
               links: [(from, to, label?)], refs: [{x,y,text}] }
       Координаты в условных единицах (x — столбец, y — строка)."""
    nodes = {n["id"]: n for n in spec["nodes"]}
    sx, sy = 3.1, 1.9
    xs = [n["x"] for n in spec["nodes"]]
    ys = [n["y"] for n in spec["nodes"]]
    W = (max(xs) - min(xs)) * sx + 3.4
    H = (max(ys) - min(ys)) * sy + 2.6
    fig, ax = plt.subplots(figsize=(W * 0.62, H * 0.62 + 0.6))
    ax.axis("off")
    ax.set_aspect("equal")
    x0, y0 = min(xs), max(ys)

    def c(n):
        return ((n["x"] - x0) * sx + 1.7, (y0 - n["y"]) * sy + 1.3)

    bw, bh = 2.4, 1.3
    jr = 0.34
    geo = {}
    for n in spec["nodes"]:
        cx, cy = c(n)
        if n["kind"] == "uow":
            ax.add_patch(Rectangle((cx - bw / 2, cy - bh / 2), bw, bh, fc="white", ec="black", lw=1.3, zorder=3))
            ax.text(cx, cy + 0.14, wrap(n["name"], _chars(bw - 0.3, 8)), ha="center", va="center", fontsize=8,
                    zorder=4, linespacing=1.1)
            ax.add_patch(Rectangle((cx - bw / 2, cy - bh / 2), 0.62, 0.27, fc="white", ec="black", lw=0.8, zorder=4))
            ax.text(cx - bw / 2 + 0.31, cy - bh / 2 + 0.135, n.get("num", ""), ha="center", va="center",
                    fontsize=7, zorder=5)
            geo[n["id"]] = (cx, cy, bw / 2, bh / 2)
        else:
            sym = {"and": "&", "or": "O", "xor": "X"}[n["kind"]]
            ax.add_patch(Rectangle((cx - jr, cy - jr * 1.3), 2 * jr, 2.6 * jr, fc="white", ec="black", lw=1.3, zorder=3))
            ax.plot([cx - jr * 0.55, cx - jr * 0.55], [cy - jr * 1.3, cy + jr * 1.3], color="black", lw=0.8, zorder=4)
            ax.text(cx + 0.08, cy, sym, ha="center", va="center", fontsize=10, weight="bold", zorder=4)
            ax.text(cx - jr - 0.06, cy + jr * 1.3, n.get("num", ""), ha="right", va="bottom", fontsize=6.5)
            geo[n["id"]] = (cx, cy, jr, jr * 1.3)

    for l in spec["links"]:
        a, b = geo[l[0]], geo[l[1]]
        label = l[2] if len(l) > 2 else None
        ax0, ay0 = a[0] + a[2], a[1]
        bx0, by0 = b[0] - b[2], b[1]
        if abs(ay0 - by0) < 1e-6:
            pts = [(ax0, ay0), (bx0, by0)]
        elif nodes[l[0]]["kind"] != "uow":  # из перекрёстка: вертикально, затем вправо
            pts = [(a[0], a[1] + (a[3] if by0 > ay0 else -a[3])), (a[0], by0), (bx0, by0)]
        elif nodes[l[1]]["kind"] != "uow":  # в перекрёсток: вправо, затем вертикально
            pts = [(ax0, ay0), (b[0], ay0), (b[0], b[1] + (b[3] if ay0 > by0 else -b[3]))]
        else:
            mx = (ax0 + bx0) / 2
            pts = [(ax0, ay0), (mx, ay0), (mx, by0), (bx0, by0)]
        xs_, ys_ = zip(*pts)
        ax.plot(xs_, ys_, color="black", lw=1.0)
        ax.annotate("", xy=pts[-1], xytext=pts[-2],
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.0, mutation_scale=9, shrinkA=0, shrinkB=0))
        if label:
            mx = (pts[-2][0] + pts[-1][0]) / 2
            ax.text(mx, pts[-1][1] + 0.08, wrap(label, 16), fontsize=6.5, ha="center", va="bottom")
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


# =========================================================================== VORD
def vord_bubbles(viewpoints, out_png):
    """Диаграмма идентификации точек зрения: viewpoints = [(имя, [сервисы])].
    Точки зрения — серые овалы по внутреннему кругу, их сервисы — белые овалы в секторе снаружи."""
    import math
    total = sum(max(len(sv), 1) for _, sv in viewpoints)
    R1, R2 = 4.6, 8.0
    EW, EH = 2.75, 1.05
    a0 = math.pi / 2
    vps, svc = [], []
    gi = 0
    for name, services in viewpoints:
        m = max(len(services), 1)
        sector = 2 * math.pi * m / total
        mid = a0 - sector / 2
        vp = [R1 * math.cos(mid), R1 * math.sin(mid)]
        vps.append((name, vp))
        for j, sname in enumerate(services):
            ang = a0 - sector * (j + 0.5) / m
            r = R2 + 1.2 * (gi % 2)
            gi += 1
            svc.append([sname, [r * math.cos(ang), r * math.sin(ang)], len(vps) - 1])
        a0 -= sector
    # расталкивание пересекающихся овалов (прямоугольная аппроксимация); центр неподвижен
    items = [(p, 3.0, 1.2) for _, p in vps] + [(p, EW, EH) for _, p, _ in svc]
    for _ in range(600):
        moved = False
        for i, (pi_, wi, hi) in enumerate(items):
            for q, w, h in items[:i] + items[i + 1:] + [([0.0, 0.0], 3.2, 1.3)]:
                dx, dy = pi_[0] - q[0], pi_[1] - q[1]
                ox = (wi + w) / 2 + 0.08 - abs(dx)
                oy = (hi + h) / 2 + 0.08 - abs(dy)
                if ox > 0 and oy > 0:
                    moved = True
                    if oy < ox:
                        pi_[1] += (oy / 2 + 0.02) * (1 if dy >= 0 else -1)
                    else:
                        pi_[0] += (ox / 2 + 0.02) * (1 if dx >= 0 else -1)
        if not moved:
            break
    xs = [p[0] for _, p, _ in svc]
    ys = [p[1] for _, p, _ in svc]
    lim_x = max(abs(min(xs)), abs(max(xs))) + EW / 2 + 0.3
    lim_y = max(abs(min(ys)), abs(max(ys))) + EH / 2 + 0.3
    fig, ax = plt.subplots(figsize=(13, 13 * lim_y / lim_x))
    ax.axis("off")
    ax.set_aspect("equal")
    ax.add_patch(Ellipse((0, 0), 2.8, 1.1, fc="white", ec="black", lw=1.3, ls="--"))
    ax.text(0, 0, "Система", ha="center", va="center", fontsize=11, weight="bold")
    for name, vp in vps:
        ax.plot([0, vp[0]], [0, vp[1]], color="#999999", lw=0.6, ls=":", zorder=0)
    for sname, p, k in svc:
        vp = vps[k][1]
        ax.plot([vp[0], p[0]], [vp[1], p[1]], color="black", lw=0.6, zorder=1)
        ax.add_patch(Ellipse(p, EW, EH, fc="white", ec="black", lw=0.9, zorder=2))
        ax.text(*p, wrap(sname, 18), ha="center", va="center", fontsize=7.6, zorder=3, linespacing=1.05)
    for name, vp in vps:
        ax.add_patch(Ellipse(vp, 2.9, 1.15, fc="#c8c8c8", ec="black", lw=1.2, zorder=4))
        ax.text(*vp, wrap(name, 16), ha="center", va="center", fontsize=8.6, weight="bold", zorder=5, linespacing=1.05)
    ax.set_xlim(-lim_x, lim_x)
    ax.set_ylim(-lim_y, lim_y)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def tree(root, children, out_png, width=12):
    """Иерархия точек зрения: children = {node: [дочерние]}"""
    levels = {}

    def walk(nd, d):
        levels.setdefault(d, []).append(nd)
        for ch in children.get(nd, []):
            walk(ch, d + 1)
    walk(root, 0)
    # раскладка листьев
    xpos = {}
    counter = [0]

    def place(nd):
        ch = children.get(nd, [])
        if not ch:
            xpos[nd] = counter[0]
            counter[0] += 1
        else:
            for c_ in ch:
                place(c_)
            xpos[nd] = (xpos[ch[0]] + xpos[ch[-1]]) / 2
    place(root)
    depth = max(levels) + 1
    nleaf = counter[0]
    sx = 2.35
    fig, ax = plt.subplots(figsize=(max(width, nleaf * 1.55), depth * 1.5 + 0.5))
    ax.axis("off")
    bw, bh = 2.05, 0.8
    ypos = {}
    for d, nds in levels.items():
        for nd in nds:
            ypos[nd] = -d * 1.6
    for nd in xpos:
        x, y = xpos[nd] * sx, ypos[nd]
        ax.add_patch(FancyBboxPatch((x - bw / 2, y - bh / 2), bw, bh, boxstyle="round,pad=0.02,rounding_size=0.15",
                                    fc="#e6e6e6" if children.get(nd) else "white", ec="black", lw=1.0))
        ax.text(x, y, wrap(nd, 17), ha="center", va="center", fontsize=7.6)
        for ch in children.get(nd, []):
            cx, cy = xpos[ch] * sx, ypos[ch]
            ym = (y - bh / 2 + cy + bh / 2) / 2
            ax.plot([x, x, cx, cx], [y - bh / 2, ym, ym, cy + bh / 2], color="black", lw=0.9)
    ax.set_xlim(-bw, (nleaf - 1) * sx + bw)
    ax.set_ylim(-(depth - 1) * 1.6 - 0.7, 0.7)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


# =========================================================================== планирование
def schedule(stages, start):
    """stages: [{id, name, dur, deps:[ids], who}] -> ES/EF (дни от start), критический путь."""
    st = {s["id"]: dict(s) for s in stages}
    order = [s["id"] for s in stages]
    for i in order:
        s = st[i]
        s["es"] = max([st[d]["ef"] for d in s["deps"]], default=0)
        s["ef"] = s["es"] + s["dur"]
    T = max(s["ef"] for s in st.values())
    for i in reversed(order):
        s = st[i]
        succ = [st[j] for j in order if i in st[j]["deps"]]
        s["lf"] = min([x["ls"] for x in succ], default=T)
        s["ls"] = s["lf"] - s["dur"]
        s["slack"] = s["ls"] - s["es"]
    for s in st.values():
        s["start"] = start + dt.timedelta(days=s["es"])
        s["end"] = start + dt.timedelta(days=s["ef"] - 1)
    return [st[i] for i in order], T


def gantt(sched, out_png, start, title=None, by_person=False):
    import matplotlib.dates as mdates
    rows = []
    if by_person:
        people = []
        for s in sched:
            for p in s["who"]:
                if p not in people:
                    people.append(p)
        for p in people:
            for s in sched:
                if p in s["who"]:
                    rows.append((p, s))
    else:
        rows = [(s["id"] + ". " + s["name"], s) for s in sched]
    fig_h = 0.42 * len(rows) + 1.6
    fig, ax = plt.subplots(figsize=(12, fig_h))
    labels = []
    for k, (lab, s) in enumerate(rows):
        y = len(rows) - k
        x0 = mdates.date2num(s["start"])
        w = s["dur"]
        crit = s["slack"] == 0
        ax.barh(y, w, left=x0, height=0.55, color="#555555" if crit else "white",
                edgecolor="black", lw=0.9)
        if not by_person and s["slack"] > 0:
            ax.barh(y, s["slack"], left=x0 + w, height=0.55, color="#d9d9d9", edgecolor="black",
                    lw=0.5, hatch="///")
        ax.text(x0 + w / 2, y, s["id"], ha="center", va="center", fontsize=7.5,
                color="white" if crit else "black", weight="bold")
        labels.append(lab)
    ax.set_yticks(range(len(rows), 0, -1))
    if by_person:
        prev = None
        ylabels = []
        for lab, s in rows:
            ylabels.append(lab if lab != prev else "")
            prev = lab
        ax.set_yticklabels(ylabels, fontsize=9)
        # разделители между сотрудниками
        k = 0
        for i in range(1, len(rows)):
            if rows[i][0] != rows[i - 1][0]:
                ax.axhline(len(rows) - i + 0.5, color="black", lw=0.6)
    else:
        ax.set_yticklabels([wrap(l, 48) for l in labels], fontsize=8)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    plt.setp(ax.get_xticklabels(), rotation=90, fontsize=7.5)
    ax.grid(axis="x", color="#cccccc", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_ylim(0.3, len(rows) + 0.7)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI, facecolor="white")
    plt.close(fig)
    return out_png


def network(sched, out_png, start):
    """Сетевой график «работа в узле» (activity-on-node): уровни по зависимостям."""
    st = {s["id"]: s for s in sched}
    lvl = {}
    for s in sched:
        lvl[s["id"]] = max([lvl[d] + 1 for d in s["deps"]], default=1)
    cols = {}
    for i, l in lvl.items():
        cols.setdefault(l, []).append(i)
    maxl = max(cols)
    maxr = max(len(v) for v in cols.values())
    sx, sy = 2.45, 1.75
    bw, bh = 1.95, 1.25
    fig, ax = plt.subplots(figsize=((maxl + 2) * sx * 0.62 + 0.5, (maxr) * sy * 0.62 + 1.4))
    ax.axis("off")
    ax.set_aspect("equal")
    pos = {}
    for l, ids in cols.items():
        n = len(ids)
        for k, i in enumerate(ids):
            pos[i] = (l * sx, ((n - 1) / 2 - k) * sy)
    # события начала/конца
    pos["start"] = (0, 0)
    pos["end"] = ((maxl + 1) * sx, 0)
    for key, lab, d in (("start", "Начало", start), ("end", "Конец", start + dt.timedelta(days=max(s["ef"] for s in sched) - 1))):
        x, y = pos[key]
        ax.add_patch(Ellipse((x, y), 1.45, 0.95, fc="#e6e6e6", ec="black", lw=1.1))
        ax.text(x, y, f"{lab}\n{d.strftime('%d.%m.%Y')}", ha="center", va="center", fontsize=7.5)

    def edge(a, b, crit):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ra = bw / 2 if a in st else 0.72
        rb = bw / 2 if b in st else 0.72
        p1 = (x1 + ra, y1)
        p2 = (x2 - rb, y2)
        ax.annotate("", xy=p2, xytext=p1,
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.8 if crit else 0.8,
                                    mutation_scale=10, shrinkA=0, shrinkB=0,
                                    connectionstyle="arc3,rad=0"), zorder=1)
    succ = {i: [] for i in st}
    for s in sched:
        for d in s["deps"]:
            succ[d].append(s["id"])
    for s in sched:
        if not s["deps"]:
            edge("start", s["id"], s["slack"] == 0)
        for d in s["deps"]:
            edge(d, s["id"], s["slack"] == 0 and st[d]["slack"] == 0 and st[d]["ef"] == s["es"])
        if not succ[s["id"]]:
            edge(s["id"], "end", s["slack"] == 0)
    for i, s in st.items():
        x, y = pos[i]
        crit = s["slack"] == 0
        ax.add_patch(Rectangle((x - bw / 2, y - bh / 2), bw, bh, fc="white", ec="black", lw=2.0 if crit else 1.0, zorder=3))
        ax.plot([x - bw / 2, x + bw / 2], [y + bh / 2 - 0.32, y + bh / 2 - 0.32], color="black", lw=0.6, zorder=4)
        ax.plot([x - bw / 2, x + bw / 2], [y - bh / 2 + 0.32, y - bh / 2 + 0.32], color="black", lw=0.6, zorder=4)
        ax.text(x, y + bh / 2 - 0.16, f"{i}   {s['dur']} дн.", ha="center", va="center", fontsize=7, weight="bold", zorder=5)
        ax.text(x, y, wrap(s["short"], 20), ha="center", va="center", fontsize=6.4, zorder=5)
        ax.text(x, y - bh / 2 + 0.16, f"{s['start'].strftime('%d.%m')}–{s['end'].strftime('%d.%m')}  R={s['slack']}",
                ha="center", va="center", fontsize=6.2, zorder=5)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 1.2, max(xs) + 1.2)
    ax.set_ylim(min(ys) - 1.0, max(ys) + 1.0)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def flow(boxes, out_png, ncols=None):
    """Простая горизонтальная схема последовательности (для иллюстраций)."""
    n = len(boxes)
    fig, ax = plt.subplots(figsize=(min(12, n * 2.3), 1.8))
    ax.axis("off")
    bw = 1.9
    for k, b in enumerate(boxes):
        x = k * 2.4
        ax.add_patch(FancyBboxPatch((x, 0), bw, 1.0, boxstyle="round,pad=0.02,rounding_size=0.12", fc="white", ec="black"))
        ax.text(x + bw / 2, 0.5, wrap(b, 16), ha="center", va="center", fontsize=8)
        if k < n - 1:
            ax.annotate("", xy=(x + 2.4, 0.5), xytext=(x + bw, 0.5), arrowprops=dict(arrowstyle="-|>", color="black"))
    ax.set_xlim(-0.2, (n - 1) * 2.4 + bw + 0.2)
    ax.set_ylim(-0.2, 1.2)
    fig.savefig(out_png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png
