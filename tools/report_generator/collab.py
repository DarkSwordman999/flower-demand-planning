# -*- coding: utf-8 -*-
"""Диаграмма кооперации (коммуникации) из диаграммы последовательности PlantUML.

Те же объекты и сообщения, что на диаграмме последовательности, но показаны связи между объектами;
порядок сообщений задаётся номерами, условия альтернативных ветвей — в квадратных скобках."""
import re
import textwrap

DECL = re.compile(r'^(actor|boundary|control|entity|participant|database)\s+"([^"]+)"\s+as\s+(\w+)')
MSG = re.compile(r'^(\w+)\s*(-{1,2}>{1,2})\s*(\w+)\s*:\s*(.+)$')
STEREO = {"boundary": "boundary", "control": "control", "entity": "entity"}


def _wrap(s, n=32):
    return "\\n".join(textwrap.wrap(s, n, break_long_words=False)) or s


def from_sequence(src):
    objs, order, links = {}, [], {}
    guards = []
    num = 0
    for raw in src.strip().splitlines():
        line = raw.strip()
        m = DECL.match(line)
        if m:
            kind, name, alias = m.groups()
            objs[alias] = (kind, name)
            order.append(alias)
            continue
        low = line.split(" ", 1)
        if low[0] in ("alt", "opt", "loop", "par", "group", "critical"):
            guards.append(low[1] if len(low) > 1 else "")
            continue
        if low[0] == "else":
            if guards:
                guards[-1] = low[1] if len(low) > 1 else "иначе"
            continue
        if low[0] == "end":
            if guards:
                guards.pop()
            continue
        m = MSG.match(line)
        if not m:
            continue
        a, arrow, b, text = m.groups()
        num += 1
        guard = f"[{guards[-1]}] " if guards and guards[-1] else ""
        key = tuple(sorted((a, b), key=lambda x: order.index(x) if x in order else 99))
        # направление: ↓ — от верхнего объекта связи к нижнему, ↑ — обратно (связь a -- b рисуется сверху вниз)
        if a == b:
            label = f"{num}: {guard}{text.strip()}"
        elif (a, b) == key:
            label = f"{num}: {guard}{text.strip()} ↓"
        else:
            label = f"{num}: {guard}{text.strip()} ↑"
        links.setdefault(key, []).append(_wrap(label.replace('"', "'")))
    out = ["skinparam rectangle {", " BorderColor black", "}"]
    for alias in order:
        kind, name = objs[alias]
        if kind == "actor":
            out.append(f'actor "{name}" as {alias}')
        else:
            st = f"\\n«{STEREO[kind]}»" if kind in STEREO else ""
            out.append(f'rectangle ":{name}{st}" as {alias}')
    for (a, b), labels in links.items():
        out.append(f'{a} -- {b} : "' + "\\n".join(labels) + '"')
    return "\n".join(out)


if __name__ == "__main__":
    demo = '''
actor "Специалист" as KS
boundary "Форма" as UI
control "Контроллер" as C
KS -> UI : ввести анкету
UI -> C : создать()
alt ошибка
  C --> UI : ошибки
else успех
  C --> UI : номер
end
'''
    print(from_sequence(demo))
