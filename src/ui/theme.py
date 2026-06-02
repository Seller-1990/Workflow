# ── V7 iOS Minimal Design System ──

COLORS = {
    # Brand Colors
    "primary": "#007AFF",          # Apple Blue
    "primary_hover": "#0062CC",
    "primary_pressed": "#0051A8",

    # Backgrounds - 层级色彩系统
    "background": "#FFFFFF",           # 主窗口背景（最底层）
    "surface_primary": "#F8FAFC",      # 左/右侧面板背景（次级）
    "surface_secondary": "#F1F5F9",    # 中区内容区背景
    "surface_card": "#FFFFFF",         # 卡片内容区（最高层）
    "surface": "#F6F7F8",              # 兼容旧代码

    # Text - 提高对比度
    "text_primary": "#111827",       # 更深的黑色
    "text_secondary": "#4B5563",     # 更深的灰色
    "text_tertiary": "#6B7280",      # Gray 500（U-P2-1: 从 #9CA3AF 提升至 AA 4.5:1）
    "text_inverse": "#FFFFFF",       # White Text

    # Borders - 增强分隔感
    "border": "#E2E8F0",             # 强分隔（面板之间）
    "border_subtle": "#F1F5F9",      # 弱分隔（卡片内部）
    "border_focus": "#007AFF",
    "divider_strong": "#E2E8F0",     # 强分隔线
    "divider": "#F3F4F6",            # 弱分隔线

    # Status
    "success": "#34C759",          # iOS Green
    "warning": "#FF9500",          # iOS Orange
    "danger": "#FF3B30",           # iOS Red
    "info": "#007AFF",

    # Interaction
    "hover": "#F3F4F6",            # Light Gray Hover
    "pressed": "#E5E7EB",
    "selected_bg": "#E8F0FE",      # Light Blue Selection
    "selected_text": "#007AFF",

    # Pencil 细节色（V7 定稿）
    "surface_header": "#FAFBFC",

    # 焦点状态
    "focus_ring": "#007AFF",
    "focus_ring_offset": "#FFFFFF",
}

DARK_COLORS = {
    "primary": "#007AFF",
    "primary_hover": "#0062CC",
    "primary_pressed": "#0051A8",

    "background": "#1C1C1E",
    "surface_primary": "#2C2C2E",
    "surface_secondary": "#3A3A3C",
    "surface_card": "#2C2C2E",
    "surface": "#2C2C2E",

    "text_primary": "#F5F5F7",
    "text_secondary": "#AEAEB2",
    "text_tertiary": "#8E8E93",
    "text_inverse": "#1C1C1E",

    "border": "#48484A",
    "border_subtle": "#3A3A3C",
    "border_focus": "#007AFF",
    "divider_strong": "#48484A",
    "divider": "#3A3A3C",

    "success": "#34C759",
    "warning": "#FF9500",
    "danger": "#FF3B30",
    "info": "#007AFF",

    "hover": "#3A3A3C",
    "pressed": "#48484A",
    "selected_bg": "#1A3A5C",
    "selected_text": "#0A84FF",

    "surface_header": "#2C2C2E",

    "focus_ring": "#007AFF",
    "focus_ring_offset": "#1C1C1E",
}

CORNER_RADIUS = {
    "small": 8,
    "default": 12,
    "large": 16,
    "pill": 100,
}


# U-P1-3 / U-P2-3 修复：状态色 / 类型色 / 日志级别色集中到 theme.py
# 单一真相源，避免 step_table / dag_view / run_history / log_panel 各自硬编码
STATUS_TOKENS_LIGHT = {
    "success":  {"fg": "#1E7E34", "bg": "#E8F5E9", "strip": "#34C759"},
    "failure":  {"fg": "#B71C1C", "bg": "#FFEBEE", "strip": "#FF3B30"},
    "cancelled": {"fg": "#7F5500", "bg": "#FFF4E0", "strip": "#FF9500"},
    "skipped":  {"fg": "#5C5C5C", "bg": "#EEEEEE", "strip": "#9CA3AF"},
    "running":  {"fg": "#0050B3", "bg": "#E3F2FD", "strip": "#007AFF"},
    "pending":  {"fg": "#6B7280", "bg": "#F4F4F5", "strip": "#D1D5DB"},
}
STATUS_TOKENS_DARK = {
    "success":  {"fg": "#34C759", "bg": "#1F3A24", "strip": "#34C759"},
    "failure":  {"fg": "#FF6961", "bg": "#3A1515", "strip": "#FF453A"},
    "cancelled": {"fg": "#FF9F0A", "bg": "#3A2A0F", "strip": "#FF9F0A"},
    "skipped":  {"fg": "#AEAEB2", "bg": "#2C2C2E", "strip": "#636366"},
    "running":  {"fg": "#5AC8FA", "bg": "#1A2A3E", "strip": "#0A84FF"},
    "pending":  {"fg": "#A1A1A6", "bg": "#2C2C2E", "strip": "#48484A"},
}

