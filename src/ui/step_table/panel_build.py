# -*- coding: utf-8 -*-
"""StepTablePanel 的 UI 构建与渲染（自 panel.py 纯移动提取，行为不变）。

每个函数的首个参数 ``panel`` 即 StepTablePanel 实例；跨方法调用一律走
``panel._xxx`` 委托方法，保持原有动态分发语义。
"""

import json

from PySide6.QtWidgets import (
    QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMenu,
    QAbstractItemView, QLabel,
)
from PySide6.QtCore import Qt, QTimer

from ui.step_table.stage_header import (
    StageHeaderActions,
    StageHeaderState,
    render_stage_header_row as render_stage_header_row_widget,
)
from ui.step_table.row_cells import (
    create_delete_action_widget,
    create_dependency_item,
    create_gate_widget,
    create_order_item,
    create_script_item,
    create_type_item,
)
from ui.step_table.styles import build_table_stylesheet
from ui.theme import COLORS, get_colors, get_menu_stylesheet
from ui.collapsible_section import CollapsibleSection
from ui.step_table.reorderable_table import ReorderableTable


def setup_ui(panel):
    """设置 UI"""
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    # iOS Minimal：标题栏同一行 + 右侧"添加步骤"主按钮
    panel.section = CollapsibleSection("步骤列表", collapsed=False, header_height=48, title_font_size=16, title_weight=700)
    group_layout = panel.section.body_layout

    panel.btn_add = QPushButton("添加步骤")
    panel.btn_add.setObjectName("primaryHeaderBtn")
    panel.btn_add.setFixedSize(86, 28)
    panel.btn_add.clicked.connect(panel._add_step)
    panel.btn_add.setAccessibleName("添加步骤")
    panel.btn_add.setToolTip("添加步骤到当前阶段")
    panel.section.header_actions_layout.addWidget(panel.btn_add)

    # 拖拽提示（新手可发现）
    # V9.2：init 从主题模板取色（原硬编码 #6B7280）
    _c = COLORS
    panel.drag_hint_label = QLabel("")
    panel.drag_hint_label.setWordWrap(True)
    panel.drag_hint_label.setStyleSheet(f"color:{_c['text_tertiary']}; font-size:11px;")
    group_layout.addWidget(panel.drag_hint_label)

    panel.stage_context_label = QLabel("")
    panel.stage_context_label.setWordWrap(True)
    panel.stage_context_label.setStyleSheet(f"color:{_c['text_secondary']}; font-size:11px;")
    group_layout.addWidget(panel.stage_context_label)

    # 提示条（用于展示阶段计算/依赖错误等，不再静默吞错）
    panel.hint_label = QLabel("")
    panel.hint_label.setVisible(False)
    panel.hint_label.setWordWrap(True)
    panel.hint_label.setStyleSheet(f"color:{_c['text_tertiary']}; font-size:11px;")
    group_layout.addWidget(panel.hint_label)

    # 表格 —— 使用自定义 ReorderableTable
    panel.table = ReorderableTable()
    panel.table.setColumnCount(len(panel.COLUMNS))
    panel.table.setHorizontalHeaderLabels([col[0] for col in panel.COLUMNS])
    panel.table.setSelectionBehavior(QTableWidget.SelectRows)
    panel.table.setSelectionMode(QTableWidget.ExtendedSelection)  # 任务9：支持 Ctrl/Shift 多选
    panel.table.setContextMenuPolicy(Qt.CustomContextMenu)
    panel.table.customContextMenuRequested.connect(panel._show_context_menu)
    panel.table.currentCellChanged.connect(panel._on_selection_changed)
    panel.table.itemSelectionChanged.connect(panel._on_selection_changed_by_selection)
    panel.table.setAlternatingRowColors(False)   # 背景由自绘分组卡片负责

    # 设置列宽
    header = panel.table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setContextMenuPolicy(Qt.CustomContextMenu)
    header.customContextMenuRequested.connect(panel._show_header_menu)
    header.sectionResized.connect(panel._on_header_section_resized)
    panel._apply_column_widths()
    # 舒适密度：避免控件挤压/堆叠
    panel.table.verticalHeader().setDefaultSectionSize(44)
    panel.table.verticalHeader().setVisible(False)
    panel.table.setShowGrid(False)
    panel.table.setMouseTracking(True)
    panel.table.setStyleSheet(build_table_stylesheet(COLORS))

    # 启用拖拽排序
    panel.table.setDragEnabled(True)
    panel.table.setAcceptDrops(True)
    panel.table.setDragDropMode(QAbstractItemView.DragDrop)
    panel.table.setDefaultDropAction(Qt.MoveAction)
    panel.table.setDropIndicatorShown(True)
    # 自定义拖拽信号：落库并 reload（不走 Qt InternalMove）
    panel.table.rows_dragged.connect(panel._on_rows_dragged)

    # 阶段标题栏点击折叠/展开
    panel.table.cellPressed.connect(panel._on_cell_pressed)

    group_layout.addWidget(panel.table)
    QTimer.singleShot(0, panel._fit_columns_to_viewport)

    layout.addWidget(panel.section)


