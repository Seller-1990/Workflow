# -*- coding: utf-8 -*-
"""Background run worker boundary for workflow execution."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Q_ARG, QMetaObject, Qt

from ui.run_actions import run_engine_mode


class RunWorker:
    """Own the background thread used for a single workflow run.

    The public ``is_alive`` / ``join`` methods preserve the previous
    ``threading.Thread`` contract used by ``MainWindow.closeEvent``.
    """

    def __init__(
        self,
        engine,
        *,
        workflow_id: int,
        mode: str,
        param,
        runner: Callable = run_engine_mode,
    ) -> None:
        self._engine = engine
        self._workflow_id = workflow_id
        self._mode = mode
        self._param = param
        self._runner = runner
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            self._runner(
                self._engine,
                workflow_id=self._workflow_id,
                mode=self._mode,
                param=self._param,
            )
        except RuntimeError as exc:
            self._emit_log(f"运行异常: {exc}")

    def _emit_log(self, message: str) -> None:
        QMetaObject.invokeMethod(
            self._engine,
            "_emit_log",
            Qt.QueuedConnection,
            Q_ARG(str, message),
        )
