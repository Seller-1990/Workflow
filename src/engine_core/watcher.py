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
MTIME_SCAN_MAX_SECONDS = 2.0


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
            for f in folders:
                if os.path.isdir(f):
                    try:
                        observer.schedule(handler, f, recursive=True)
                        scheduled += 1
                    except Exception as e:
                        logger.warning("watchdog schedule 失败 %s: %s", f, e)
            if scheduled == 0:
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
        try:
            initial_scan = scan_folder_mtimes_result(folders, warning_cb=self._log)
            last_success_folder_mtimes = (
                dict(initial_scan.folder_mtimes) if not initial_scan.aborted else {}
            )
            last_mtime = initial_scan.max_mtime if not initial_scan.aborted else -1.0
            pending_since: Optional[float] = None
            queued_while_running = False
            use_observer = self._observer is not None
            scan_degraded = initial_scan.aborted
            degraded_triggered = False
            if initial_scan.aborted:
                self._log("警告：初始 mtime 扫描提前终止，监听基线未确认；后续将保守按可能有变更处理")
            while not self._stop.is_set():
                if use_observer:
                    self._dirty.wait(timeout=cooldown)
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
                folder_mtimes = scan_result.folder_mtimes
                current_mtime = scan_result.max_mtime

                triggered = False
                conservative_trigger = False
                if scan_result.aborted:
                    if not scan_degraded:
                        self._log("警告：mtime 扫描提前终止，本轮不能确认“无变化”，将保守按可能有变更处理")
                    scan_degraded = True
                    if not degraded_triggered:
                        triggered = True
                        conservative_trigger = True
                else:
                    if scan_degraded:
                        self._log("mtime 扫描已恢复完整，重新按完整扫描结果判断变更")
                    scan_degraded = False
                    degraded_triggered = False
                    if mode == "all_folders_updated_since_success":
                        # 每个监听根目录都必须相对各自上次成功基线前进，避免被其它目录更大的 mtime 长期压制。
                        if folder_mtimes and all(
                            folder_mtimes.get(folder, 0.0) > last_success_folder_mtimes.get(folder, 0.0)
                            for folder in folder_mtimes
                        ):
                            triggered = True
                    else:
                        if current_mtime > last_mtime:
                            triggered = True

                if triggered:
                    if pending_since is None:
                        pending_since = time.time()
                    elif time.time() - pending_since >= settle:
                        if self._is_running():
                            if not queued_while_running:
                                self._log("检测到变更，但当前正在运行，待本轮结束后自动补触发")
                                queued_while_running = True
                            continue
                        if conservative_trigger:
                            degraded_triggered = True
                            self._log("mtime 扫描不完整，保守触发工作流运行")
                        else:
                            last_mtime = current_mtime
                            degraded_triggered = False
                        if mode == "all_folders_updated_since_success" and not conservative_trigger:
                            last_success_folder_mtimes = dict(folder_mtimes)
                        pending_since = None
                        queued_while_running = False
                        if not conservative_trigger:
                            self._log("检测到文件变更，触发工作流运行")
                        self._trigger(workflow_id, "watch")
                else:
                    pending_since = None
                    queued_while_running = False
        except Exception as e:
            logger.exception("监听线程致命异常: %s", e)
            self._log(f"警告：监听线程退出（{e}）。请重新启用监听。")