def refresh_theme(panel, dark: bool):
    panel._dark = dark
    colors = get_colors(dark)
    panel.section.refresh_theme(dark)
    panel.table.setStyleSheet(build_table_stylesheet(colors))
    panel.table.refresh_theme(dark)
    panel.drag_hint_label.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")
    panel.stage_context_label.setStyleSheet(f"color:{colors['text_secondary']}; font-size:11px;")
    panel.hint_label.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")
    panel._update_stage_context_ui()


def default_column_widths(panel) -> list[int]:
    return [int(w) for _, w in panel.COLUMNS]


def sanitize_column_widths(panel, widths: list[int]) -> list[int]:
    safe = []
    for i, width in enumerate(widths):
        min_width = panel.COLUMN_MIN_WIDTHS[i] if i < len(panel.COLUMN_MIN_WIDTHS) else 48
        safe.append(max(int(min_width), int(width)))
    return safe


def load_column_widths(panel) -> list[int] | None:
    raw = panel._settings.value(panel._column_widths_key, None)
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            widths = json.loads(raw)
        else:
            widths = raw
        if not isinstance(widths, list):
            return None
        widths = [int(x) for x in widths if str(x).strip()]
        if len(widths) != panel.table.columnCount():
            return None
        return widths
    except Exception:
        return None


def apply_column_widths(panel):
    widths = panel._load_column_widths() or panel._default_column_widths()
    widths = panel._sanitize_column_widths(widths)
    panel._suspend_width_save = True
    try:
        for i, w in enumerate(widths):
            panel.table.setColumnWidth(i, int(w))
    finally:
        panel._suspend_width_save = False


def fit_columns_to_viewport(panel):
    """让关键列默认可见，把宽度波动留给名称/脚本两列。"""
    if not hasattr(panel, "table") or panel.table.columnCount() < len(panel.COLUMNS):
        return
    viewport_width = int(panel.table.viewport().width())
    if viewport_width <= 0:
        return

    fixed_total = sum(panel.FIXED_VISIBLE_COLUMNS.values())
    flex_available = viewport_width - fixed_total - 6
    min_flex = panel.NAME_MIN_WIDTH + panel.SCRIPT_MIN_WIDTH
    if flex_available >= min_flex:
        name_width = max(panel.NAME_MIN_WIDTH, min(220, int(flex_available * 0.38)))
        script_width = max(panel.SCRIPT_MIN_WIDTH, flex_available - name_width)
    else:
        name_width = panel.NAME_MIN_WIDTH
        script_width = panel.SCRIPT_MIN_WIDTH

    widths = panel._sanitize_column_widths(panel._default_column_widths())
    for col, width in panel.FIXED_VISIBLE_COLUMNS.items():
        widths[col] = int(width)
    widths[2] = int(name_width)
    widths[3] = int(script_width)

    panel._suspend_width_save = True
    try:
        for col, width in enumerate(widths):
            panel.table.setColumnWidth(col, int(width))
    finally:
        panel._suspend_width_save = False


