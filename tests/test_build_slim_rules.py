# -*- coding: utf-8 -*-
"""slim 打包资源过滤规则测试"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from build_slim_rules import should_keep_artifact


def test_should_drop_unused_qt_modules():
    assert should_keep_artifact("PySide6\\Qt6Pdf.dll", profile="slim1") is False
    assert should_keep_artifact("PySide6\\Qt6Qml.dll", profile="slim1") is False
    assert should_keep_artifact("PySide6\\Qt6Quick.dll", profile="slim1") is False
    assert should_keep_artifact("PySide6\\Qt6VirtualKeyboard.dll", profile="slim1") is False


def test_should_drop_unneeded_qt_translations():
    assert should_keep_artifact("PySide6\\translations\\qtbase_de.qm", profile="slim1") is False
    assert should_keep_artifact("PySide6\\translations\\qt_help_fr.qm", profile="slim1") is False


def test_should_keep_core_qt_runtime():
    assert should_keep_artifact("PySide6\\Qt6Core.dll", profile="slim1") is True
    assert should_keep_artifact("PySide6\\Qt6Gui.dll", profile="slim1") is True
    assert should_keep_artifact("PySide6\\Qt6Widgets.dll", profile="slim1") is True
    assert should_keep_artifact("PySide6\\Qt6Network.dll", profile="slim1") is True
    assert should_keep_artifact("PySide6\\plugins\\platforms\\qwindows.dll", profile="slim1") is True
    assert should_keep_artifact("PySide6\\plugins\\styles\\qmodernwindowsstyle.dll", profile="slim1") is True


def test_should_keep_non_qt_runtime_files():
    assert should_keep_artifact("python312.dll", profile="slim1") is True
    assert should_keep_artifact("pywin32_system32\\pythoncom312.dll", profile="slim1") is True
    assert should_keep_artifact("图标.png", profile="slim1") is True


def test_slim2_drops_icon_png_pythonwin_and_qtsvg():
    assert should_keep_artifact("图标.png", profile="slim2") is False
    assert should_keep_artifact("图标.ico", profile="slim2") is True
    assert should_keep_artifact("Pythonwin\\mfc140u.dll", profile="slim2") is False
    assert should_keep_artifact("Pythonwin\\win32ui.pyd", profile="slim2") is False
    assert should_keep_artifact("PySide6\\Qt6Svg.dll", profile="slim2") is False
    assert should_keep_artifact("PySide6\\plugins\\iconengines\\qsvgicon.dll", profile="slim2") is False
    assert should_keep_artifact("PySide6\\plugins\\imageformats\\qsvg.dll", profile="slim2") is False
