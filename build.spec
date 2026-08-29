# -*- mode: python ; coding: utf-8 -*-
"""
工作流管理应用打包配置
使用命令: pyinstaller build.spec
"""

import sys
import runpy
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# 项目路径
src_path = Path('src')
config = runpy.run_path(str(src_path / 'config.py'))
app_name = config['APP_NAME']
app_version = config['APP_VERSION']
exe_name = f"{app_name}_{app_version}"

a = Analysis(
    ['src/main.py'],
    pathex=[str(src_path)],
    binaries=[],
    datas=[
        ('图标.ico', '.'),
        # 如果有静态资源文件，在这里添加
        # ('src/resources', 'resources'),
    ] + collect_data_files('certifi'),
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'sqlalchemy',
        'sqlalchemy.orm',
        'sqlalchemy.dialects.sqlite',
        'requests',
        # CLI 子命令路由（main.py 在打包后通过 from cli import CLI_COMMANDS 转发）
        'cli',
        'duration_utils',
        # V9：统一图标库
        'qtawesome',
        'qtpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除冲突的 Qt 绑定
        'PyQt5', 'PyQt6', 'PySide2',
        # 排除无用的大包（避免 torch/scipy/matplotlib/pandas/IPython 被一并打包）
        'torch', 'torchvision', 'torchaudio', 'tensorflow',
        'scipy', 'matplotlib', 'pandas', 'numpy',
        'IPython', 'jupyter', 'notebook', 'nbformat',
        'tkinter', '_tkinter', 'pyarrow', 'jedi', 'parso',
        'fsspec', 'zmq', 'orjson', 'lark', 'PIL', 'jinja2',
        'sympy', 'sklearn', 'networkx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

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
    runtime_tmpdir=os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "工作流管理", "pyi-tmp"
    ),
    console=False,  # False = 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='图标.ico',  # EXE 文件图标
)
