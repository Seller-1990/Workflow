# ── V8 Linear/Vercel Design System ──
# 克制极简风：柔和 Indigo 主色 + Zinc 中性灰阶 + 微妙阴影
# 替代原 iOS Blue + Slate 双轨制

COLORS = {
    # Brand Colors - Indigo 主色系（比 iOS Blue 柔和，长时间看不刺眼）
    "primary": "#5E6AD2",          # Linear Indigo
    "primary_hover": "#4F5BC1",
    "primary_pressed": "#4049B0",

    # Backgrounds - Zinc 灰阶系统（V9：层级差异加深到 8-12%，肉眼可辨）
    "background": "#FFFFFF",           # 主窗口背景（最底层）
    "surface_primary": "#F8F8FA",      # 左/右侧面板背景（次级，与 background 差 ~3%）
    "surface_secondary": "#EEEEF1",    # 中区内容区背景（差 ~6%）
    "surface_card": "#FFFFFF",         # 卡片内容区（最高层，带阴影）
    "surface": "#EEEEF1",              # 兼容旧代码

    # Text - Zinc 灰阶（无色相偏移，层级更清晰）
    "text_primary": "#18181B",       # Zinc-950，最深黑
    "text_secondary": "#3F3F46",     # Zinc-700
    "text_tertiary": "#71717A",      # Zinc-500（AA 4.5:1）
    "text_inverse": "#FAFAFA",       # Zinc-50

    # Borders - Zinc 灰阶（统一不混入蓝调）
    "border": "#E4E4E7",             # Zinc-200，强分隔
    "border_subtle": "#F4F4F5",      # Zinc-100，弱分隔
    "border_focus": "#5E6AD2",
    "divider_strong": "#D4D4D8",     # Zinc-300，强分隔线
    "divider": "#E4E4E7",            # Zinc-200，弱分隔线

    # Status - 降饱和的 Emerald/Amber/Red（与 Indigo 主色更协调）
    "success": "#10B981",          # Emerald-500
    "warning": "#F59E0B",          # Amber-500
    "danger": "#EF4444",           # Red-500
    "info": "#0EA5E9",             # V9：Teal-500（原复用 primary，现独立区分"信息"语义）

    # Interaction - Zinc 灰阶（hover 略深）
    "hover": "#F4F4F5",            # Zinc-100
    "pressed": "#E4E4E7",          # Zinc-200
    "selected_bg": "#EEF0FC",      # Indigo-50 淡选区
    "selected_text": "#5E6AD2",

    # 表头/工具栏背景
    "surface_header": "#FAFAFA",

    # 焦点状态 - 柔和 indigo 光晕（替代硬 outline）
    "focus_ring": "#5E6AD2",
    "focus_ring_offset": "#FFFFFF",

    # AA-safe 强调色变体（白底对比度 ≥ 4.5:1）
    "primary_aa": "#4338CA",      # Indigo-700 白底 5.9:1
    "success_aa": "#047857",      # Emerald-700 白底 5.4:1
    "danger_aa":  "#B91C1C",      # Red-700 白底 5.5:1
    "warning_aa": "#B45309",      # Amber-700 白底 4.7:1

    # 按钮文字色
    "on_primary": "#FFFFFF",

    # 勾选框 indicator 配色
    "indicator_bg": "#FFFFFF",
    "indicator_border": "#D4D4D8",  # Zinc-300

    # 状态弱色底（Indigo/Emerald/Red/Amber-50）
    "success_weak": "#ECFDF5",
    "danger_weak":  "#FEF2F2",
    "warning_weak": "#FFFBEB",

    # V9：新增辅助色 token（消除 workbench_board 双调色板）
    "indigo_weak": "#EEF0FC",        # Indigo-50，统一弱底（替换散落的 #e9eefc / #EEF0FC）
    "violet": "#6D28D9",             # Violet-700，子工作流类型色（AA-safe 白底 5.6:1）
    "violet_weak": "#F3F0FF",        # Violet-50，子工作流弱底
    "teal": "#0EA5E9",               # Teal-500，信息语义色（与 info 同色，独立命名便于扩展）
    "teal_weak": "#ECFEFF",          # Teal-50

    # V9：图表色板（8 色，为未来运行历史图表预留，本批不使用）
    "chart_palette": [
        "#5E6AD2",  # Indigo
        "#10B981",  # Emerald
        "#F59E0B",  # Amber
        "#EF4444",  # Red
        "#0EA5E9",  # Teal
        "#8B5CF6",  # Violet
        "#EC4899",  # Pink
        "#14B8A6",  # Teal-600
    ],

    # V9.2：状态指示器专用 token（消除散落的 iOS 色 #FF9500/#34C759/#248A3D 等）
    "accent_running": "#F59E0B",          # 后台运行中（琥珀，与 warning 同色）
    "accent_running_aa": "#B45309",       # AA-safe 暗文字版（白底 4.7:1）
    "watch_active": "#10B981",            # 监听运行中（绿，与 success 同色）
    "watch_active_aa": "#047857",         # AA-safe 暗文字版
    "watch_inactive": "#71717A",          # 未监听（Zinc-500 text_tertiary 同色）
    "watch_inactive_strong": "#3F3F46",   # 未监听（Zinc-700 text_secondary，AA 版）

    # V9.2：danger 按钮 hover/pressed 派生色（替代 get_danger_button_stylesheet 内硬编码）
    "danger_hover": "#DC2626",            # Red-600
    "danger_pressed": "#B91C1C",          # Red-700（= danger_aa）

    # V9.2：DAG/列表 阶段交替色带（4 色循环）
    "stage_band_palette": [
        "#FFFFFF",  # surface_card（白底）
        "#F8F8FA",  # surface_primary
        "#EEF0FC",  # indigo_weak（淡 Indigo 底）
        "#ECFDF5",  # success_weak（淡 Emerald 底）
    ],

    # V9.2：未匹配类型时的 fallback 背景
    "default_type_bg": "#F8F8FA",         # = surface_primary
}