TYPE_TOKENS_LIGHT = {
    "python":            {"fg": "#1E40AF", "bg": "#DBEAFE"},
    "excel_powerquery":  {"fg": "#166534", "bg": "#DCFCE7"},
    "powerbi_refresh":   {"fg": "#854D0E", "bg": "#FEF3C7"},
    "sub_workflow":      {"fg": "#6B21A8", "bg": "#F3E8FF"},
}
TYPE_TOKENS_DARK = {
    "python":            {"fg": "#60A5FA", "bg": "#1E3A8A"},
    "excel_powerquery":  {"fg": "#4ADE80", "bg": "#14532D"},
    "powerbi_refresh":   {"fg": "#FCD34D", "bg": "#78350F"},
    "sub_workflow":      {"fg": "#C084FC", "bg": "#581C87"},
}

LOG_LEVEL_TOKENS_LIGHT = {
    "ERROR":   "#FF3B30",
    "WARNING": "#FF9500",
    "INFO":    "#1A1A1A",
    "DEBUG":   "#9CA3AF",
}
LOG_LEVEL_TOKENS_DARK = {
    "ERROR":   "#FF453A",
    "WARNING": "#FF9F0A",
    "INFO":    "#F5F5F7",
    "DEBUG":   "#636366",
}


def get_status_tokens(dark: bool = False) -> dict:
    return STATUS_TOKENS_DARK if dark else STATUS_TOKENS_LIGHT


def get_type_tokens(dark: bool = False) -> dict:
    return TYPE_TOKENS_DARK if dark else TYPE_TOKENS_LIGHT


def get_log_level_colors(dark: bool = False) -> dict:
    return LOG_LEVEL_TOKENS_DARK if dark else LOG_LEVEL_TOKENS_LIGHT


def get_duration_tokens(dark: bool = False) -> dict:
    colors = get_colors(dark)
    return {
        "fast": colors["success"],
        "medium": colors["warning"],
        "slow": colors["danger"],
    }


def get_danger_button_stylesheet(dark: bool = False, radius: int = 4, padding: str = "2px 10px") -> str:
    colors = get_colors(dark)
    hover = "#FF453A" if dark else "#FF6259"
    pressed = "#D70015" if dark else "#E02B20"
    fg = colors["text_primary"] if dark else colors["text_inverse"]
    return f"""
QPushButton {{
    background: {colors["danger"]};
    color: {fg};
    border: none;
    border-radius: {int(radius)}px;
    padding: {padding};
    font-weight: 700;
}}
QPushButton:hover {{
    background: {hover};
}}
QPushButton:pressed {{
    background: {pressed};
}}
QPushButton:disabled {{
    background: {colors["border"]};
    color: {colors["text_tertiary"]};
}}
"""


def get_colors(dark=False):
    return DARK_COLORS if dark else COLORS


