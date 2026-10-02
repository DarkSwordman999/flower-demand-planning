# -*- coding: utf-8 -*-
"""Сборка отчётов: python build.py [flowers] [12 3 4 56 78 910]
(нужны Windows + MS Word, Java 11+ и plantuml.jar рядом со скриптами)"""
import os, sys, time, importlib
import win32com.client
import docgen, diagrams as dg
import lab12, lab3, lab4, lab56, lab78, lab910
from config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = {
    "flowers": os.path.abspath(os.path.join(HERE, "..", "..")),
}
FILES = {
    "12": "ПР_1-2_Стандарты_и_методологии",
    "3": "ПР_3_Описание_и_анализ_ИС",
    "4": "ПР_4_Требования_к_ИС",
    "56": "ПР_5-6_Функциональное_моделирование",
    "78": "ПР_7-8_Объектно-ориентированное_моделирование",
    "910": "ПР_9-10_Управление_проектом",
}


def topic(key):
    a, b = importlib.import_module("topic_flowers"), importlib.import_module("topic_flowers2")
    return {
        "name": a.NAME, "short": a.SHORT, "literature": a.LITERATURE,
        "laws": a.LAB12["laws"], "concl": a.LAB12["concl"], "secret": a.LAB12["secret"], "slug": a.SLUG,
        "lab3": a.LAB3, "lab4": a.LAB4, "lab56": b.LAB56, "lab78": b.LAB78, "lab910": b.LAB910,
        "arch": a.ARCH_PUML, "er": a.ER_PUML, "tree": a.TREE, "viewpoints": a.VIEWPOINTS,
    }


def run(key, which):
    T = topic(key)
    root = OUT[key]
    rep = os.path.join(root, "reports")
    dia = os.path.join(root, "diagrams")
    os.makedirs(rep, exist_ok=True)
    os.makedirs(dia, exist_ok=True)
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        for w in which:
            t0 = time.time()
            if w == "12":
                blocks, no, title, tp = lab12.blocks(T), "1-2", lab12.TITLE, None
            elif w == "3":
                figs = {"arch": dg.plantuml(T["arch"], os.path.join(dia, "pr3_architecture.png"))}
                blocks, no, title, tp = lab3.blocks(T, figs), "3", lab3.TITLE, T["name"]
            elif w == "4":
                vps = T["viewpoints"]
                figs = {
                    "vord": dg.vord_bubbles([(v["name"], v["services"]) for v in vps], os.path.join(dia, "pr4_vord_identification.png")),
                    "tree": dg.tree(T["tree"][0], T["tree"][1], os.path.join(dia, "pr4_vord_hierarchy.png")),
                    "er": dg.plantuml(T["er"], os.path.join(dia, "pr4_er_model.png")),
                }
                blocks, no, title, tp = lab4.blocks(T, figs), "4", lab4.TITLE, T["name"]
            elif w == "56":
                figs = lab56.make_figs(T, dia)
                blocks, no, title, tp = lab56.blocks(T, figs), "5-6", lab56.TITLE, T["name"]
            elif w == "78":
                figs = lab78.make_figs(T, dia)
                blocks, no, title, tp = lab78.blocks(T, figs), "7-8", lab78.TITLE, T["name"]
            elif w == "910":
                figs = lab910.make_figs(T, dia)
                blocks, no, title, tp = lab910.blocks(T, figs), "9-10", lab910.TITLE, T["name"]
            out = os.path.join(rep, FILES[w] + ".docx")
            splits, pages = docgen.build_final(blocks, out, CFG, no, title, tp, word=word)
            print(f"{key} ПР {no}: {pages} стр., разрезано таблиц: {len(splits)}, {time.time() - t0:.0f} c", flush=True)
    finally:
        word.Quit()


if __name__ == "__main__":
    keys = ["flowers"]
    args = [a for a in sys.argv[1:] if a != "flowers"]
    which = args or ["12", "3", "4", "56", "78", "910"]
    for k in keys:
        run(k, which)
