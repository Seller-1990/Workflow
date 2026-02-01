# -*- coding: utf-8 -*-
"""全局 UI 主题（白色极简 / 瑞士风格）"""


def get_stylesheet() -> str:
    return """
    * {
        font-family: "Inter", "Segoe UI", "Microsoft YaHei", sans-serif;
        font-size: 12px;
        color: #111111;
    }

    QWidget {
        background: #FFFFFF;
    }

    QToolBar {
        background: #FFFFFF;
        border-bottom: 1px solid #E5E5EA;
        spacing: 8px;
        padding: 4px 8px;
    }

    QStatusBar {
        border-top: 1px solid #E5E5EA;
        padding: 4px 8px;
    }

    QGroupBox {
        border: 1px solid #E5E5EA;
        border-radius: 12px;
        margin-top: 18px;
        padding: 12px 12px 10px 12px;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 6px;
        background: #FFFFFF;
        font-weight: 600;
    }

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        border: 1px solid #D1D1D6;
        border-radius: 10px;
        padding: 7px 10px;
        background: #FFFFFF;
        min-height: 30px;
    }

    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
        border: 1px solid #0A84FF;
    }

    QComboBox::drop-down {
        border: 0px;
        width: 24px;
    }

    QComboBox::down-arrow {
        image: none;
        border: 4px solid transparent;
        border-top-color: #111111;
        margin-right: 6px;
    }

    QPlainTextEdit, QTextEdit {
        min-height: 80px;
    }

    QPushButton {
        border: 1px solid #D1D1D6;
        border-radius: 10px;
        background: #F2F2F7;
        padding: 7px 12px;
    }

    QPushButton:hover {
        background: #EDEDF4;
    }

    QPushButton:pressed {
        background: #E2E2EA;
    }

    QPushButton#primary {
        background: #0A84FF;
        color: #FFFFFF;
        border: 1px solid #0A84FF;
    }

    QPushButton#primary:hover {
        background: #007AFF;
    }

    QPushButton#ghost {
        border: 1px solid #E6E6E6;
        color: #111111;
        background: #FFFFFF;
    }

    QTableWidget {
        gridline-color: #E6E6E6;
        border: 1px solid #E6E6E6;
        border-radius: 6px;
        background: #FFFFFF;
        alternate-background-color: #FAFAFA;
    }

    QHeaderView::section {
        background: #F2F2F7;
        border: 0px;
        border-bottom: 1px solid #E5E5EA;
        padding: 6px 8px;
        font-weight: 600;
    }

    QTableWidget::item:selected, QListWidget::item:selected {
        background: #E6F0FF;
        color: #111111;
    }

    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #C7C7CC;
        border-radius: 4px;
        background: #FFFFFF;
    }

    QCheckBox::indicator:checked {
        background: #0A84FF;
        border: 1px solid #0A84FF;
    }

    /* iOS-like toggle (only for QCheckBox#toggle) */
    QCheckBox#toggle::indicator {
        width: 36px;
        height: 20px;
        border-radius: 10px;
        border: 1px solid #C7C7CC;
        background: #E5E5EA;
    }

    QCheckBox#toggle::indicator:checked {
        border: 1px solid #0A84FF;
        background: #0A84FF;
    }

    QSplitter::handle {
        background: #F0F0F0;
        width: 1px;
    }
    """