def get_stylesheet(dark=False):
    C = get_colors(dark)
    return f"""
    * {{
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
        font-size: 13px;
        color: {C["text_primary"]};
        outline: none;
    }}

    QMainWindow, QDialog {{
        background: {C["background"]};
    }}

    QWidget {{
        background: transparent;
        border: none;
    }}

    /* --- Toolbar --- */
    QToolBar {{
        background: {C["background"]};
        spacing: 12px;
        padding: 0px 16px;
        border: none;
        border-bottom: 1px solid {C["divider"]};
        min-height: 44px;
        max-height: 44px;
    }}
    
    QToolBar QToolButton {{
        border: none;
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 0px 6px;
        background: transparent;
        color: {C["primary"]}; 
        font-weight: 500;
        font-size: 13px;
    }}

    QToolBar QToolButton:hover {{
        background: {C["surface"]};
    }}

    /* --- Panels & Cards --- */
    /* Use QFrame or QWidget with objectName for panel styling if needed */
    QFrame#LeftPanel, QFrame#RightPanel {{
        background: {C["background"]};
    }}
    
    QFrame#CenterPanel {{
        background: {C["background"]};
    }}

    /* Fold Strips (24px) */
    QFrame#FoldStrip {{
        background: {C["surface_header"]};
    }}
    QFrame#FoldBtnWrap {{
        background: #EEEEEE;
        border-radius: 10px;
    }}
    QToolButton#FoldBtn {{
        border: none;
        padding: 0px;
        background: transparent;
    }}

    /* Component Containers */
    QGroupBox {{
        border: none;
        border-radius: {CORNER_RADIUS["large"]}px;
        margin-top: 0px; 
        padding: 0px;
        background: {C["surface"]}; /* Light Gray Card Background */
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 8px 0px 0px 12px;
        background: transparent;
        font-weight: 700;
        font-size: 14px;
        color: {C["text_primary"]};
    }}

    /* --- Inputs --- */
    QLineEdit, QComboBox, QSpinBox {{
        border: 1px solid transparent; 
        border-radius: {CORNER_RADIUS["default"]}px;
        min-height: 32px;
        padding: 0px 12px;
        background: {C["background"]}; /* White input on Gray card */
        color: {C["text_primary"]};
        selection-background-color: {C["primary"]};
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        background: {C["background"]};
        border: 1px solid {C["primary"]};
    }}

    QPlainTextEdit, QTextEdit {{
        border: 1px solid transparent;
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 8px 12px;
        background: {C["background"]};
    }}
    
    /* --- Buttons --- */
    QPushButton {{
        border: none;
        border-radius: {CORNER_RADIUS["default"]}px;
        background: {C["surface"]};
        padding: 8px 16px;
        color: {C["text_primary"]};
        font-weight: 600;
    }}

    QPushButton:hover {{
        background: {C["hover"]};
    }}

    /* U-P2-2 焦点反馈：键盘 Tab 切换时显示 2px 焦点环；不影响布局 */
    QPushButton:focus, QToolButton:focus {{
        outline: 2px solid {C["focus_ring"]};
    }}
    QCheckBox:focus, QRadioButton:focus {{
        outline: 2px solid {C["focus_ring"]};
    }}

    QPushButton#primary {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
    }}

    QPushButton#primary:hover {{
        background: {C["primary_hover"]};
    }}

    QPushButton#primarySmall {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
        border-radius: 12px;
        padding: 0px 12px;
        font-weight: 600;
        font-size: 11px;
    }}

    QPushButton#primaryRect {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton#primaryRect:hover {{
        background: {C["primary_hover"]};
    }}
    QPushButton#primaryRect:disabled {{
        background: {C["pressed"]};
        color: {C["text_tertiary"]};
    }}

    /* StepTable header primary button (86x28, radius 14) */
    QPushButton#primaryHeaderBtn {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
        border-radius: 14px;
        padding: 0px 14px;
        font-weight: 600;
        font-size: 12px;
        text-align: center;
    }}
    QPushButton#primaryHeaderBtn:hover {{
        background: {C["primary_hover"]};
    }}
    QPushButton#primaryHeaderBtn:disabled {{
        background: {C["pressed"]};
        color: {C["text_tertiary"]};
    }}

    QPushButton#inputLike {{
        background: {C["background"]};
        border: 1px solid transparent;
        border-radius: 10px;
        padding: 0px 12px;
        text-align: left;
        font-weight: 500;
    }}
    QPushButton#inputLike:hover {{
        background: {C["hover"]};
    }}

    /* Header link buttons (e.g., 日志工具条) */
    QPushButton#headerLink {{
        background: transparent;
        border: none;
        padding: 0px 6px;
        color: {C["primary"]};
        font-weight: 500;
        font-size: 11px;
    }}
    QPushButton#headerLink:hover {{
        background: {C["surface"]};
        border-radius: 10px;
    }}

    /* Workflow list pills */
    QPushButton#wfPill {{
        background: {C["surface"]};
        border-radius: 16px;
        padding: 0px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {C["text_primary"]};
    }}
    QPushButton#wfPill:hover {{ background: {C["hover"]}; }}
    QPushButton#wfDangerPill {{
        background: {C["surface"]};
        border-radius: 16px;
        padding: 0px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {C["danger"]};
    }}
    QPushButton#wfDangerPill:hover {{ background: {C["hover"]}; }}

    /* Run control buttons */
    QPushButton#runPrimary {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
        border-radius: 12px;
        padding: 0px 14px;
        font-size: 14px;
        font-weight: 600;
        text-align: center;
    }}
    QPushButton#runPrimary:hover {{ background: {C["primary_hover"]}; }}
    QPushButton#runGhost {{
        background: transparent;
        color: {C["primary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhost:hover {{ background: {C["surface"]}; }}
    QPushButton#runGhost:disabled {{ color: {C["text_tertiary"]}; }}

    QPushButton#stepRunButton {{
        background: {C["surface"]};
        color: {C["primary"]};
        border: 1px solid {C["border"]};
        border-radius: 10px;
        padding: 0px 10px;
        font-size: 12px;
        font-weight: 650;
        text-align: center;
    }}
    QPushButton#stepRunButton:hover {{
        background: {C["hover"]};
        border-color: {C["border_focus"]};
    }}
    QPushButton#stepRunButton:pressed {{
        background: {C["pressed"]};
    }}
    QPushButton#stepRunButton:disabled {{
        background: {C["surface"]};
        color: {C["text_tertiary"]};
        border-color: {C["border_subtle"]};
    }}

    QPushButton#runGhostMuted {{
        background: transparent;
        color: {C["text_secondary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhostMuted:hover {{ background: {C["surface"]}; }}
    QPushButton#runGhostMuted:disabled {{ color: {C["text_tertiary"]}; }}

    QPushButton#runGhostDisabled {{
        background: transparent;
        color: {C["text_tertiary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhostDisabled:hover {{ background: {C["surface"]}; }}
    QPushButton#runGhostDisabled:enabled {{ color: {C["text_tertiary"]}; }}

    QPushButton#runDanger {{
        background: {C["surface"]};
        color: {C["danger"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 600;
        text-align: center;
    }}
    QPushButton#runDanger:hover {{ background: {C["hover"]}; }}
    QPushButton#runDanger:pressed {{ background: {C["pressed"]}; }}
    QPushButton#runDanger:disabled {{ color: {C["text_tertiary"]}; }}
    QPushButton#primarySmall:disabled {{
        background: {C["pressed"]};
        color: {C["text_tertiary"]};
    }}

    /* --- Table & Lists --- */
    QTableWidget, QListWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        selection-background-color: {C["selected_bg"]};
        selection-color: {C["selected_text"]};
    }}
    
    QHeaderView::section {{
        background: transparent;
        border: none;
        padding: 8px;
        font-weight: 600;
        color: {C["text_secondary"]};
        text-transform: uppercase;
        font-size: 11px;
    }}

    /* StatusBar */
    QStatusBar {{
        background: {C["surface_header"]};
        color: {C["text_tertiary"]};
        border-top: 1px solid {C["divider"]};
    }}
    
    /* --- Scrollbars (Mac Style) --- */
    QScrollBar:vertical {{
        border: none;
        background: {C["background"]};
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {C["divider_strong"]};
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {C["text_tertiary"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    /* --- ScrollArea --- */
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        border: none;
        background: {C["background"]};
        height: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: {C["divider_strong"]};
        min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {C["text_tertiary"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        background: transparent;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    /* --- Splitter --- */
    QSplitter::handle {{
        background: {C["divider_strong"]};
    }}
    """ + get_menu_stylesheet(dark)


