# -*- coding: utf-8 -*-
"""主窗口面板折叠与分栏布局控制（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例；跨方法调用一律走
``window._xxx`` 委托方法，保持原有动态分发语义。
"""

from PySide6.QtCore import QPoint, QTimer

from ui import run_splitter_controller
from ui.panel_layout import (
    border_button_x,
    expanded_splitter_sizes,
    panel_toggle_text,
    run_splitter_sizes,
    visible_run_splitter_sizes,
)


def update_border_widget_positions(window):
    """更新浮动折叠按钮位置（基于主分栏边缘定位）。"""
    cw = window.centralWidget()
    if not cw or not hasattr(window, "main_splitter") or not hasattr(window, "center_container"):
        return
    splitter_pos = window.main_splitter.mapTo(cw, QPoint(0, 0))
    center_geo = window.center_container.geometry()
    center_left = splitter_pos.x() + center_geo.left()
    center_right = splitter_pos.x() + center_geo.right()
    button_height = 40
    center_y = splitter_pos.y() + center_geo.top() + max(0, (center_geo.height() - button_height) // 2)
    center_y = min(max(0, center_y), max(0, cw.height() - button_height))

    if hasattr(window, 'btn_toggle_left'):
        left_x = border_button_x(
            edge_x=center_left,
            button_width=window.btn_toggle_left.width(),
            parent_width=cw.width(),
        )
        window.btn_toggle_left.move(left_x, center_y)
        window.btn_toggle_left.raise_()
        window.btn_toggle_left.show()

    if hasattr(window, 'btn_toggle_right'):
        right_x = border_button_x(
            edge_x=center_right,
            button_width=window.btn_toggle_right.width(),
            parent_width=cw.width(),
        )
        window.btn_toggle_right.move(right_x, center_y)
        window.btn_toggle_right.raise_()
        window.btn_toggle_right.show()


def on_run_splitter_moved(window, *_args):
    run_splitter_controller.on_run_splitter_moved(window, *_args)


def begin_run_history_collapse(window) -> None:
    run_splitter_controller.begin_run_history_collapse(window)


def _restore_run_history_layout(window) -> None:
    run_splitter_controller._restore_run_history_layout(window)


def prepare_run_history_expand(window) -> None:
    """展开动画开始前解除父 splitter 的折叠高度约束。"""
    _restore_run_history_layout(window)


def on_run_history_collapsed(window, collapsed: bool):
    run_splitter_controller.on_run_history_collapsed(
        window, collapsed, restore_layout=_restore_run_history_layout,
        begin_collapse=begin_run_history_collapse,
    )


def apply_run_splitter_profile(window, profile: str, *, force: bool = False):
    run_splitter_controller.apply_run_splitter_profile(
        window, profile, force=force, restore_layout=_restore_run_history_layout,
        profile_sizes=run_splitter_sizes,
    )


def ensure_run_log_visible(window) -> None:
    run_splitter_controller.ensure_run_log_visible(window, visible_sizes=visible_run_splitter_sizes)


def toggle_left_panel(window, silent: bool = False):
    """折叠/展开左侧面板

    Args:
        silent: 静默模式（启动时恢复状态用），不触发持久化保存
    """
    if window.left_panel.isVisible():
        window._left_last_size = window.left_panel.width()
        window.left_panel.setVisible(False)
        window.btn_toggle_left.setText(panel_toggle_text("left", visible=False))
    else:
        window.left_panel.setVisible(True)
        window.left_panel.setMinimumWidth(200)
        sizes = expanded_splitter_sizes(
            window.main_splitter.sizes(),
            panel_index=0,
            last_size=window._left_last_size,
            minimum_size=200,
        )
        if sizes:
            window.main_splitter.setSizes(sizes)
        window.btn_toggle_left.setText(panel_toggle_text("left", visible=True))
    window._update_border_widget_positions()
    QTimer.singleShot(0, window._update_border_widget_positions)
    QTimer.singleShot(50, window._update_border_widget_positions)
    # V9：持久化面板折叠状态
    if not silent:
        try:
            from ui.ui_state import save_panel_collapsed
            save_panel_collapsed("left", not window.left_panel.isVisible())
        except Exception:
            pass


def toggle_right_panel(window, silent: bool = False):
    """折叠/展开右侧面板

    Args:
        silent: 静默模式（启动时恢复状态用），不触发持久化保存
    """
    if window.right_panel.isVisible():
        window._right_last_size = window.right_panel.width()
        window.right_panel.setVisible(False)
        window.btn_toggle_right.setText(panel_toggle_text("right", visible=False))
    else:
        window.right_panel.setVisible(True)
        window.right_panel.setMinimumWidth(320)
        sizes = expanded_splitter_sizes(
            window.main_splitter.sizes(),
            panel_index=-1,
            last_size=window._right_last_size,
            minimum_size=320,
        )
        if sizes:
            window.main_splitter.setSizes(sizes)
        window.btn_toggle_right.setText(panel_toggle_text("right", visible=True))
    window._update_border_widget_positions()
    QTimer.singleShot(0, window._update_border_widget_positions)
    QTimer.singleShot(50, window._update_border_widget_positions)
    # V9：持久化面板折叠状态
    if not silent:
        try:
            from ui.ui_state import save_panel_collapsed
            save_panel_collapsed("right", not window.right_panel.isVisible())
        except Exception:
            pass
