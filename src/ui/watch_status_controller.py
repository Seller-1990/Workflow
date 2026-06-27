# -*- coding: utf-8 -*-
"""主窗口文件监听状态控制（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例；跨方法调用一律走
``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import logging

from ui.theme import get_colors

logger = logging.getLogger(__name__)


def sync_engine_watch(window, workflow) -> None:
    """根据 workflow.watch_enabled 启停该工作流的监听（M1: 不影响其它工作流）。

    engine.start_watch 内部已经做：先停本工作流旧监听，再按 watch_enabled / 目录有效性决定启停。
    这里只负责拉一次起、并把结果反馈到状态栏。
    """
    if workflow is None:
        # M1: 选中为空不再全局停止监听——其它工作流的监听照常运行；
        # 工作流被删除时由 _on_workflow_deleted 精确停掉对应监听。
        return
    try:
        started = window.engine.start_watch(workflow)
    except Exception as e:
        logger.warning("启动监听失败: %s", e)
        window.statusbar.showMessage(f"监听启动失败: {e}", 3000)
        return
    if started:
        folders = workflow.get_watch_folders() or []
        window.statusbar.showMessage(f"已开始监听 {len(folders)} 个目录", 3000)
    elif workflow.watch_enabled:
        # watch_enabled=True 但 start_watch 返回 False：目录无效 / 校验失败
        window.statusbar.showMessage("监听未启动（目录无效或为空）", 4000)


def restore_watches_on_startup(window) -> None:
    """M1: 应用启动时恢复所有 watch_enabled 工作流的监听；M7: 同步展示启动期配置自动修复。"""
    try:
        results = window.engine.restore_watches()
    except Exception as e:
        logger.warning("启动恢复监听失败: %s", e)
        return
    started = [name for name, ok in results if ok]
    failed = [name for name, ok in results if not ok]
    try:
        import database as _database
        repairs = list(getattr(_database, "LAST_WATCH_CONFIG_REPAIRS", []) or [])
    except Exception:
        repairs = []
    parts = []
    if started:
        parts.append(f"已恢复 {len(started)} 个工作流的文件监听")
    if failed:
        parts.append(f"{len(failed)} 个监听未能启动（详见日志）：{'、'.join(failed[:3])}")
    if repairs:
        parts.append(f"{len(repairs)} 个监听配置已被自动修正（详见 app.log）")
    if parts:
        window.statusbar.showMessage("；".join(parts), 8000)


def update_watch_indicator(window) -> None:
    """M1: 按当前监听集合刷新指示器（数量 + 目录 tooltip）。"""
    try:
        count = len(window._watching_workflows)
        if count:
            window._watch_indicator.setText(f"▶ 监听中 ({count})")
            window._refresh_watch_indicator_theme(running=True)
            lines: list[str] = []
            for wf_id, folders in window._watching_workflows.items():
                for folder in folders or []:
                    lines.append(str(folder))
            window._watch_indicator.setToolTip("\n".join(lines) or "文件监听状态")
        else:
            window._watch_indicator.setText("⏸ 未监听")
            window._refresh_watch_indicator_theme(running=False)
            window._watch_indicator.setToolTip("文件监听状态")
    except Exception as e:
        logger.warning("更新监听指示器失败: %s", e)


def on_watch_started(window, workflow_id: int, folders: list) -> None:
    """R2-#4 / M1: 监听启动 → 聚合到指示器"""
    window._watching_workflows[workflow_id] = list(folders or [])
    window._update_watch_indicator()


def on_watch_stopped(window, workflow_id: int) -> None:
    """R2-#4 / M1: 监听停止 → 从聚合中移除"""
    window._watching_workflows.pop(workflow_id, None)
    window._update_watch_indicator()


def refresh_watch_indicator_theme(window, running: bool) -> None:
    """R3-#6 / R4-#8: 按主题与运行态计算指示器颜色，保证 WCAG AA 对比度"""
    try:
        # V9.2：从主题模板取色（原硬编码 #248A3D/#34C759/#AEAEB2/#6E6E73）
        colors = get_colors(getattr(window, "_dark_mode", False))
        if running:
            color = colors["watch_active_aa"]
        else:
            color = colors["watch_inactive_strong"]
        window._watch_indicator.setStyleSheet(f"color: {color}; padding: 0 8px;")
    except Exception:
        pass
