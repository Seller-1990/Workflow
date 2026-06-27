# -*- coding: utf-8 -*-
"""取消信号工具：CA2 把 _watch_cancel 后台线程模式从 engine.py 抽离

设计要点：
- 不依赖 QObject / engine 状态；仅接受 is_cancelled 回调 + cancel_event
- 返回 Thread 对象，调用方 finally 中应 ``cancel_event.set()`` + ``thread.join(timeout=...)``
- 轮询粒度可调（默认 0.2s）
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


def install_cancel_watcher(
    is_cancelled_cb: Callable[[], bool],
    cancel_event: threading.Event,
    poll_interval: float = 0.2,
) -> threading.Thread:
    """启动后台线程，将 ``is_cancelled_cb()`` 的取消请求映射到 ``cancel_event``

    Args:
        is_cancelled_cb: 通常是 ``lambda: engine.is_cancelled``
        cancel_event: 传给执行器的 ``threading.Event``
        poll_interval: 轮询间隔（秒），默认 0.2

    Returns:
        已启动的 daemon Thread。调用方负责在 finally 中
        ``cancel_event.set()`` + ``thread.join(timeout=1)``
    """
    def _watch():
        # 注意：cancel_event.wait(poll_interval) 在 event 被 set 时立即返回，
        # 所以这里既轮询 is_cancelled 又能响应 finally 中的 cancel_event.set()
        while not cancel_event.is_set():
            if is_cancelled_cb():
                cancel_event.set()
                break
            cancel_event.wait(poll_interval)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t
