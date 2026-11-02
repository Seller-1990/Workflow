# -*- coding: utf-8 -*-
"""Own transient run-history folding and log-space allocation."""

def on_run_splitter_moved(window, *_args):
    window._run_splitter_user_adjusted = True
    saved = getattr(window, "_run_history_expanded_layout", None)
    if saved is not None and not window.run_history.section.body.isHidden():
        # 折叠动画尚未锁定父面板，保存此时实际接受的手动位置。
        _, minimum, maximum, _ = saved
        window._run_history_expanded_layout = (
            window.run_splitter.sizes(), minimum, maximum, True,
        )


def begin_run_history_collapse(window) -> None:
    """记住展开布局，动画收起完成前不改变父 splitter 尺寸。"""
    if getattr(window, "_run_history_expanded_layout", None) is not None:
        return
    history = window.run_history
    window._run_history_expanded_layout = (
        window.run_splitter.sizes(), history.minimumHeight(), history.maximumHeight(),
        window._run_splitter_user_adjusted,
    )


def _restore_run_history_layout(window) -> None:
    saved = getattr(window, "_run_history_expanded_layout", None)
    if saved is None:
        return
    sizes, minimum, maximum, user_adjusted = saved
    splitter = window.run_splitter
    history = window.run_history
    previous = splitter.blockSignals(True)
    try:
        history.setMaximumHeight(maximum)
        history.setMinimumHeight(minimum)
        splitter.setSizes(sizes)
    finally:
        splitter.blockSignals(previous)
    window._run_splitter_user_adjusted = user_adjusted
    del window._run_history_expanded_layout


def on_run_history_collapsed(window, collapsed: bool, *, restore_layout, begin_collapse):
    """折叠完成后把腾出的空间交给日志面板。"""
    if not collapsed:
        restore_layout(window)
        return
    begin_collapse(window)
    history = window.run_history
    splitter = window.run_splitter
    sizes = splitter.sizes()
    margins = history.layout().contentsMargins()
    height = history.section.collapsed_height + margins.top() + margins.bottom()
    previous = splitter.blockSignals(True)
    try:
        history.setFixedHeight(height)
        splitter.setSizes([height, max(0, sum(sizes) - height)])
    finally:
        splitter.blockSignals(previous)


def apply_run_splitter_profile(window, profile: str, *, force: bool, restore_layout, profile_sizes):
    if not hasattr(window, "run_splitter"):
        return
    if getattr(window, "_run_history_expanded_layout", None) is not None:
        if window.run_history.section.is_collapsed:
            return
        restore_layout(window)
    if window._run_splitter_user_adjusted and not force:
        return
    sizes = profile_sizes(profile)
    window.run_splitter.blockSignals(True)
    try:
        window.run_splitter.setSizes(sizes)
    finally:
        window.run_splitter.blockSignals(False)
    if force:
        window._run_splitter_user_adjusted = False


def ensure_run_log_visible(window, *, visible_sizes) -> None:
    """确保运行页中的实时日志区域不会被 splitter 压到不可见。"""
    if not hasattr(window, "run_splitter"):
        return
    if getattr(window, "_run_history_expanded_layout", None) is not None:
        return
    sizes = visible_sizes(
        window.run_splitter.sizes(),
        available_height=window.run_splitter.height(),
    )
    if sizes:
        window.run_splitter.blockSignals(True)
        try:
            window.run_splitter.setSizes(sizes)
        finally:
            window.run_splitter.blockSignals(False)
        window._run_splitter_user_adjusted = False
