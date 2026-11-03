# -*- coding: utf-8 -*-
"""Build run-mode controls from one label/icon/action definition per button."""

RUN_MODE_BUTTONS = (
    ("btn_run_from", " 从选中步骤开始", "从当前选中的步骤开始运行后续步骤", "从选中步骤开始", "run.from", "from_step"),
    ("btn_run_only", " 只运行选中步骤", "只运行当前选中的单个步骤", "只运行选中步骤", "run.only", "only_step"),
    ("btn_run_range", " 区间运行", "选择起点与终点步骤，连续运行这一段（含两端）", "区间运行", "run.from", "step_range"),
    ("btn_run_stage", " 只运行该阶段", "只运行当前选中步骤所属的阶段", "只运行该阶段", "run.only", "only_stage"),
    ("btn_run_from_stage", " 从该阶段开始", "从当前阶段开始运行后续阶段", "从该阶段开始", "run.from", "from_stage"),
    ("btn_retry", " 重试失败步骤", "重试最近一次运行失败的步骤", "重试失败步骤", "run.retry", "retry_failed"),
)


def setup_run_controls(panel, *, ui, colors, set_icon_button):
    layout = ui.QVBoxLayout(panel)
    layout.setContentsMargins(4, 0, 4, 0)
    layout.setSpacing(8)
    header = ui.QLabel("运行控制")
    font = ui.QFont(header.font())
    font.setPointSize(15)
    font.setWeight(ui.QFont.Weight.Bold)
    header.setFont(font)
    layout.addWidget(header)

    panel.lbl_selected = ui.QLabel("未选中步骤")
    panel.lbl_selected.setObjectName("selectedStepLabel")
    panel.lbl_selected.setStyleSheet(f"""
            QLabel#selectedStepLabel {{
                color: {colors["text_tertiary"]};
                font-size: 11px;
                padding: 2px 0px;
            }}
        """)
    layout.addWidget(panel.lbl_selected)

    def add_button(attr, text, tooltip, accessible, icon_key, callback, target, *, kind="runGhost", height=32):
        button = ui.QPushButton(text)
        setattr(panel, attr, button)
        button.setObjectName(kind)
        button.setFixedHeight(height)
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible)
        color = colors["text_inverse"] if kind == "runPrimary" else colors["primary"]
        set_icon_button(button, icon_key, color=color)
        button.clicked.connect(callback)
        target.addWidget(button)

    add_button(
        "btn_run_all", " 全流程运行", "从第一阶段开始运行整个工作流", "全流程运行", "run.all",
        lambda: panel._run("full"), layout, kind="runPrimary", height=36,
    )
    ghost = ui.QWidget()
    ghost_layout = ui.QVBoxLayout(ghost)
    ghost_layout.setContentsMargins(0, 0, 0, 0)
    ghost_layout.setSpacing(2)
    for attr, text, tooltip, accessible, icon_key, mode in RUN_MODE_BUTTONS:
        add_button(
            attr, text, tooltip, accessible, icon_key,
            lambda _checked=False, mode=mode: panel._run(mode), ghost_layout,
        )
    add_button(
        "btn_dry_run", " 工作流预演", "预览执行计划，不实际执行", "工作流预演", "run.dry",
        panel.dry_run_clicked.emit, ghost_layout, kind="runGhostMuted", height=28,
    )
    layout.addWidget(ghost)
