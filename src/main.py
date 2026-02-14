#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流管理应用入口"""

import argparse
import sys
from pathlib import Path

# 添加 src 目录到路径
src_dir = Path(__file__).resolve().parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon

from ui import MainWindow
from ui.theme import get_stylesheet
from config import ICON_PATH, APP_NAME, APP_VERSION


def main(argv=None):
    """主函数"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke", action="store_true", help="启动后立即退出（用于冒烟验证）")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

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
