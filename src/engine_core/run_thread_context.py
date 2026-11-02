"""Per-run thread-local pool, nesting depth and parent-run identity."""
import threading


# ============== R5: run 线程局部执行上下文 ==============

class _RunThreadContext(threading.local):
    """每个 run 线程的局部执行上下文（线程隔离）。

    - ``step_pool``: 本 run 的独立步骤池（首次并行批次惰性创建，run 结束统一关闭）
    - ``subworkflow_depth``: 本 run 的子工作流嵌套深度（根 run 为 0）
    - ``run_id``: 本线程正在执行的 run 的 run_id（F-18：供 run_sub_workflow
      读取作 parent_run_id；嵌套子工作流跑在自己线程上，天然拿到直接父 run）
    """

    def __init__(self) -> None:
        super().__init__()
        self.step_pool = None
        self.subworkflow_depth = 0
        self.run_id = None


_run_thread_ctx = _RunThreadContext()


def get_run_thread_context() -> _RunThreadContext:
    """返回当前 run 线程的局部上下文（线程隔离，天然支持并行/嵌套 run）。"""
    return _run_thread_ctx


def shutdown_step_pool(*, wait: bool = True, cancel_futures: bool = True) -> None:
    """R5: 关闭当前 run 线程绑定的步骤池（幂等，无池时 no-op）。

    由 run 收尾（engine._run finally）统一调用；``wait=True`` 等待已运行任务，
    ``cancel_futures=True`` 取消未启动任务。
    """
    ctx = _run_thread_ctx
    pool = getattr(ctx, "step_pool", None)
    if pool is None:
        return
    try:
        pool.shutdown(wait=wait, cancel_futures=cancel_futures)
    finally:
        ctx.step_pool = None
