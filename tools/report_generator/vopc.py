# -*- coding: utf-8 -*-
"""Диаграмма классов, участвующих в реализации варианта использования (VOPC), из его диаграммы
последовательности: классы — объекты-участники со стереотипами, операции — принимаемые сообщения,
связи — пары объектов, обменивающихся сообщениями. Атрибуты классов-сущностей берутся из models.py."""
import re

DECL = re.compile(r'^(actor|boundary|control|entity|participant|database)\s+"([^"]+)"\s+as\s+(\w+)')
MSG = re.compile(r'^(\w+)\s*(-{1,2}>{1,2})\s*(\w+)\s*:\s*(.+)$')
STOP = {"в", "во", "из", "и", "по", "с", "со", "на", "для", "к", "от", "до", "о", "об", "а", "или", "при", "за"}
SKIP_ATTR = {"id", "created_at", "updated_at", "raw", "password_hash"}


def parse(src):
    """(объекты {псевдоним: (вид, имя)}, порядок, сообщения [(от, к, текст, ответ)])."""
    objs, order, msgs = {}, [], []
    for raw in src.strip().splitlines():
        line = raw.strip()
        m = DECL.match(line)
        if m:
            kind, name, alias = m.groups()
            objs[alias] = (kind, name)
            order.append(alias)
            continue
        m = MSG.match(line)
        if m:
            a, arrow, b, text = m.groups()
            msgs.append((a, b, text.strip(), arrow.startswith("--")))
    return objs, order, msgs


def operation(text):
    """Имя операции из текста сообщения: «найти(паспорт)» — как есть, «ввести анкету клиента» —
    вводитьАнкетуКлиента() (три значимых слова)."""
    t = re.sub(r"<<[^>]*>>|\[[^\]]*\]", "", text).strip()
    m = re.match(r"^([\wА-Яа-яЁё]+)\s*\(([^)]*)\)", t)
    if m:
        args = m.group(2).strip()
        return f"{m.group(1)}({args})" if len(args) <= 28 else f"{m.group(1)}(...)"
    t = re.split(r"[,:;(]", t)[0]
    words = [w for w in re.findall(r"[\wА-Яа-яЁё]+", t) if w.lower() not in STOP][:3]
    if not words:
        return None
    name = words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])
    return name + "()"


def collect(sequences):
    """{(вид, имя): [операции]} по набору диаграмм последовательности."""
    ops = {}
    for src in sequences:
        objs, order, msgs = parse(src)
        for a, b, text, ret in msgs:
            if ret or b not in objs or objs[b][0] not in ("boundary", "control", "entity"):
                continue
            op = operation(text)
            if not op:
                continue
            key = objs[b]
            lst = ops.setdefault(key, [])
            base = op.split("(")[0]
            same = [i for i, x in enumerate(lst) if x[1:].split("(")[0] == base]
            if same:
                i = same[0]
                vis = "+" if a != b else lst[i][0]      # вызов извне делает операцию открытой
                sig = lst[i][1:]
                if sig != op and not sig.endswith("()"):
                    sig = base + "(...)"                # разные аргументы в разных сообщениях
                lst[i] = vis + sig
                continue
            lst.append(("-" if a == b else "+") + op)
    return ops


def entity_attrs(cls_info, n=6):
    """Ключевые атрибуты класса-сущности: поля модели без служебных и ссылочных."""
    if not cls_info:
        return []
    out = []
    for name, typ, fk, _ in cls_info["cols"]:
        if name in SKIP_ATTR or fk or name.endswith("_id"):
            continue
        out.append("{field} " + f"{name}: {typ.split(',')[0]}")
    return out[:n]


def from_sequence(src, entities=None, fks=None):
    """entities — {русское имя сущности: описание класса из modelscan}; fks — [(родитель, потомок, кратность)] по именам."""
    entities = entities or {}
    objs, order, msgs = parse(src)
    classes = [a for a in order if objs[a][0] in ("boundary", "control", "entity")]
    ops = collect([src])
    out = ["hide circle", "skinparam classAttributeIconSize 0"]
    for a in classes:
        kind, name = objs[a]
        lines = []
        if kind == "entity":
            lines += entity_attrs(entities.get(name))
            if lines:
                lines.append("--")
        lines += ops.get((kind, name), [])
        body = "\n".join(" " + x for x in lines)
        out.append(f"class {name} <<{kind}>> {{\n{body}\n}}" if lines else f"class {name} <<{kind}>>")
    names = {objs[a][1] for a in classes}
    seen = set()
    for a, b, text, ret in msgs:
        if ret or a == b or a not in classes or b not in classes:
            continue
        pair = (objs[a][1], objs[b][1])
        if pair in seen or pair[::-1] in seen:
            continue
        seen.add(pair)
        if objs[b][0] == "entity" and objs[a][0] == "entity":
            continue
        out.append(f"{pair[0]} --> {pair[1]}")
    for parent, child, mult in fks or []:
        if parent in names and child in names and parent != child:
            out.append(f'{parent} "1" -- "{mult}" {child}')
    return "\n".join(out)
