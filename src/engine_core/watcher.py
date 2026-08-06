# -*- coding: utf-8 -*-
"""文件监听器：CA2 把 watch 子系统从 engine.py 抽离

设计要点：
- 不依赖 QObject / QApplication，便于 headless CLI 复用
- 通过回调与上层引擎解耦（log_cb / trigger_cb / is_running_cb）
- HA4：优先 watchdog 事件驱动；watchdog 不可用 / schedule 失败时回退 mtime 轮询
- H5：外层 try/except 防止驱动器拔出等异常导致线程崩溃
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MTIME_SCAN_MAX_DEPTH: int | None = None
MTIME_SCAN_MAX_DIRECTORIES = 20000
MTIME_SCAN_MAX_SECONDS = 10.0


@dataclass(frozen=True)
class MtimeScanResult:
    folder_mtimes: dict[str, float]
    aborted: bool = False
    warning: Optional[str] = None
    scanned_directories: int = 0

    @property
    def max_mtime(self) -> float:
        return max(self.folder_mtimes.values()) if self.folder_mtimes else 0.0


def validate_watch_folders(folders: list[str]) -> list[str]:
    """校验监听目录并返回去重后的绝对路径列表"""
    if not folders:
        raise ValueError("未配置监听目录")

    system_root = Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "")
    protected_roots = {
        p.resolve()
        for p in (
            system_root,
            Path(os.environ.get("ProgramFiles") or ""),
            Path(os.environ.get("ProgramFiles(x86)") or ""),
        )
        if str(p).strip()
    }

    validated: list[str] = []
    seen: set[str] = set()
    for raw_folder in folders:
        folder = (raw_folder or "").strip()
        if not folder:
            continue

        path = Path(folder).expanduser().resolve()
        path_str = str(path)
        if path_str in seen:
            continue
        if not path.exists():
            raise ValueError(f"监听目录不存在: {path}")
        if not path.is_dir():
            raise ValueError(f"监听路径不是目录: {path}")
        if path.parent == path:
            raise ValueError(f"不允许监听磁盘根目录: {path}")
        if any(path == protected or protected in path.parents for protected in protected_roots):
            raise ValueError(f"不允许监听系统目录: {path}")

        seen.add(path_str)
        validated.append(path_str)

    if not validated:
        raise ValueError("未配置有效的监听目录")
    return validated


def _describe_mtime_scan_scope(max_depth: int | None = MTIME_SCAN_MAX_DEPTH) -> str:
    depth_desc = "无限" if max_depth is None else f"{max_depth}层"
    return (
        f"深度={depth_desc}, 目录上限={MTIME_SCAN_MAX_DIRECTORIES}, "
        f"单轮耗时上限={MTIME_SCAN_MAX_SECONDS:.1f}s"
    )


def scan_folder_mtimes_result(
    folders: list,
    max_depth: int | None = MTIME_SCAN_MAX_DEPTH,
    warning_cb: Callable[[str], None] | None = None,
) -> MtimeScanResult:
    """扫描每个监听根目录聚合后的最大修改时间（os.scandir 递归）

    H4：去掉跨调用的缓存以保证正确性。
    为避免深层目录被静默漏扫，默认不再限制深度；但保留目录数量与单轮耗时保护，
    防止大目录树在轮询模式下无限放大扫描成本。
    """
    folder_mtimes: dict = {}
    scanned_directories = 0
    deadline = time.perf_counter() + MTIME_SCAN_MAX_SECONDS
    aborted = False

    def _should_abort() -> bool:
        return scanned_directories >= MTIME_SCAN_MAX_DIRECTORIES or time.perf_counter() >= deadline

    def _scan_dir(root_key: str, current_path: str, depth: int):
        nonlocal scanned_directories, aborted
        if aborted:
            return
        if _should_abort():
            aborted = True
            return
        scanned_directories += 1
        try:
            with os.scandir(current_path) as it:
                for entry in it:
                    if aborted:
                        return
                    try:
                        if entry.is_file(follow_symlinks=False):
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            if mtime > folder_mtimes.get(root_key, 0.0):
                                folder_mtimes[root_key] = mtime
                        elif entry.is_dir(follow_symlinks=False) and (
                            max_depth is None or depth < max_depth
                        ):
                            _scan_dir(root_key, entry.path, depth + 1)
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass

    for folder in folders:
        if not os.path.isdir(folder):
            continue
        folder_str = str(folder)
        folder_mtimes[folder_str] = 0.0
        _scan_dir(folder_str, folder, 0)
        if aborted:
            break

    warning: Optional[str] = None
    if aborted:
        warning = (
            f"警告：mtime 扫描提前终止：{_describe_mtime_scan_scope(max_depth)}；"
            f"已扫描目录={scanned_directories}"
        )
        logger.warning(warning)
        if warning_cb:
            warning_cb(warning)

    return MtimeScanResult(
        folder_mtimes=folder_mtimes,
        aborted=aborted,
        warning=warning,
        scanned_directories=scanned_directories,
    )


def scan_folder_mtimes(
    folders: list,
    max_depth: int | None = MTIME_SCAN_MAX_DEPTH,
    warning_cb: Callable[[str], None] | None = None,
) -> dict:
    return scan_folder_mtimes_result(
        folders,
        max_depth=max_depth,
        warning_cb=warning_cb,
    ).folder_mtimes


def scan_mtime(folders: list) -> float:
    """扫描目录最大修改时间"""
    mtimes = scan_folder_mtimes(folders)
    return max(mtimes.values()) if mtimes else 0.0


class FileWatcher:
    """文件监听器

    回调约定：
        log_cb(message: str): 转发日志（线程安全由调用方负责）
        trigger_cb(workflow_id: int, reason: str): 触发工作流运行
        is_running_cb() -> bool: 引擎是否正在执行
    """

    def __init__(
        self,
        log_cb: Callable[[str], None],
        trigger_cb: Callable[[int, str], None],
        is_running_cb: Callable[[], bool],
    ) -> None:
        self._log = log_cb
        self._trigger = trigger_cb
        self._is_running = is_running_cb
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._observer = None  # watchdog Observer or None
        # R2-#4: 记录当前监听目标，供外部幂等判断 + 状态指示
        self._workflow_id: Optional[int] = None
        self._folders: list[str] = []
        # R5-#2: 同时记录 cooldown/settle/mode，幂等判断纳入参数变化
        self._cooldown: int = 0
        self._settle: int = 0
        self._mode: str = ""

    # ── 公开 API ──
    def start(
        self,
        workflow_id: int,
        folders: list[str],
        cooldown: int,
        settle: int,
        mode: str,
    ) -> bool:
        """启动监听。folders 应已经过 validate_watch_folders。"""
        self.stop()
        if self._thread is not None and self._thread.is_alive():
            self._log("警告：旧的文件监听线程仍在退出中，本次重启已取消")
            return False
        self._stop.clear()
        self._dirty.clear()
        self._workflow_id = workflow_id
        self._folders = list(folders)
        # R5-#2: 同步缓存当前 watcher 启动参数
        self._cooldown = int(cooldown)
        self._settle = int(settle)
        self._mode = str(mode or "")
        self._start_watchdog_observer(folders)
        self._thread = threading.Thread(
            target=self._loop,
            args=(workflow_id, folders, cooldown, settle, mode),
            daemon=True,
        )
        self._thread.start()
        observer_mode = (
            "事件驱动 (watchdog)"
            if self._observer
            else f"轮询 (mtime, {_describe_mtime_scan_scope()})"
        )
        self._log(f"已启动文件监听 [{observer_mode}]")
        return True

    def stop(self, join_timeout: float = 1.0) -> None:
        thread = self._thread
        thread_stopped = True
        if thread and thread.is_alive():
            self._stop.set()
            self._dirty.set()  # 唤醒可能阻塞在 dirty.wait 的循环
            thread.join(timeout=max(0.0, float(join_timeout or 0.0)))
            if thread.is_alive():
                self._log("警告：文件监听线程未能及时退出")
                thread_stopped = False
        if thread_stopped:
            self._thread = None
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=max(0.5, float(join_timeout or 0.5)))
            except Exception as e:
                logger.warning("watchdog Observer 关闭异常: %s", e)
            if not getattr(self._observer, "is_alive", lambda: False)():
                self._observer = None
        if self._thread is None and self._observer is None:
            # R2-#4: 停止后清空目标记录
            self._workflow_id = None
            self._folders = []
            self._cooldown = 0
            self._settle = 0
            self._mode = ""

    # ── 内部 ──
    def _start_watchdog_observer(self, folders: list[str]) -> None:
        """优先 watchdog 事件驱动；失败时 silent 回退到 mtime 轮询"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            dirty = self._dirty

            class _Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    dirty.set()

            observer = Observer()
            handler = _Handler()
            scheduled = 0
            failed: list[str] = []
            eligible = [f for f in folders if os.path.isdir(f)]
            for f in folders:
                if os.path.isdir(f):
                    try:
                        observer.schedule(handler, f, recursive=True)
                        scheduled += 1
                    except Exception as e:
                        logger.warning("watchdog schedule 失败 %s: %s", f, e)
                        failed.append(str(f))
            if scheduled == 0:
                return
            if failed or scheduled < len(eligible):
                self._log(
                    "警告：部分监听目录未能启用事件驱动，已整体回退 mtime 轮询："
                    + "；".join(failed)
                )
                self._observer = None
                return
            observer.start()
            self._observer = observer
        except ImportError:
            return
        except Exception as e:
            logger.warning("watchdog 启动异常，回退 mtime 轮询: %s", e)
            self._observer = None

    def _loop(
        self,
        workflow_id: int,
        folders: list[str],
        cooldown: int,
        settle: int,
        mode: str,
    ) -> None:
        """监听主循环。

        H1/H2 修复后的状态机：
        - baseline_valid=False 时（初始/刷新扫描中止），下一次完整扫描只重建基线、不触发，
          避免"扫描不完整→保守触发"的无变更误跑。
        - pending 窗口内只要出现过运行（run_active_during_pending），settle 到期后一律按
          运行输出吞并并刷新基线，闭合"运行刚结束、settle 才到期→立刻重跑"的竞态。
        """
        try:
            initial_scan = scan_folder_mtimes_result(folders, warning_cb=self._log)
            baseline_valid = not initial_scan.aborted
            last_success_folder_mtimes = (
                dict(initial_scan.folder_mtimes) if baseline_valid else {}
            )
            last_mtime = initial_scan.max_mtime if baseline_valid else 0.0
            pending_since: Optional[float] = None
            run_active_during_pending = False
            use_observer = self._observer is not None
            scan_degraded = initial_scan.aborted
            if initial_scan.aborted:
                self._log(
                    "警告：初始 mtime 扫描提前终止，监听基线未建立；"
                    "待完整扫描后重建基线，期间不会自动触发"
                )

            def _refresh_baseline(context: str) -> bool:
                """全量重扫并刷新基线；中止时标记基线不可信，等待下一次完整扫描重建。"""
                nonlocal baseline_valid, last_mtime, last_success_folder_mtimes, scan_degraded
                try:
                    refresh_scan = scan_folder_mtimes_result(folders, warning_cb=self._log)
                except Exception as e:
                    logger.warning("%s基线刷新异常: %s", context, e)
                    self._log(f"警告：{context}基线刷新失败，基线暂不可信，待完整扫描后重建：{e}")
                    baseline_valid = False
                    return False
                if refresh_scan.aborted:
                    scan_degraded = True
                    baseline_valid = False
                    self._log(f"警告：{context} mtime 扫描提前终止，基线暂不可信，待完整扫描后重建")
                    return False
                baseline_valid = True
                last_mtime = refresh_scan.max_mtime
                if mode == "all_folders_updated_since_success":
                    last_success_folder_mtimes = dict(refresh_scan.folder_mtimes)
                return True

            while not self._stop.is_set():
                if use_observer:
                    # P1-A: observer 模式下 watchdog 已在真实文件事件（及 stop 唤醒）时
                    # dispatch 置位 dirty；wait 超时说明 cooldown 内无任何事件——
                    # 跳过本轮全树扫描，避免空闲时每 cooldown 仍无条件递归扫整棵监听树。
                    if not self._dirty.wait(timeout=cooldown):
                        continue
                    if self._stop.is_set():
                        break
                    self._dirty.clear()
                else:
                    if self._stop.wait(cooldown):
                        break
                try:
                    scan_result = scan_folder_mtimes_result(folders, warning_cb=self._log)
                except Exception as e:
                    logger.warning("监听扫描异常: %s", e)
                    self._log(f"警告：监听扫描异常（将在下一轮重试）：{e}")
                    continue

                if scan_result.aborted:
                    # H2 修复：扫描不完整时不再"保守触发"——无法确认变更就不替用户启动工作流，
                    # 只告警并等待扫描恢复完整。
                    if not scan_degraded:
                        self._log(
                            "警告：mtime 扫描提前终止，无法确认文件变更，本轮不会触发；"
                            "建议缩小监听目录范围"
                        )
                    scan_degraded = True
                    continue
                if scan_degraded:
                    self._log("mtime 扫描已恢复完整，重新按完整扫描结果判断变更")
                    scan_degraded = False

                folder_mtimes = scan_result.folder_mtimes
                current_mtime = scan_result.max_mtime

                if not baseline_valid:
                    # H2 修复：基线缺失/失效后，首个完整扫描只重建基线，不视为变更。
                    last_mtime = current_mtime
                    last_success_folder_mtimes = dict(folder_mtimes)
                    baseline_valid = True
                    pending_since = None
                    run_active_during_pending = False
                    self._log("监听基线已重新建立（此前扫描不完整），本轮不触发")
                    continue

                if mode == "all_folders_updated_since_success":
                    # 每个监听根目录都必须相对各自上次成功基线前进，避免被其它目录更大的 mtime 长期压制。
                    triggered = bool(folder_mtimes) and all(
                        folder_mtimes.get(folder, 0.0) > last_success_folder_mtimes.get(folder, 0.0)
                        for folder in folder_mtimes
                    )
                else:
                    triggered = current_mtime > last_mtime

                if not triggered:
                    pending_since = None
                    run_active_during_pending = False
                    continue

                if pending_since is None:
                    pending_since = time.time()
                    run_active_during_pending = self._is_running()
                    continue

                # H1 修复：pending 等待期间持续记录"是否有运行发生过"，
                # 即使 settle 到期时运行已结束，也能识别出变更来自该运行。
                run_active_during_pending = run_active_during_pending or self._is_running()
                if time.time() - pending_since < settle:
                    continue

                if self._is_running() or run_active_during_pending:
                    # 工作流运行期间（或 pending 窗口内曾有运行）产生的文件事件，
                    # 通常来自该运行自身的输出。吞并变更：刷新基线并清掉 pending，不补跑。
                    if self._is_running():
                        message = "检测到运行期间文件变更，已刷新监听基线，不在本轮结束后补触发"
                    else:
                        message = "检测到的文件变更与刚结束的运行重叠，已刷新监听基线，不自动补跑"
                    if _refresh_baseline("监听运行中"):
                        self._log(message)
                    pending_since = None
                    run_active_during_pending = False
                    continue

                # 真实外部变更：先推进基线，再触发
                last_mtime = current_mtime
                if mode == "all_folders_updated_since_success":
                    last_success_folder_mtimes = dict(folder_mtimes)
                pending_since = None
                run_active_during_pending = False
                self._log("检测到文件变更，触发工作流运行")
                trigger_ok = self._trigger(workflow_id, "watch")
                # 触发的运行在本线程同步执行完毕，重扫一次把运行输出纳入基线，
                # 避免运行自身的产物在下一轮被当作新变更。
                if _refresh_baseline("监听触发后"):
                    if trigger_ok:
                        self._log("监听触发后已刷新文件变更基线")
                    else:
                        self._log("监听触发失败后已刷新文件变更基线，避免同一变更重复触发")
        except Exception as e:
            logger.exception("监听线程致命异常: %s", e)
            self._log(f"警告：监听线程退出（{e}）。请重新启用监听。")