_MSG_BOX_STYLE = """
QMessageBox {{
    background-color: {bg};
    color: {fg};
}}
QMessageBox QLabel {{
    color: {fg};
    background-color: transparent;
}}
QMessageBox QPushButton {{
    background-color: {btn_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
    font-weight: 500;
}}
QMessageBox QPushButton:hover {{
    background-color: {hover};
}}
"""

_INPUT_DIALOG_STYLE = """
QInputDialog {{
    background-color: {bg};
    color: {fg};
}}
QInputDialog QLabel {{
    color: {fg};
    background-color: transparent;
}}
QInputDialog QLineEdit {{
    background-color: {input_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
QInputDialog QLineEdit:focus {{
    border: 1px solid {focus};
}}
QInputDialog QPushButton {{
    background-color: {btn_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
    font-weight: 500;
}}
QInputDialog QPushButton:hover {{
    background-color: {hover};
}}
QInputDialog QComboBox {{
    background-color: {input_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
"""

_MENU_STYLE = """
QMenu {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    background-color: transparent;
    color: {fg};
    border-radius: 6px;
    padding: 7px 12px;
    margin: 1px 0px;
}}
QMenu::item:selected {{
    background-color: {hover};
    color: {fg};
}}
QMenu::item:disabled {{
    color: {muted};
    background-color: transparent;
}}
QMenu::separator {{
    height: 1px;
    margin: 6px 8px;
    background: {divider};
}}
"""


