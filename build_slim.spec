# -*- mode: python ; coding: utf-8 -*-
"""
工作流管理应用精简打包配置
使用命令: pyinstaller build_slim.spec
输出: dist/工作流管理_4.1.0_slim.exe
"""

import runpy
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

src_path = Path("src")
if str(src_path.resolve()) not in sys.path:
    sys.path.insert(0, str(src_path.resolve()))

from build_slim_rules import should_keep_artifact

config = runpy.run_path(str(src_path / "config.py"))
app_name = config["APP_NAME"]
app_version = config["APP_VERSION"]
exe_name = f"{app_name}_{app_version}_slim"


def _filter_toc_entries(entries):
    filtered = []
    for entry in entries:
        if len(entry) < 2:
            filtered.append(entry)
            continue
        dest_name = entry[0]
        if should_keep_artifact(dest_name, profile="slim1"):
            filtered.append(entry)
    return filtered


a = Analysis(
    ["src/main.py"],
    pathex=[str(src_path)],
    binaries=[],
    datas=[
        ("图标.png", "."),
    ] + collect_data_files("certifi"),
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "sqlalchemy",
        "sqlalchemy.orm",
        "sqlalchemy.dialects.sqlite",
        "win32com.client",
        "pywintypes",
        "pythoncom",
        "pywinauto",
        "requests",
        "watchdog",
        "watchdog.observers",
        "watchdog.events",
        # V9：图标库
        "qtawesome",
        "qtpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "scipy",
        "matplotlib",
        "pandas",
        "numpy",
        "IPython",
        "jupyter",
        "notebook",
        "nbformat",
        "tkinter",
        "_tkinter",
        "pyarrow",
        "jedi",
        "parso",
        "fsspec",
        "zmq",
        "orjson",
        "lark",
        "PIL",
        "jinja2",
        "sympy",
        "sklearn",
        "networkx",
        "PySide6.QtPdf",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtVirtualKeyboard",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = _filter_toc_entries(a.binaries)
a.datas = _filter_toc_entries(a.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="图标.ico",
)
