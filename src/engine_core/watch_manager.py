# -*- coding: utf-8 -*-
"""监听管理器：M1 多 watcher 管理从 engine.py 抽离

设计要点：
- 不依赖 QObject / QApplication，便于 headless CLI 复用
- 通过回调与上层引擎解耦：
    log_cb(message): 转发日志
    trigger_cb(workflow_id, reason): 监听命中后触发工作流运行
    is_running_cb() -> bool: 引擎是否正在执行
    emit_started_cb(workflow_id, folders): 监听启动信号（R2-#4 指示灯）
    emit_stopped_cb(workflow_id): 监听停止信号（R2-#4 指示灯）
    validate_folders_cb(folders) -> list[str]: 校验监听目录
    detect_conflicts_cb(folders, steps) -> list[str]: 监听目录与输出目录重叠检测
    get_steps_cb(workflow_id) -> list[Step]: 读取工作流步骤
- 回调闭包应由 engine.py 在引擎模块内定义（late-bound），保持
  ``engine.get_steps_by_workflow`` / ``engine.detect_watch_output_conflicts``
  等模块级 monkeypatch 语义不变
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from constants import WATCH_COOLDOWN_DEFAULT, WATCH_SETTLE_DEFAULT
from engine_core.watcher import FileWatcher

if TYPE_CHECKING:
    from models import Workflow

logger = logging.getLogger(__name__)


class WatchManager:
    """按 workflow_id 管理多个 FileWatcher（M1: 多实例互不干扰）"""

    def __init__(
        self,
        *,
        log_cb: Callable[[str], None],
        trigger_cb: Callable[[int, str], None],
        is_running_cb: Callable[[], bool],
        emit_started_cb: Callable[[int, list], None],
        emit_stopped_cb: Callable[[int], None],
        validate_folders_cb: Callable[[list], list],
        detect_conflicts_cb: Callable[[list, list], list],
        get_steps_cb: Callable[[int], list],
    ) -> None:
        self._log_cb = log_cb
        self._trigger_cb = trigger_cb
        self._is_running_cb = is_running_cb
        self._emit_started_cb = emit_started_cb
        self._emit_stopped_cb = emit_stopped_cb
        self._validate_folders_cb = validate_folders_cb
        self._detect_conflicts_cb = detect_conflicts_cb
        self._get_steps_cb = get_steps_cb
        self._lock = threading.RLock()
        # CA2: 监听器子系统抽到 engine_core.watcher
        # M1: 单 watcher 升级为按 workflow_id 的多实例，互不干扰；
        # 切换 UI 选中不再影响其它工作流的监听。
        self.watchers: dict[int, FileWatcher] = {}

    def _make_watcher(self) -> FileWatcher:
        """创建绑定到本引擎的 FileWatcher。

        注意：is_running_cb 是引擎级状态——任一工作流运行期间，其它监听的
        settle 到期变更会被按"与运行重叠"吞并（引擎同一时刻只允许一个顶层运行，
        宁可少跑也不排队补跑，避免意外连环运行）。
        """
        return FileWatcher(
            log_cb=self._log_cb,
            trigger_cb=self._trigger_cb,
            is_running_cb=self._is_running_cb,
        )

    def start_watch(self, workflow: "Workflow") -> bool:
        """启动该工作流的文件监听（M1: 每工作流独立 watcher，互不影响）

        R2-#4: 启停信号在状态切换时发出，UI 据此更新持续指示灯。
        幂等：若该 workflow 已按相同目录/参数监听且线程存活，则跳过 stop+restart 抖动。
        """
        with self._lock:
            return self._start_watch_locked(workflow)

    def _start_watch_locked(self, workflow: "Workflow") -> bool:
        existing = self.watchers.get(workflow.id)
        prev_folders = list(getattr(existing, "_folders", []) or [])
        prev_cooldown = int(getattr(existing, "_cooldown", 0) or 0)
        prev_settle = int(getattr(existing, "_settle", 0) or 0)
        prev_mode = str(getattr(existing, "_mode", "") or "")
        prev_thread = getattr(existing, "_thread", None)
        new_folders = list(workflow.get_watch_folders() or [])
        # R6-#5: DB 中若存在脏数据（字符串/None/异常类型）也兜底为默认值
        def _safe_int(value, default: int, minimum: int = 0) -> int:
            try:
                v = int(value) if value is not None else default
            except (TypeError, ValueError):
                v = default
            return max(minimum, v)
        # L3: 默认值收敛到 constants，避免与 config.DEFAULT_CONFIG 漂移
        new_cooldown = _safe_int(workflow.cooldown_seconds, default=WATCH_COOLDOWN_DEFAULT, minimum=1)
        new_settle = _safe_int(workflow.settle_seconds, default=WATCH_SETTLE_DEFAULT, minimum=0)
        new_mode = workflow.watch_mode or "any_change"
        if (
            workflow.watch_enabled
            and existing is not None
            and sorted(prev_folders) == sorted(new_folders)
            and prev_cooldown == new_cooldown
            and prev_settle == new_settle
            and prev_mode == new_mode
            # H4 修复：线程对象残留但已死亡（_loop 致命异常退出）时不得短路，
            # 否则监听静默失效且无法通过重选工作流/重存配置恢复。
            and prev_thread is not None
            and prev_thread.is_alive()
        ):
            return True  # 已在监听同样目标 + 同样参数且线程存活，无需重启

        # R4-#1: stop_watch 内部已发 watch_stopped；不再重复 emit，避免指示器抖动
        # M1: 只停本工作流的旧监听，不再波及其它工作流
        self.stop_watch(workflow.id)
        if workflow.id in self.watchers:
            self._log_cb("警告：旧的文件监听线程仍在退出中，本次重启已取消")
            return False

        if not workflow.watch_enabled:
            return False
        if not new_folders:
            return False
        try:
            folders = self._validate_folders_cb(new_folders)
        except ValueError as e:
            self._log_cb(f"监听未启动: {e}")
            return False
        conflicts = self._detect_conflicts_cb(
            folders,
            self._get_steps_cb(workflow.id),
        )
        if conflicts:
            joined = "；".join(conflicts)
            self._log_cb(f"监听未启动: 监听目录与工作流输出目录重叠：{joined}")
            return False
        watcher = self._make_watcher()
        ok = watcher.start(
            workflow_id=workflow.id,
            folders=folders,
            cooldown=new_cooldown,
            settle=new_settle,
            mode=new_mode,
        )
        if ok:
            self.watchers[workflow.id] = watcher
            try:
                self._emit_started_cb(workflow.id, folders)
            except Exception:
                pass
        return ok

    def stop_watch(self, workflow_id: int | None = None, join_timeout: float = 1.0):
        """停止文件监听。

        M1: ``workflow_id=None`` 停止全部监听（关闭/退出场景）；
        指定 workflow_id 时只停该工作流的监听。
        """
        with self._lock:
            self._stop_watch_locked(workflow_id, join_timeout)

    def _stop_watch_locked(self, workflow_id: int | None = None, join_timeout: float = 1.0):
        if workflow_id is None:
            target_ids = list(self.watchers.keys())
        elif workflow_id in self.watchers:
            target_ids = [workflow_id]
        else:
            return
        for wf_id in target_ids:
            watcher = self.watchers.get(wf_id)
            if watcher is None:
                continue
            previous_thread = getattr(watcher, "_thread", None)
            was_watching = previous_thread is not None
            watcher.stop(join_timeout)
            current_thread = getattr(watcher, "_thread", None)
            old_thread_alive = bool(
                previous_thread is not None
                and getattr(previous_thread, "is_alive", lambda: False)()
            )
            stopped = (
                current_thread is None
                or current_thread is not previous_thread
                or not old_thread_alive
            )
            if stopped:
                # 线程未能退出时保留句柄，FileWatcher.start 会拒绝并行重启
                self.watchers.pop(wf_id, None)
            if was_watching and stopped:
                try:
                    self._emit_stopped_cb(wf_id)
                except Exception:
                    pass

    def restore_watches(self) -> list[tuple[str, bool]]:
        """应用启动时恢复所有 watch_enabled 工作流的监听（M1）。

        Returns:
            [(工作流名称, 是否启动成功), ...]，读取工作流列表失败时返回空列表。
        """
        results: list[tuple[str, bool]] = []
        try:
            # 延迟导入：每次调用时解析 database.list_workflows 模块属性，
            # 保持测试 monkeypatch(database, "list_workflows", ...) 语义
            from database import list_workflows
            workflows = list_workflows()
        except Exception as e:
            logger.warning("恢复监听失败：读取工作流列表出错: %s", e)
            return results
        for wf in workflows:
            if not getattr(wf, "watch_enabled", False):
                continue
            try:
                ok = self.start_watch(wf)
            except Exception as e:
                logger.warning("恢复工作流监听失败: %s: %s", getattr(wf, "name", wf), e)
                ok = False
            results.append((getattr(wf, "name", str(getattr(wf, "id", "?"))), bool(ok)))
        return results