def _style_colors(dark: bool) -> dict:
    C = get_colors(dark)
    return {
        "bg": C["surface_primary"],
        "fg": C["text_primary"],
        "btn_bg": C["surface_secondary"],
        "hover": C["hover"],
        "border": C["border"],
        "focus": C["border_focus"],
        "input_bg": C["background"],
    }


def get_menu_stylesheet(dark: bool = False) -> str:
    C = get_colors(dark)
    return _MENU_STYLE.format(
        bg=C["surface_card"],
        fg=C["text_primary"],
        border=C["border"],
        hover=C["hover"],
        muted=C["text_tertiary"],
        divider=C["divider"],
    )


def msg_information(parent, dark: bool, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Information)
    msg.setStandardButtons(QMessageBox.Ok)
    sc = _style_colors(dark)
    msg.setStyleSheet(_MSG_BOX_STYLE.format(**sc))
    msg.exec()


def msg_warning(parent, dark: bool, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Warning)
    msg.setStandardButtons(QMessageBox.Ok)
    sc = _style_colors(dark)
    msg.setStyleSheet(_MSG_BOX_STYLE.format(**sc))
    msg.exec()


def msg_critical(parent, dark: bool, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Critical)
    msg.setStandardButtons(QMessageBox.Ok)
    sc = _style_colors(dark)
    msg.setStyleSheet(_MSG_BOX_STYLE.format(**sc))
    msg.exec()


def msg_question(
    parent, dark: bool, title: str, text: str,
    buttons=None, default_button=None,
) -> int:
    from PySide6.QtWidgets import QMessageBox
    if buttons is None:
        buttons = QMessageBox.Yes | QMessageBox.No
    if default_button is None:
        default_button = QMessageBox.No
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Question)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default_button)
    sc = _style_colors(dark)
    msg.setStyleSheet(_MSG_BOX_STYLE.format(**sc))
    return msg.exec()


def input_get_text(parent, dark: bool, title: str, label: str, text: str = ""):
    from PySide6.QtWidgets import QInputDialog
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    sc = _style_colors(dark)
    dlg.setStyleSheet(_INPUT_DIALOG_STYLE.format(**sc))
    ok = dlg.exec() == QInputDialog.Accepted
    return dlg.textValue(), ok


def input_get_item(
    parent, dark: bool, title: str, label: str,
    items: list, current: int = 0, editable: bool = False,
):
    from PySide6.QtWidgets import QInputDialog
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setComboBoxItems(items)
    dlg.setComboBoxEditable(editable)
    if 0 <= current < len(items):
        dlg.setTextValue(items[current])
    sc = _style_colors(dark)
    dlg.setStyleSheet(_INPUT_DIALOG_STYLE.format(**sc))
    ok = dlg.exec() == QInputDialog.Accepted
    return dlg.textValue(), ok
