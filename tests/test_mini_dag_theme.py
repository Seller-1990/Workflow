# -*- coding: utf-8 -*-
"""MiniDag 主题回归测试：refresh_theme 必须重涂烘焙进 item 的类型背景色。

背景：_make_item 在 set_data 时把类型色 QBrush 烘焙进 QListWidgetItem，
refresh_theme 若只刷 QSS，切主题后节点仍保留旧主题底色（V9.3 修复）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget

from ui.mini_dag import MiniDagWidget  # noqa: E402

TYPE_KEY_ROLE = int(Qt.UserRole) + 1  # _make_item 存放 type_key 的角色位


@dataclass
class DummyStep:
    id: int
    uid: str
    name: str
    order: int
    step_type: str = "python"


def _list_by_suffix(widget: MiniDagWidget, suffix: str) -> QListWidget:
    return next(l for l in widget.findChildren(QListWidget) if l.objectName().endswith(suffix))


def test_refresh_theme_recolors_baked_item_backgrounds():
    app = QApplication.instance() or QApplication([])
    widget = MiniDagWidget(dark=False)
    try:
        current = DummyStep(1, "uid-1", "当前步骤", 0, "python")
        upstream = DummyStep(2, "uid-2", "上游步骤", 1, "excel_powerquery")
        widget.set_data(current, [upstream], [])

        current_list = _list_by_suffix(widget, "current")
        item = current_list.item(0)
        assert item.data(TYPE_KEY_ROLE) == "python"
        # 亮色下 python 节点底色应为亮色 token（#EEF0FC）
        assert item.background().color().name().upper() == "#EEF0FC"

        widget.refresh_theme(True)

        # 切暗色后必须重涂为暗色 token（#1E1F3A），而不是保留亮色烘焙值
        assert item.background().color().name().upper() == "#1E1F3A"
    finally:
        widget.deleteLater()
        assert app is not None
