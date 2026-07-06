# -*- mode: python ; coding: utf-8 -*-
"""
macOS Intel packaging configuration.
Use on an Intel macOS runner: pyinstaller build_macos_intel.spec
Output: dist/工作流管理_<APP_VERSION>_macos_intel.app
"""

import runpy
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

src_path = Path("src")
if str(src_path.resolve()) not in sys.path:
    sys.path.insert(0, str(src_path.resolve()))

config = runpy.run_path(str(src_path / "config.py"))
app_name = config["APP_NAME"]
app_version = config["APP_VERSION"]
bundle_name = f"{app_name}_{app_version}_macos_intel"

a = Analysis(
    ["src/main.py"],
    pathex=[str(src_path)],
    binaries=[],
    datas=[
        ("图标.ico", "."),
        ("图标.png", "."),
    ] + collect_data_files("certifi"),
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "sqlalchemy",
        "sqlalchemy.orm",
        "sqlalchemy.dialects.sqlite",
        "requests",
        "watchdog",
        "watchdog.observers",
        "watchdog.events",
        "backports.tarfile",
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
        "win32com",
        "win32com.client",
        "pywintypes",
        "pythoncom",
        "pywinauto",
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
        "PySide6.QtSvg",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=bundle_name,
)

app = BUNDLE(
    coll,
    name=f"{bundle_name}.app",
    icon=None,
    bundle_identifier="com.workflow.manager",
)
