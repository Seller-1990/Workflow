
# ── V7 iOS Minimal Design System ──

COLORS = {
    # Brand Colors
    "primary": "#007AFF",          # Apple Blue
    "primary_hover": "#0062CC",
    "primary_pressed": "#0051A8",
    
    # Backgrounds
    "background": "#FFFFFF",       # Main Window Background (White)
    "surface": "#F6F7F8",          # Secondary Background (Light Gray for Cards/Panels)
    "surface_secondary": "#F0F5FF", # Highlight/Selected
    
    # Text
    "text_primary": "#1A1A1A",     # Nearly Black
    "text_secondary": "#6B7280",   # Gray 500
    "text_tertiary": "#9CA3AF",    # Gray 400
    "text_inverse": "#FFFFFF",     # White Text
    
    # Borders (Minimal use)
    "border": "#F1F5F9",           # Very subtle border
    "border_focus": "#007AFF",
    
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
    "divider": "#F3F4F6",
    "border_subtle": "#E5E7EB",
}

CORNER_RADIUS = {
    "small": 8,
    "default": 12,
    "large": 16,
    "pill": 100,
}

def get_stylesheet() -> str:
    return f"""
    * {{
        font-family: "Inter", "DM Sans", "Segoe UI", sans-serif;
        font-size: 13px;
        color: {COLORS["text_primary"]};
        outline: none;
    }}

    QWidget {{
        background: {COLORS["background"]};
        border: none;
    }}

    /* --- Toolbar --- */
    QToolBar {{
        background: {COLORS["background"]};
        spacing: 12px;
        padding: 0px 16px;
        border: none;
        border-bottom: 1px solid {COLORS["divider"]};
        min-height: 44px;
        max-height: 44px;
    }}
    
    QToolBar QToolButton {{
        border: none;
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 0px 6px;
        background: transparent;
        color: {COLORS["primary"]}; 
        font-weight: 500;
        font-size: 13px;
    }}

    QToolBar QToolButton:hover {{
        background: {COLORS["surface"]};
    }}

    /* --- Panels & Cards --- */
    /* Use QFrame or QWidget with objectName for panel styling if needed */
    QFrame#LeftPanel, QFrame#RightPanel {{
        background: {COLORS["background"]};
    }}
    
    QFrame#CenterPanel {{
        background: {COLORS["background"]};
    }}

    /* Fold Strips (24px) */
    QFrame#FoldStrip {{
        background: {COLORS["surface_header"]};
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
        background: {COLORS["surface"]}; /* Light Gray Card Background */
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 8px 0px 0px 12px;
        background: transparent;
        font-weight: 700;
        font-size: 14px;
        color: {COLORS["text_primary"]};
    }}

    /* --- Inputs --- */
    QLineEdit, QComboBox, QSpinBox {{
        border: 1px solid transparent; 
        border-radius: {CORNER_RADIUS["default"]}px;
        min-height: 32px;
        padding: 0px 12px;
        background: {COLORS["background"]}; /* White input on Gray card */
        color: {COLORS["text_primary"]};
        selection-background-color: {COLORS["primary"]};
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        background: {COLORS["background"]};
        border: 1px solid {COLORS["primary"]};
    }}

    QPlainTextEdit, QTextEdit {{
        border: 1px solid transparent;
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 8px 12px;
        background: {COLORS["background"]};
    }}
    
    /* --- Buttons --- */
    QPushButton {{
        border: none;
        border-radius: {CORNER_RADIUS["default"]}px;
        background: {COLORS["surface"]};
        padding: 8px 16px;
        color: {COLORS["text_primary"]};
        font-weight: 600;
    }}

    QPushButton:hover {{
        background: {COLORS["hover"]};
    }}

    QPushButton#primary {{
        background: {COLORS["primary"]};
        color: {COLORS["text_inverse"]};
    }}

    QPushButton#primary:hover {{
        background: {COLORS["primary_hover"]};
    }}

    QPushButton#primarySmall {{
        background: {COLORS["primary"]};
        color: {COLORS["text_inverse"]};
        border-radius: 12px;
        padding: 0px 12px;
        font-weight: 600;
        font-size: 11px;
    }}

    QPushButton#primaryRect {{
        background: {COLORS["primary"]};
        color: {COLORS["text_inverse"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton#primaryRect:hover {{
        background: {COLORS["primary_hover"]};
    }}
    QPushButton#primaryRect:disabled {{
        background: {COLORS["pressed"]};
        color: {COLORS["text_tertiary"]};
    }}

    /* StepTable header primary button (86x28, radius 14) */
    QPushButton#primaryHeaderBtn {{
        background: {COLORS["primary"]};
        color: {COLORS["text_inverse"]};
        border-radius: 14px;
        padding: 0px 14px;
        font-weight: 600;
        font-size: 12px;
        text-align: center;
    }}
    QPushButton#primaryHeaderBtn:hover {{
        background: {COLORS["primary_hover"]};
    }}
    QPushButton#primaryHeaderBtn:disabled {{
        background: {COLORS["pressed"]};
        color: {COLORS["text_tertiary"]};
    }}

    QPushButton#inputLike {{
        background: {COLORS["background"]};
        border: 1px solid transparent;
        border-radius: 10px;
        padding: 0px 12px;
        text-align: left;
        font-weight: 500;
    }}
    QPushButton#inputLike:hover {{
        background: {COLORS["hover"]};
    }}

    /* Header link buttons (e.g., 日志工具条) */
    QPushButton#headerLink {{
        background: transparent;
        border: none;
        padding: 0px 6px;
        color: {COLORS["primary"]};
        font-weight: 500;
    }}
    QPushButton#headerLink:hover {{
        background: {COLORS["surface"]};
        border-radius: 10px;
    }}

    /* Workflow list pills */
    QPushButton#wfPill {{
        background: {COLORS["surface"]};
        border-radius: 16px;
        padding: 0px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {COLORS["text_primary"]};
    }}
    QPushButton#wfPill:hover {{ background: {COLORS["hover"]}; }}
    QPushButton#wfDangerPill {{
        background: {COLORS["surface"]};
        border-radius: 16px;
        padding: 0px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {COLORS["danger"]};
    }}
    QPushButton#wfDangerPill:hover {{ background: {COLORS["hover"]}; }}

    /* Run control buttons */
    QPushButton#runPrimary {{
        background: {COLORS["primary"]};
        color: {COLORS["text_inverse"]};
        border-radius: 12px;
        padding: 0px 14px;
        font-size: 14px;
        font-weight: 600;
        text-align: center;
    }}
    QPushButton#runPrimary:hover {{ background: {COLORS["primary_hover"]}; }}
    QPushButton#runGhost {{
        background: transparent;
        color: {COLORS["primary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhost:hover {{ background: {COLORS["surface"]}; }}
    QPushButton#runGhost:disabled {{ color: {COLORS["text_tertiary"]}; }}

    QPushButton#runGhostMuted {{
        background: transparent;
        color: {COLORS["text_secondary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhostMuted:hover {{ background: {COLORS["surface"]}; }}
    QPushButton#runGhostMuted:disabled {{ color: {COLORS["text_tertiary"]}; }}

    QPushButton#runGhostDisabled {{
        background: transparent;
        color: {COLORS["text_tertiary"]};
        border-radius: 10px;
        padding: 0px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton#runGhostDisabled:hover {{ background: {COLORS["surface"]}; }}
    QPushButton#runGhostDisabled:enabled {{ color: {COLORS["text_tertiary"]}; }}
    QPushButton#primarySmall:disabled {{
        background: {COLORS["pressed"]};
        color: {COLORS["text_tertiary"]};
    }}

    /* --- Table & Lists --- */
    QTableWidget, QListWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        selection-background-color: {COLORS["selected_bg"]};
        selection-color: {COLORS["selected_text"]};
    }}
    
    QHeaderView::section {{
        background: transparent;
        border: none;
        padding: 8px;
        font-weight: 600;
        color: {COLORS["text_secondary"]};
        text-transform: uppercase;
        font-size: 11px;
    }}

    /* StatusBar */
    QStatusBar {{
        background: {COLORS["surface_header"]};
        color: {COLORS["text_tertiary"]};
        border-top: 1px solid {COLORS["divider"]};
    }}
    
    /* --- Scrollbars (Mac Style) --- */
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #D1D5DB;
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    
    /* --- Splitter --- */
    QSplitter::handle {{
        background: transparent;
        margin: 0px 4px;
    }}
    """