def save_column_widths(panel):
    try:
        widths = [int(panel.table.columnWidth(i)) for i in range(panel.table.columnCount())]
        panel._settings.setValue(panel._column_widths_key, json.dumps(widths, ensure_ascii=False))
    except Exception:
        return


def reset_column_widths(panel):
    panel._settings.remove(panel._column_widths_key)
    panel._apply_column_widths()
    panel._fit_columns_to_viewport()
    try:
        win = panel.window()
        if win and hasattr(win, "statusBar"):
            sb = win.statusBar()
            if sb:
                sb.showMessage("已重置步骤列表列宽", 4000)
    except Exception:
        return


def show_header_menu(panel, pos):
    menu = QMenu(panel)
    menu.setStyleSheet(get_menu_stylesheet(panel._dark))
    act_reset = menu.addAction("重置列宽")
    act_reset.triggered.connect(panel._reset_column_widths)
    menu.exec(panel.table.horizontalHeader().mapToGlobal(pos))


def apply_enabled_state(panel):
    can_edit = panel._edit_enabled and (not panel._single_script_mode)
    panel.btn_add.setEnabled(can_edit and panel._workflow_id is not None)
    panel._update_stage_context_ui()

    panel.drag_hint_label.setText(
        '拖拽：请先开启左侧"编辑"，从"顺序(Sx-y)"列拖拽排序；拖到其他阶段即改变归属。'
        if not can_edit
        else '拖拽：从"顺序(Sx-y)"列拖拽排序；拖到其他阶段可改变归属。右键步骤：移动阶段/新建阶段。'
    )

    # 拖拽排序与编辑模式联动（编辑关闭必须禁止拖拽）
    panel.table.setDragEnabled(can_edit)
    panel.table.setAcceptDrops(can_edit)
    panel.table.setDragDropMode(
        QAbstractItemView.DragDrop if can_edit else QAbstractItemView.NoDragDrop
    )
    panel.table.setDropIndicatorShown(can_edit)
    panel.table.setToolTip(
        "" if can_edit else '编辑模式关闭：开启左侧"编辑"开关后可拖拽调整步骤顺序。'
    )

    # 行内控件需要重绘/重建才能正确禁用
    if panel._workflow_id:
        panel.load_steps(panel._workflow_id)


def update_group_ranges(panel):
    """把用途阶段的行范围同步给表格，用于"框住阶段"的卡片绘制"""
    ranges = []
    if not panel._row_meta:
        panel.table.set_group_ranges([])
        return

    start = None
    stage_uid = None
    for row, meta in enumerate(panel._row_meta):
        if meta.get("kind") == "stage_header":
            # 收尾上一个
            if start is not None:
                ranges.append({"start": start, "end": row - 1, "stage_uid": stage_uid})
            start = row
            stage_uid = meta.get("stage_uid")

    if start is not None:
        ranges.append({"start": start, "end": len(panel._row_meta) - 1, "stage_uid": stage_uid})

    panel.table.set_group_ranges(ranges)


def update_table_height(panel):
    row_h = panel.table.verticalHeader().defaultSectionSize()
    header_h = panel.table.horizontalHeader().height()
    padding = 18
    min_rows = 3
    desired = header_h + min_rows * row_h + padding
    panel.table.setMinimumHeight(desired)


def stage_label_for_uid(panel, stage_uid: str | None) -> str:
    if not stage_uid:
        return ""
    stage = next((s for s in panel._stages if s["uid"] == stage_uid), None)
    if not stage:
        return ""
    stage_idx = panel._stage_uid_to_index.get(stage_uid, 0)
    return f"S{stage_idx + 1} {stage.get('name', '阶段')}"


