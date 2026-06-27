#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流管理应用入口"""

import argparse
import os
import sys
from pathlib import Path

# 添加 src 目录到路径
src_dir = Path(__file__).resolve().parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Qt/UI/config imports are intentionally delayed until after argparse handles
# ``--help``.  Importing ``config`` creates app-data directories, so keeping
# the module import-light makes launcher help safe for clean release probes.


def _run_self_check(qt_args: list[str]) -> int:
    """Run release smoke checks without entering the GUI event loop."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    try:
        from ui import MainWindow
    except ImportError as e:
        print(f"导入 UI 模块失败: {e}")
        print("请确保已安装所有依赖: pip install PySide6")
        return 1

    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    try:
        from config import APP_DATA_DIR

        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = APP_DATA_DIR / ".self_check_write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        record("app_data_writable", True, str(APP_DATA_DIR))
    except Exception as exc:
        record("app_data_writable", False, str(exc))

    try:
        import certifi

        ca_path = Path(certifi.where())
        record("certifi_ca_bundle", ca_path.is_file(), str(ca_path))
    except Exception as exc:
        record("certifi_ca_bundle", False, str(exc))

    try:
        import requests  # noqa: F401
        from executors.excel_executor import ExcelExecutor  # noqa: F401
        from executors.powerbi_executor import PowerBIExecutor  # noqa: F401
        from executors.python_executor import PythonExecutor  # noqa: F401
        from engine import WorkflowEngine  # noqa: F401

        record("critical_imports", True, "engine/executors/requests")
    except Exception as exc:
        record("critical_imports", False, str(exc))

    try:
        import database

        database.init_db()
        record("database_init", True, str(database.DATABASE_PATH))
    except Exception as exc:
        record("database_init", False, str(exc))

    app = QApplication.instance()
    created_app = False
    try:
        if app is None:
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
            app = QApplication([sys.argv[0], *qt_args])
            created_app = True
        window = MainWindow()
        window.close()
        record("main_window_construct", True, os.environ.get("QT_QPA_PLATFORM", ""))
    except Exception as exc:
        record("main_window_construct", False, str(exc))
    finally:
        if created_app and app is not None:
            app.quit()

    failed = False
    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"[self-check] {status} {name}: {detail}", flush=True)
        failed = failed or not ok
    return 1 if failed else 0


def _try_dispatch_cli(argv: list[str]) -> int | None:
    """打包后让 exe 也能执行 CLI 子命令。

    `build.spec` 的 `console=False` 让 windowed exe 没有自带控制台，
    但用户在终端里执行 `Workflow.exe list` 时，argv 仍然会传进来。
    这里通过判断首个非选项参数是否为 CLI 子命令来决定是否转发到 `cli.main()`。
    转发前用 Win32 AttachConsole(ATTACH_PARENT_PROCESS) 附加到父控制台，
    让 stdout/stderr 重新可见。
    """
    if not argv:
        return None
    # 跳过选项参数（--xxx / -x），找到首个非选项 token
    head = next((a for a in argv if a and not a.startswith("-")), None)
    if head is None:
        return None
    try:
        from cli import CLI_COMMANDS
    except ImportError:
        return None
    if head not in CLI_COMMANDS:
        return None
    # 仅 Windows 需要附加控制台；非 Windows 直接转发即可
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            ATTACH_PARENT_PROCESS = -1
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.AttachConsole.restype = wintypes.BOOL
            kernel32.AttachConsole.argtypes = [wintypes.DWORD]
            if kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                # 重定向 std 流到附加的控制台
                STD_OUTPUT_HANDLE = -11
                STD_ERROR_HANDLE = -12
                kernel32.GetStdHandle.restype = wintypes.HANDLE
                kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
                # 用 os.fdopen 把文件描述符封装成 Python 文本流
                conout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                conerr = kernel32.GetStdHandle(STD_ERROR_HANDLE)
                # os.fdopen 需要 int fd；通过 msvcrt 把 HANDLE 转 fd
                try:
                    import msvcrt
                    fd_out = msvcrt.open_osfhandle(conout, 0)
                    fd_err = msvcrt.open_osfhandle(conerr, 0)
                    sys.stdout = os.fdopen(fd_out, "w", encoding="utf-8", buffering=1, closefd=False)
                    sys.stderr = os.fdopen(fd_err, "w", encoding="utf-8", buffering=1, closefd=False)
                except Exception:
                    # 退化：直接用 print 写到 stderr
                    pass
        except Exception as exc:
            # 附加控制台失败不阻断 CLI；输出可能丢失，但命令仍执行
            sys.stderr.write(f"[cli] AttachConsole 失败: {exc}\n")
    # 转发到 cli.main
    try:
        from cli import main as cli_main
        cli_main(argv)
        return 0
    except SystemExit as e:
        return int(getattr(e, "code", 0) or 0)
    except Exception as exc:
        sys.stderr.write(f"[cli] 执行失败: {exc}\n")
        return 1


def main(argv=None):
    """主函数"""
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    # 打包后路由：首个非选项参数若是 CLI 子命令（list/run/...）则转发到 cli.main
    cli_rc = _try_dispatch_cli(raw_argv)
    if cli_rc is not None:
        return cli_rc

    parser = argparse.ArgumentParser(
        description="Workflow desktop application launcher.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--smoke", action="store_true", help="启动后立即退出（用于冒烟验证）")
    parser.add_argument("--self-check", action="store_true", help="执行发布自检后退出")
    args, qt_args = parser.parse_known_args(raw_argv)

    if args.self_check:
        return _run_self_check(qt_args)

    import logging
    from logging.handlers import RotatingFileHandler

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication
    from config import APP_NAME, APP_VERSION, ICON_PATH, LOG_DIR

    # 打包后的 GUI 没有可见 stderr，logger.warning 在生产环境完全不可见；
    # 落盘到 LOG_DIR/app.log（config 导入时已创建 LOG_DIR）。
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=[
                RotatingFileHandler(
                    LOG_DIR / "app.log",
                    maxBytes=1_000_000,
                    backupCount=2,
                    encoding="utf-8",
                )
            ],
        )

    from ui import MainWindow
    from ui.theme import get_stylesheet

    # 启用高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication([sys.argv[0], *qt_args])

    # 设置应用图标
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    
    # 设置应用信息
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    # 避免把个人/本机信息写入应用元数据；同时也利于跨机器一致性
    app.setOrganizationName(APP_NAME)
    
    # 设置默认字体
    font = QFont("Inter", 10)
    app.setFont(font)
    
    # 设置样式
    app.setStyle("Fusion")
    app.setStyleSheet(get_stylesheet())
    
    # 创建主窗口
    window = MainWindow()
    window.show()

    if args.smoke:
        QTimer.singleShot(0, app.quit)
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