DARK_COLORS = {
    # Brand Colors
    "primary": "#6E7AE0",          # 比 light 略亮，暗底可读
    "primary_hover": "#7E89E8",
    "primary_pressed": "#5E6AD2",

    # Backgrounds - 纯灰阶（V9：层级差异加深，与 light 对应）
    "background": "#0F0F10",       # 接近纯黑但留呼吸感
    "surface_primary": "#1A1A1C", # Zinc-900 接近
    "surface_secondary": "#262629",# 中区（V9：从 #232325 加深到 #262629）
    "surface_card": "#1A1A1C",
    "surface": "#1A1A1C",

    "text_primary": "#FAFAFA",     # Zinc-50
    "text_secondary": "#A1A1AA",   # Zinc-400
    "text_tertiary": "#71717A",    # Zinc-500
    "text_inverse": "#18181B",

    "border": "#27272A",           # Zinc-800
    "border_subtle": "#1F1F22",
    "border_focus": "#6E7AE0",
    "divider_strong": "#3F3F46",   # Zinc-700
    "divider": "#27272A",

    "success": "#34D399",          # Emerald-400 暗底高可读
    "warning": "#FBBF24",          # Amber-400
    "danger": "#F87171",           # Red-400
    "info": "#38BDF8",             # V9：Teal-400（暗底版）

    "hover": "#232325",
    "pressed": "#2A2A2D",
    "selected_bg": "#1E1F3A",      # 淡 indigo 选区
    "selected_text": "#A5ACED",

    "surface_header": "#1A1A1C",

    "focus_ring": "#6E7AE0",
    "focus_ring_offset": "#0F0F10",

    # AA-safe 强调色变体（暗底对比度 ≥ 4.5:1）
    "primary_aa": "#A5ACED",       # 暗底 5.1:1
    "success_aa": "#6EE7B7",       # 暗底 5.5:1
    "danger_aa":  "#FCA5A5",       # 暗底 5.2:1
    "warning_aa": "#FCD34D",       # 暗底 5.0:1

    "on_primary": "#FFFFFF",

    "indicator_bg": "#1A1A1C",
    "indicator_border": "#3F3F46",

    "success_weak": "#0A2A1F",
    "danger_weak":  "#2A1010",
    "warning_weak": "#2A1F08",

    # V9：新增辅助色 token（暗色版）
    "indigo_weak": "#1E1F3A",        # 暗色 Indigo 弱底
    "violet": "#C4B5FD",             # Violet-300 暗底可读
    "violet_weak": "#221A3A",        # 暗色 Violet 弱底
    "teal": "#38BDF8",               # Teal-400 暗底版
    "teal_weak": "#082F3C",          # 暗色 Teal 弱底

    "chart_palette": [
        "#6E7AE0", "#34D399", "#FBBF24", "#F87171",
        "#38BDF8", "#C4B5FD", "#F472B6", "#2DD4BF",
    ],

    # V9.2：状态指示器专用 token（暗色版）
    "accent_running": "#FBBF24",          # Amber-400
    "accent_running_aa": "#FCD34D",       # AA-safe 暗底版
    "watch_active": "#34D399",            # Emerald-400
    "watch_active_aa": "#6EE7B7",         # AA-safe 暗底版
    "watch_inactive": "#71717A",          # Zinc-500
    "watch_inactive_strong": "#A1A1AA",   # Zinc-400（暗底 AA 版）

    "danger_hover": "#F87171",            # Red-400
    "danger_pressed": "#FCA5A5",          # Red-300（= danger_aa）

    "stage_band_palette": [
        "#1A1A1C",  # surface_card
        "#1F1F22",  # surface_primary 加深
        "#1E1F3A",  # indigo_weak
        "#0A2A1F",  # success_weak
    ],

    "default_type_bg": "#1A1A1C",         # = surface_card
}

