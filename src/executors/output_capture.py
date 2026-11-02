# -*- coding: utf-8 -*-
"""Python/BAT 管道的单一读取方，以及日志关闭前的输出分离。"""

import threading

from executors.result_policy import build_policy_extra


class _PipeCapture:
    def __init__(self, name, pipe, log_file, console, decode_line):
        self.name = name
        self.pipe = pipe
        self._log_file = log_file
        self._console = console
        self._decode_line = decode_line
        self._lock = threading.Lock()
        self._accepting = True
        self._log_active = False
        self.thread = None
        self.errors = []

    def start(self):
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _take_log_to_close(self):
        # 仅在状态锁内转移关闭权；外部 I/O 不得持有此锁。
        if self._accepting or self._log_active:
            return None
        log_file = self._log_file
        self._log_file = None
        return log_file

    def _close_log(self, log_file):
        if log_file is not None:
            try:
                log_file.close()
            except (OSError, ValueError) as exc:
                with self._lock:
                    self.errors.append(f"{self.name} 日志关闭失败: {exc}")

    def _sink_operation(self, kind, operation, *args):
        with self._lock:
            sink = self._log_file if kind == "日志" else self._console
            if not self._accepting or sink is None:
                return False
            if kind == "日志":
                self._log_active = True
        try:
            getattr(sink, operation)(*args)
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            with self._lock:
                action = "写入" if operation == "write" else "刷新"
                self.errors.append(f"{self.name} {kind}{action}失败: {exc}")
                self._console = None
                if kind == "日志":
                    self._accepting = False
            return False
        finally:
            if kind == "日志":
                with self._lock:
                    self._log_active = False
                    log_file = self._take_log_to_close()
                # 分离时仍在途的操作独占延迟关闭权，不阻塞执行器返回。
                self._close_log(log_file)

    def _write(self, decoded):
        # write/flush 分别授权；在途日志写入结束后不能再启动控制台操作。
        if not self._sink_operation("日志", "write", decoded):
            return
        if not self._sink_operation("日志", "flush"):
            return
        if self._sink_operation("控制台", "write", decoded):
            self._sink_operation("控制台", "flush")

    def _close_pipe(self):
        try:
            self.pipe.close()
        except (OSError, ValueError) as exc:
            with self._lock:
                self.errors.append(f"{self.name} 管道关闭失败: {exc}")

    def _read(self):
        try:
            for raw_line in iter(self.pipe.readline, b''):
                self._write(self._decode_line(raw_line))
        except (OSError, ValueError, RuntimeError) as exc:
            with self._lock:
                self.errors.append(f"{self.name} 管道读取失败: {exc}")
        finally:
            # 已启动的 reader 独占管道关闭权；主线程不能抢 buffered readline 的锁。
            self._close_pipe()

    def join(self, timeout):
        if self.thread is not None and self.thread.ident is not None:
            try:
                self.thread.join(timeout=timeout)
            except RuntimeError as exc:
                with self._lock:
                    self.errors.append(f"{self.name} 输出线程等待失败: {exc}")
        else:
            # Thread 构造/start 失败时没有读取方，当前线程负责释放这个管道。
            self.errors.append(f"{self.name} 输出线程未启动")
            self._close_pipe()

    def detach(self):
        with self._lock:
            # 快照先于撤销，避免另一条流分离期间 reader 退出而漏报。
            residual = self.is_alive()
            self._accepting = False
            self._console = None
            pending_log = self._log_active
            log_file = self._take_log_to_close()
        # 无在途写入时同步关闭；底层文件 close 本身的阻塞不受线程等待预算约束。
        self._close_log(log_file)
        with self._lock:
            errors = list(self.errors)
        if pending_log:
            errors.append(f"{self.name} 日志操作仍在途，已撤销后续输出；由在途操作返回后延迟关闭日志")
        return errors, residual

    def is_alive(self):
        return self.thread is not None and self.thread.is_alive()


class OutputCapture:
    """接管日志关闭权；有界等待后撤销输出，在途 I/O 完成后由原 owner 安全关闭。"""

    def __init__(self, proc, stdout_file, stderr_file, stdout_console, stderr_console, decode_line):
        self._streams = [
            _PipeCapture("stdout", proc.stdout, stdout_file, stdout_console, decode_line),
            _PipeCapture("stderr", proc.stderr, stderr_file, stderr_console, decode_line),
        ]
        self._cleanup_errors = []

    def start(self):
        for stream in self._streams:
            stream.start()

    def cleanup_failed(self, message):
        self._cleanup_errors.append(message)

    def finish(self, join_timeout):
        for stream in self._streams:
            stream.join(join_timeout)
        errors = list(self._cleanup_errors)
        residual = False
        for stream in self._streams:
            stream_errors, stream_residual = stream.detach()
            errors.extend(stream_errors)
            residual = residual or stream_residual
        if residual:
            errors.append("输出线程尚未结束，已撤销后续日志/控制台操作；未确认所有后台任务停止")
        if not errors:
            return {}
        note = "输出采集不完整；" + "；".join(errors)
        return build_policy_extra(
            manual_required=True,
            background_risk=True if residual or self._cleanup_errors else None,
            non_retryable=True,
            note=note,
        )
