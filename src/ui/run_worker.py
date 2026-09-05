# -*- coding: utf-8 -*-
"""Background run worker boundary for workflow execution."""

from __future__ import annotations

import threading
from typing import Callable, Mapping, Sequence

from PySide6.QtCore import Q_ARG, QMetaObject, Qt

from ui.run_actions import run_engine_mode


class RunWorker:
    """Own the background thread that dispatches a workflow run."""

    def __init__(
        self,
        engine,
        *,
        workflow_id: int,
        mode: str,
        param=None,
        runner: Callable[..., bool] | None = None,
        run_arg_overrides: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self._engine = engine
        self._workflow_id = workflow_id
        self._mode = mode
        self._param = param
        self._runner = runner or run_engine_mode
        self._run_arg_overrides = dict(run_arg_overrides or {})
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        try:
            self._runner(
                self._engine,
                workflow_id=self._workflow_id,
                mode=self._mode,
                param=self._param,
                run_arg_overrides=self._run_arg_overrides,
            )
        except RuntimeError as exc:
            self._emit_log(f"运行异常: {exc}")
        except Exception as exc:
            # F-07/F-01: run_engine_mode 内部已兜 except Exception，此处捕获的是
            # 预检/生命周期漏出的非 RuntimeError（如 SQLAlchemyError 族）。吞掉会让
            # threading.excepthook 在 windowed 构建下静默杀线程（UI 卡 "running"），
            # 至少记日志并把终态信息送回 UI。
            import logging

            logging.getLogger(__name__).warning("运行线程异常: %s", exc, exc_info=True)
            self._emit_log(f"运行异常: {exc}")

    def _emit_log(self, message: str) -> None:
        QMetaObject.invokeMethod(
            self._engine,
            "_emit_log",
            Qt.QueuedConnection,
            Q_ARG(str, message),
        )