CORNER_RADIUS = {
    "small": 6,       # 小按钮/标签
    "default": 8,     # 默认（输入框、按钮）
    "large": 12,      # 卡片/面板
    "pill": 100,
}

# V9 阴影 - 加深层级差异（depth 而非 line）
SHADOW_TOKENS = {
    "xs": "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",  # 卡片基础
    "sm": "0 2px 6px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)",  # hover 提升
    "md": "0 4px 12px rgba(0,0,0,0.10)",                              # 弹层
    "focus_ring": "0 0 0 3px rgba(94,106,210,0.18)",                  # 焦点光晕
}


# U-P1-3 / U-P2-3 修复：状态色 / 类型色 / 日志级别色集中到 theme.py
# 单一真相源，避免 step_table / run_history / log_panel 各自硬编码
STATUS_TOKENS_LIGHT = {
    "success":  {"fg": "#047857", "bg": "#ECFDF5", "strip": "#10B981"},
    "failure":  {"fg": "#B91C1C", "bg": "#FEF2F2", "strip": "#EF4444"},
    "cancelled": {"fg": "#B45309", "bg": "#FFFBEB", "strip": "#F59E0B"},
    "skipped":  {"fg": "#52525B", "bg": "#F4F4F5", "strip": "#A1A1AA"},
    "running":  {"fg": "#4338CA", "bg": "#EEF0FC", "strip": "#5E6AD2"},
    "pending":  {"fg": "#71717A", "bg": "#F4F4F5", "strip": "#D4D4D8"},
}
STATUS_TOKENS_DARK = {
    "success":  {"fg": "#6EE7B7", "bg": "#0A2A1F", "strip": "#34D399"},
    "failure":  {"fg": "#FCA5A5", "bg": "#2A1010", "strip": "#F87171"},
    "cancelled": {"fg": "#FCD34D", "bg": "#2A1F08", "strip": "#FBBF24"},
    "skipped":  {"fg": "#A1A1AA", "bg": "#1A1A1C", "strip": "#71717A"},
    "running":  {"fg": "#A5ACED", "bg": "#1E1F3A", "strip": "#6E7AE0"},
    "pending":  {"fg": "#A1A1AA", "bg": "#1A1A1C", "strip": "#3F3F46"},
}

TYPE_TOKENS_LIGHT = {
    "python":            {"fg": "#4338CA", "bg": "#EEF0FC"},   # Indigo
    "excel_powerquery":  {"fg": "#047857", "bg": "#ECFDF5"},   # Emerald
    "powerbi_refresh":   {"fg": "#B45309", "bg": "#FFFBEB"},   # Amber
    "sub_workflow":      {"fg": "#6D28D9", "bg": "#F3F0FF"},   # Violet
}
TYPE_TOKENS_DARK = {
    "python":            {"fg": "#A5ACED", "bg": "#1E1F3A"},
    "excel_powerquery":  {"fg": "#6EE7B7", "bg": "#0A2A1F"},
    "powerbi_refresh":   {"fg": "#FCD34D", "bg": "#2A1F08"},
    "sub_workflow":      {"fg": "#C4B5FD", "bg": "#221A3A"},
}

