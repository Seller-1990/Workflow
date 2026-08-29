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
    assert should_keep_artifact("certifi\\cacert.pem", profile="slim1") is True
    assert should_keep_artifact("certifi\\cacert.pem", profile="slim2") is True
    assert should_keep_artifact("图标.png", profile="slim1") is True


def test_pyinstaller_specs_collect_certifi_data_files():
    root = Path(__file__).resolve().parent.parent

    for spec_name in ("build.spec", "build_slim.spec", "build_slim2.spec"):
        content = (root / spec_name).read_text(encoding="utf-8")
        assert "collect_data_files" in content
        assert "collect_data_files(\"certifi\")" in content or "collect_data_files('certifi')" in content


def test_slim2_drops_icon_png_pythonwin_and_qtsvg():
    assert should_keep_artifact("图标.png", profile="slim2") is False
    assert should_keep_artifact("图标.ico", profile="slim2") is True
    assert should_keep_artifact("Pythonwin\\mfc140u.dll", profile="slim2") is False
    assert should_keep_artifact("Pythonwin\\win32ui.pyd", profile="slim2") is False
    assert should_keep_artifact("PySide6\\Qt6Svg.dll", profile="slim2") is False
    assert should_keep_artifact("PySide6\\plugins\\iconengines\\qsvgicon.dll", profile="slim2") is False
    assert should_keep_artifact("PySide6\\plugins\\imageformats\\qsvg.dll", profile="slim2") is False


def test_qtawesome_fonts_trimmed_to_fa5_only():
    """V9.3：项目只用 fa5s（solid）与 fa5b（brands，Python logo），其余字体丢弃。"""
    keep = [
        "qtawesome\\fonts\\fontawesome5-solid-webfont-5.15.4.ttf",
        "qtawesome\\fonts\\fontawesome5-solid-webfont-charmap-5.15.4.json",
        "qtawesome\\fonts\\fontawesome5-brands-webfont-5.15.4.ttf",
        "qtawesome\\fonts\\fontawesome5-brands-webfont-charmap-5.15.4.json",
    ]
    drop = [
        "qtawesome\\fonts\\fontawesome5-regular-webfont-5.15.4.ttf",
        "qtawesome\\fonts\\fontawesome6-solid-webfont-6.7.2.ttf",
        "qtawesome\\fonts\\materialdesignicons5-webfont-5.9.55.ttf",
        "qtawesome\\fonts\\materialdesignicons6-webfont-6.9.96.ttf",
        "qtawesome\\fonts\\phosphor-1.3.0.ttf",
        "qtawesome\\fonts\\remixicon-2.5.0.ttf",
        "qtawesome\\fonts\\codicon-0.0.36.ttf",
    ]
    for profile in ("slim1", "slim2"):
        for name in keep:
            assert should_keep_artifact(name, profile=profile) is True, (profile, name)
        for name in drop:
            assert should_keep_artifact(name, profile=profile) is False, (profile, name)


def test_slim_specs_wire_qtawesome_fa5_runtime_hook():
    """slim 包丢弃了非 FA5 字体，必须配套 runtime hook 收窄 _BUNDLED_FONTS，
    否则 qtawesome 急切加载缺失字体会被 ui.icons 吞掉导致图标全空白。"""
    root = Path(__file__).resolve().parent.parent
    hook = root / "tools" / "qtawesome_fa5_runtime_hook.py"
    assert hook.is_file()
    hook_source = hook.read_text(encoding="utf-8")
    assert "_BUNDLED_FONTS" in hook_source
    assert '"fa5s"' in hook_source or "'fa5s'" in hook_source
    assert '"fa5b"' in hook_source or "'fa5b'" in hook_source

    for spec_name in ("build_slim.spec", "build_slim2.spec"):
        content = (root / spec_name).read_text(encoding="utf-8")
        assert "qtawesome_fa5_runtime_hook.py" in content, spec_name
