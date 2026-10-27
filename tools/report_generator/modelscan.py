# -*- coding: utf-8 -*-
"""Классы-сущности прямо из models.py программы (SQLAlchemy, Mapped / mapped_column) — без импорта кода
и без базы данных: файл разбирается модулем ast. Поэтому атрибуты в отчёте всегда совпадают с программой."""
import ast

TYPES = {
    "String": "строка", "Text": "текст", "Integer": "целое", "Float": "дробное", "Numeric": "деньги",
    "Money": "деньги", "Boolean": "логическое", "Date": "дата", "DateTime": "дата и время", "JSON": "JSON",
}
PY = {"int": "целое", "str": "строка", "float": "дробное", "bool": "логическое", "date": "дата",
      "datetime": "дата и время", "dict": "JSON", "list": "JSON"}


def _type(call, ann):
    """Тип столбца: по первому аргументу mapped_column, иначе по аннотации Mapped[...]."""
    fk = None
    typ = None
    for a in call.args:
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Name):
            if a.func.id == "ForeignKey":
                fk = a.args[0].value.split(".")[0] if a.args and isinstance(a.args[0], ast.Constant) else "?"
                continue
            if a.func.id in TYPES:
                typ = TYPES[a.func.id]
                if a.func.id == "String" and a.args and isinstance(a.args[0], ast.Constant):
                    typ += f"({a.args[0].value})"
        elif isinstance(a, ast.Name) and a.id in TYPES:
            typ = TYPES[a.id]
    nullable = False
    for kw in call.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = bool(kw.value.value)
        if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant) and kw.value.value:
            typ = (typ or "целое") + ", ключ"
    src = ast.unparse(ann) if ann is not None else ""
    if typ is None:
        for k, v in PY.items():
            if f"[{k}" in src or f"{k} |" in src or src.endswith(k + "]"):
                typ = v
                break
    if "None" in src:
        nullable = True
    if fk:
        typ = "ссылка"
    return typ or "—", fk, nullable


def scan(path):
    """[{"cls", "table", "doc", "cols": [(имя, тип, ссылка на таблицу | None, может быть пустым)],
         "rels": [имена relationship]}] в порядке файла."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        table, cols, rels, unique = None, [], [], set()
        for st in node.body:
            if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__"
                                                  for t in st.targets):
                table = st.value.value
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and isinstance(st.value, ast.Call):
                fn = st.value.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == "mapped_column":
                    cols.append((st.target.id, *_type(st.value, st.annotation)))
                    if any(kw.arg == "unique" and isinstance(kw.value, ast.Constant) and kw.value.value
                           for kw in st.value.keywords):
                        unique.add(st.target.id)
                elif name == "relationship":
                    rels.append(st.target.id)
        if table:
            out.append({"cls": node.name, "table": table, "doc": (ast.get_docstring(node) or "").split("\n")[0],
                        "cols": cols, "rels": rels, "unique": unique})
    return out


def by_table(path):
    return {c["table"]: c for c in scan(path)}