LOG_LEVEL_TOKENS_LIGHT = {
    "ERROR":   "#B91C1C",
    "WARNING": "#B45309",
    "INFO":    "#18181B",
    "DEBUG":   "#71717A",
}
LOG_LEVEL_TOKENS_DARK = {
    "ERROR":   "#FCA5A5",
    "WARNING": "#FCD34D",
    "INFO":    "#FAFAFA",
    "DEBUG":   "#71717A",
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
    fg = colors["text_primary"] if dark else colors["text_inverse"]
    return f"""
QPushButton {{
    background: {colors["danger"]};
    color: {fg};
    border: none;
    border-radius: {int(radius)}px;
    padding: {padding};
    font-weight: 700;
    text-align: center;
}}
QPushButton:hover {{
    background: {colors["danger_hover"]};
}}
QPushButton:pressed {{
    background: {colors["danger_pressed"]};
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
    # V8：焦点环改用 box-shadow 柔和光晕，替代硬 outline（通过 border + padding 模拟）
    focus_shadow = SHADOW_TOKENS["focus_ring"]
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
        border-radius: {CORNER_RADIUS["small"]}px;
        padding: 0px 6px;
        background: transparent;
        color: {C["primary"]};
        font-weight: 500;
        font-size: 13px;
        text-align: center;
    }}

    QToolBar QToolButton:hover {{
        background: {C["surface"]};
    }}

    /* --- Panels & Cards --- */
    QFrame#LeftPanel, QFrame#RightPanel {{
        background: {C["surface_primary"]};
    }}

    QFrame#CenterPanel {{
        background: {C["background"]};
    }}

    /* Fold Strips (24px) */
    QFrame#FoldStrip {{
        background: {C["surface_header"]};
    }}
    QFrame#FoldBtnWrap {{
        background: {C["surface_secondary"]};
        border-radius: {CORNER_RADIUS["small"]}px;
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
        background: {C["surface"]};
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
        border: 1px solid {C["border"]};
        border-radius: {CORNER_RADIUS["small"]}px;
        min-height: 30px;
        padding: 0px 10px;
        background: {C["background"]};
        color: {C["text_primary"]};
        selection-background-color: {C["primary"]};
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        background: {C["background"]};
        border: 1px solid {C["primary"]};
    }}

    QPlainTextEdit, QTextEdit {{
        border: 1px solid {C["border"]};
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 8px 12px;
        background: {C["background"]};
    }}

    /* --- Buttons --- */
    QPushButton {{
        border: none;
        border-radius: {CORNER_RADIUS["small"]}px;
        background: {C["surface"]};
        padding: 6px 14px;
        color: {C["text_primary"]};
        font-weight: 500;
        text-align: center;
    }}

    QPushButton:hover {{
        background: {C["hover"]};
    }}

    /* U-P2-2 焦点反馈：柔和 indigo 光晕，不影响布局 */
    QPushButton:focus, QToolButton:focus {{
        border: 1px solid {C["focus_ring"]};
    }}
    QCheckBox:focus, QRadioButton:focus {{
        outline: 2px solid {C["focus_ring"]};
    }}

    /* V8 图标按钮（主题切换等）：padding 归零、文字居中、字号略大 */
    QPushButton#IconThemeButton {{
        background: {C["surface"]};
        border: 1px solid {C["border"]};
        border-radius: {CORNER_RADIUS["default"]}px;
        padding: 0;
        text-align: center;
        font-size: 15px;
    }}
    QPushButton#IconThemeButton:hover {{
        background: {C["hover"]};
        border-color: {C["primary"]};
    }}

    QPushButton#primary {{
        background: {C["primary"]};
        color: {C["text_inverse"]};
    }}

    QPushButton#primary:hover {{
        background: {C["primary_hover"]};
    }}

    QPushButton#primarySmall {{
        background: {C["primary_aa"]};
        color: {C["text_inverse"]};
        border-radius: 8px;
        padding: 0px 14px;
        font-weight: 700;
        font-size: 13px;
    }}
    QPushButton#primarySmall:hover {{
        background: {C["primary_hover"]};
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

    /* Header link buttons (e.g., 日志工具条)；兼容 QToolButton（如 btn_level "级别 ▾"） */
    QPushButton#headerLink, QToolButton#headerLink {{
        background: transparent;
        border: none;
        padding: 0px 6px;
        color: {C["primary"]};
        font-weight: 500;
        font-size: 11px;
        text-align: center;
    }}
    QPushButton#headerLink:hover, QToolButton#headerLink:hover {{
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
        text-align: center;
    }}
    QPushButton#wfPill:hover {{ background: {C["hover"]}; }}
    QPushButton#wfDangerPill {{
        background: {C["surface"]};
        border-radius: 16px;
        padding: 0px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {C["danger"]};
        text-align: center;
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
        text-align: center;
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


def get_app_palette(dark: bool = False):
    """按主题构造应用级 QPalette。

    QSS 覆盖不到的原生元素（菜单、tooltip 缺省色、禁用态文字、未样式化控件的
    底色/文字）跟随主题，避免暗色模式下出现系统亮色残留。
    """
    from PySide6.QtGui import QColor, QPalette

    C = get_colors(dark)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(C["surface_primary"]))
    p.setColor(QPalette.WindowText, QColor(C["text_primary"]))
    p.setColor(QPalette.Base, QColor(C["background"]))
    p.setColor(QPalette.AlternateBase, QColor(C["surface_secondary"]))
    p.setColor(QPalette.Text, QColor(C["text_primary"]))
    p.setColor(QPalette.Button, QColor(C["surface_secondary"]))
    p.setColor(QPalette.ButtonText, QColor(C["text_primary"]))
    p.setColor(QPalette.ToolTipBase, QColor(C["surface_card"]))
    p.setColor(QPalette.ToolTipText, QColor(C["text_primary"]))
    # 选区用与 QSS 相同的 selected_bg/selected_text 对（暗色下 primary+白字对比度仅 3.8:1）
    p.setColor(QPalette.Highlight, QColor(C["selected_bg"]))
    p.setColor(QPalette.HighlightedText, QColor(C["selected_text"]))
    p.setColor(QPalette.PlaceholderText, QColor(C["text_tertiary"]))
    p.setColor(QPalette.Link, QColor(C["primary"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(C["text_tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(C["text_tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C["text_tertiary"]))
    return p


_MSG_ICON_MAP = None


def msg_custom_buttons(
    parent, dark: bool, title: str, text: str,
    buttons: list, *, icon: str = "question", default: int = 0,
) -> int:
    """弹出已主题化的自定义按钮消息框，返回被点击按钮的下标。

    Args:
        buttons: [(label, QMessageBox.ButtonRole), ...]，按显示顺序添加
        icon: question / warning / critical / information
        default: 默认按钮下标（buttons 内）

    Returns:
        被点击按钮的下标；用户按 Esc/关闭窗口且未命中任何按钮时为 -1（调用方按取消处理）。
    """
    from PySide6.QtWidgets import QMessageBox

    global _MSG_ICON_MAP
    if _MSG_ICON_MAP is None:
        _MSG_ICON_MAP = {
            "question": QMessageBox.Question,
            "warning": QMessageBox.Warning,
            "critical": QMessageBox.Critical,
            "information": QMessageBox.Information,
        }
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(_MSG_ICON_MAP.get(icon, QMessageBox.Question))
    added = [msg.addButton(label, role) for label, role in buttons]
    if added and 0 <= default < len(added):
        msg.setDefaultButton(added[default])
    msg.setStyleSheet(_MSG_BOX_STYLE.format(**_style_colors(dark)))
    # exec_ 与 exec 等价；用 exec_ 以兼容既有测试对 QMessageBox.exec_ 的补丁约定
    msg.exec_()
    clicked = msg.clickedButton()
    if clicked in added:
        return added.index(clicked)
    return -1


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