def update_stage_context_ui(panel):
    if not panel._workflow_id:
        panel.stage_context_label.setText("")
        panel.btn_add.setToolTip("添加步骤")
        return
    can_edit = panel._edit_enabled and (not panel._single_script_mode)
    stage_label = panel._stage_label_for_uid(panel._selected_stage_uid)
    if panel._single_script_mode:
        text = "当前为单脚本模式：步骤由右侧配置生成。"
        add_tip = "单脚本模式下不能新增步骤"
    elif stage_label:
        text = f"当前阶段：{stage_label} · 点击「添加步骤」会加入此阶段。"
        add_tip = f"添加步骤到当前阶段：{stage_label}"
    else:
        text = "当前阶段：未选择 · 新增步骤默认进入第一个阶段。"
        add_tip = "添加步骤到第一个阶段"
    panel.stage_context_label.setText(text)
    if can_edit:
        panel.btn_add.setToolTip(add_tip)
    else:
        panel.btn_add.setToolTip(f"{add_tip}\n（需要先开启编辑）")


def refresh_stage_headers(panel):
    if panel._single_script_mode or not panel._stage_header_rows:
        return
    counts = {}
    for meta in panel._row_meta:
        if meta.get("kind") == "step":
            suid = meta.get("stage_uid")
            counts[suid] = counts.get(suid, 0) + 1
    for stage in panel._stages:
        stage_uid = stage["uid"]
        row = panel._stage_header_rows.get(stage_uid)
        if row is None:
            continue
        panel._render_stage_header_row(
            row=row,
            stage_uid=stage_uid,
            stage_idx=panel._stage_uid_to_index.get(stage_uid, 0),
            stage_name=stage.get("name", "阶段"),
            step_count=counts.get(stage_uid, 0),
        )


def render_stage_header_row(
    panel,
    row: int,
    stage_uid: str,
    stage_idx: int,
    stage_name: str,
    step_count: int,
):
    """渲染用途阶段标题条（iOS grouped list 风格）"""
    colors = get_colors(panel._dark)
    can_edit = panel._edit_enabled and (not panel._single_script_mode)
    is_first = stage_idx <= 0
    is_last = stage_idx >= max(0, len(panel._stages) - 1)
    render_stage_header_row_widget(
        table=panel.table,
        style=panel.style(),
        state=StageHeaderState(
            row=row,
            column_count=panel.table.columnCount(),
            stage_uid=stage_uid,
            stage_idx=stage_idx,
            stage_name=stage_name,
            step_count=step_count,
            selected=stage_uid == panel._selected_stage_uid,
            can_edit=can_edit,
            is_first=is_first,
            is_last=is_last,
            is_collapsed=panel._stage_collapsed.get(stage_uid, False),
            colors=colors,
        ),
        actions=StageHeaderActions(
            toggle_collapse=panel._toggle_stage_collapse,
            move_stage_order=panel._move_stage_order,
            insert_stage_after=panel._insert_stage_after,
            show_stage_menu=panel._show_stage_menu,
        ),
    )


def set_row_data(
    panel,
    row: int,
    step,
    prev_step=None,
    workflow_map=None,
    stage_idx: int = 0,
    within_idx: int = 0,
    batch_idx: int = 0,
):
    """设置行数据"""
    can_edit = panel._edit_enabled and (not panel._single_script_mode)
    panel.table.setItem(row, 0, create_order_item(step, panel._stages, stage_idx, within_idx, batch_idx))
    panel.table.setItem(row, 1, create_type_item(step.step_type, panel._dark))
    panel.table.setItem(row, 2, QTableWidgetItem(step.name))
    panel.table.setItem(row, 3, create_script_item(step, workflow_map))
    panel.table.setItem(row, 4, create_dependency_item(step, panel._uid_display_map, get_colors(panel._dark)))
    panel.table.setCellWidget(
        row,
        5,
        create_gate_widget(
            step,
            enabled=can_edit,
            on_state_changed=lambda state, r=row, sid=step.id: panel._on_gate_changed_with_select(
                r, sid, state
            ),
        ),
    )
    panel.table.setCellWidget(
        row,
        6,
        create_delete_action_widget(
            style=panel.style(),
            dark=panel._dark,
            enabled=can_edit,
            on_delete=lambda _=False, r=row, sid=step.id: panel._delete_step_with_select(r, sid),
        ),
    )
