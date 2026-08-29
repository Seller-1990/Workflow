# -*- coding: utf-8 -*-
"""图标库回归测试：_ICON_MAP 中每个键必须真实可渲染。

背景：fa5s.python 是无效字形（Python logo 属 brands 族），曾在 icons() 的
兜底 except 下静默渲染为空；slim 打包还会裁掉未使用的 qtawesome 字体族。
本文件从两个方向防回归：
1. 字形有效性——每个映射键在 qtawesome 下渲染成功且 pixmap 非空；
2. 字体族约束——映射只允许使用 slim 打包保留的 fa5s/fa5b 前缀。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QApplication = pytest.importorskip("PySide6.QtWidgets", reason="需要 PySide6").QApplication

from ui.icons import _ICON_MAP, type_icon  # noqa: E402

# slim 打包（build_slim_rules.QTAWESOME_KEEP_FONT_FILES）保留的字体族前缀
KEEP_FONT_PREFIXES = {"fa5s", "fa5b"}


def test_icon_map_only_uses_bundled_font_prefixes():
    """slim 包只保留 fa5s/fa5b 字体，_ICON_MAP 不得引用其他前缀。"""
    bad = {name: key for name, key in _ICON_MAP.items() if key.split(".", 1)[0] not in KEEP_FONT_PREFIXES}
    assert not bad, f"以下图标键使用了会被 slim 打包裁掉的字体族: {bad}"


def test_icon_map_all_glyphs_render():
    """ui.icons.icon() 内部会吞掉 qtawesome 异常并返回空 QIcon，
    因此这里直接断言非空——空值即意味着字形无效或字体缺失。"""
    from ui.icons import icon

    app = QApplication.instance() or QApplication([])
    for name, key in _ICON_MAP.items():
        rendered = icon(name, color="#3F3F46")
        assert not rendered.isNull(), (name, key)
        assert not rendered.pixmap(32, 32).isNull(), (name, key)
    assert app is not None


@pytest.mark.parametrize(
    "step_type",
    ["python", "excel_powerquery", "powerbi_refresh", "sub_workflow", "unknown_type"],
)
def test_type_icon_renders_for_all_step_types(step_type):
    """type_icon 对已知/未知类型都必须产出非空 pixmap（回归：fa5s.python 静默为空）。"""
    app = QApplication.instance() or QApplication([])
    for dark in (False, True):
        rendered = type_icon(step_type, dark=dark)
        assert not rendered.isNull(), (step_type, dark)
        assert not rendered.pixmap(32, 32).isNull(), (step_type, dark)
    assert app is not None
