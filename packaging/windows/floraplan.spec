# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller packaging/windows/floraplan.spec (из каталога backend, после npm run build)
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
PKG = os.path.join(ROOT, "floraplan")

datas = [
    (os.path.join(PKG, "static"), "floraplan/static"),
    (os.path.join(PKG, "migrations"), "floraplan/migrations"),
]
datas += collect_data_files("statsmodels")
binaries, hidden = [], []
for pkg in ("scipy", "statsmodels"):   # расширения и DLL (scipy.libs) — целиком
    d_, b_, h_ = collect_all(pkg)
    datas += d_
    binaries += b_
    hidden += h_
hidden += (collect_submodules("floraplan") + collect_submodules("uvicorn") + collect_submodules("apscheduler")
          + ["statsmodels.tsa.holtwinters", "openpyxl", "psycopg", "multipart"])

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ФлораПлан",
    console=True,
    icon=os.path.join(SPECPATH, "floraplan.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="FloraPlan")
