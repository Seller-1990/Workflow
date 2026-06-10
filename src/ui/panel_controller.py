# -*- coding: utf-8 -*-
"""主窗口面板折叠与分栏布局控制（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例；跨方法调用一律走
``window._xxx`` 委托方法，保持原有动态分发语义。
"""

from PySide6.QtCore import QPoint, QTimer

from ui.panel_layout import expanded_splitter_sizes, panel_toggle_text, run_splitter_sizes


def update_border_widget_positions(window):
    """更新浮动折叠按钮位置（基于 center_scroll 边缘定位）"""
    cw = window.centralWidget()
    if not cw:
        return
    cw_pos = cw.mapTo(window, QPoint(0, 0))
    center_pos = window.center_scroll.mapTo(window, QPoint(0, 0))
    center_h = window.center_scroll.height()

    if hasattr(window, 'btn_toggle_left'):
        x = center_pos.x() - 10
        y = center_pos.y() + (center_h - 40) // 2
        window.btn_toggle_left.move(x, y)

    if hasattr(window, 'btn_toggle_right'):
        x = center_pos.x() + window.center_scroll.width() - 10
        y = center_pos.y() + (center_h - 40) // 2
        window.btn_toggle_right.move(x, y)


def on_run_splitter_moved(window, *_args):
    window._run_splitter_user_adjusted = True


def apply_run_splitter_profile(window, profile: str, *, force: bool = False):
    if not hasattr(window, "run_splitter"):
        return
    if window._run_splitter_user_adjusted and not force:
        return
    sizes = run_splitter_sizes(profile)
    window.run_splitter.blockSignals(True)
    try:
        window.run_splitter.setSizes(sizes)
    finally:
        window.run_splitter.blockSignals(False)
    if force:
        window._run_splitter_user_adjusted = False


def toggle_left_panel(window):
    """折叠/展开左侧面板"""
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
    QTimer.singleShot(50, window._update_border_widget_positions)


def toggle_right_panel(window):
    """折叠/展开右侧面板"""
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
    QTimer.singleShot(50, window._update_border_widget_positions)
