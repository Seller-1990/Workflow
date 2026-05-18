# -*- coding: utf-8 -*-
"""步骤列表面板（StepTablePanel）"""

import json
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMenu, QMessageBox, QGroupBox,
    QCheckBox, QComboBox, QAbstractItemView, QLabel, QInputDialog,
    QToolButton, QStyle, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot, QRectF, QSize, QSettings, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPalette

from config import StepType, APP_NAME
from database import (
    get_steps_by_workflow,
    create_step,
    delete_step,
    update_step,
    reorder_steps,
    get_workflow_uid_name_map,
    copy_step,
    list_stages,
    create_stage,
    update_stage,
    delete_stage,
    get_stage_order_map,
    get_workflow_by_id,
    get_session,
)
from ui.theme import (
    COLORS,
    CORNER_RADIUS,
    get_colors,
    get_status_tokens,
    get_type_tokens,
    get_menu_stylesheet,
    msg_information,
    msg_warning,
    msg_critical,
    msg_question,
    input_get_text,
    input_get_item,
)
from ui.collapsible_section import CollapsibleSection
from ui.step_table.reorderable_table import ReorderableTable, STAGE_COLORS


class StepTablePanel(QWidget):
    """步骤列表表格面板

    列：顺序 / 类型 / 名称 / 脚本 / 依赖 / 是否前置 / 操作
    """

    # 信号
    step_selected = Signal(int)  # step_id
    steps_changed = Signal()

    # 列定义
    COLUMNS = [
        ("顺序", 48),
        ("类型", 72),
        ("名称", 120),
        ("脚本", 448),
        ("依赖", 64),
        ("前置", 44),
        ("操作", 80),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._workflow_id = None
        self._single_script_mode = False
        self._edit_enabled = True
        self._parallel_available = True
        self._selected_step_id = None

        # UI 状态持久化（列宽等）
        self._settings = QSettings(APP_NAME, "ui")
        self._column_widths_key = "StepTable/column_widths"
        self._width_save_timer = QTimer(self)
        self._width_save_timer.setSingleShot(True)
        self._width_save_timer.timeout.connect(self._save_column_widths)
        self._suspend_width_save = False

        # 用途阶段（人为归类）
        self._stages = []  # [{uid,name,order,color}, ...]（按 order）
        self._stage_uid_to_index = {}  # stage_uid -> index (1-based display uses +1)

        # 视觉行模型（表格行 -> 元信息）
        # kind: "stage_header" | "step"
        self._row_meta = []

        # 阶段折叠状态
        self._stage_collapsed = {}       # stage_uid -> bool
        self._stage_header_rows = {}     # stage_uid -> row index
        self._row_by_step_id = {}        # R4-#5: step_id -> row index（O(1) 状态刷新）

        # 执行批次（自动）：compute_batches 输出，用于显示 Bx 与高级操作
        self._step_batch_map = {}   # step_id -> batch_idx
        self._batch_deps_map = {}   # batch_idx -> deps list (fingerprint)
        # uid -> {"code": "S2-2", "stage_name": "阶段名", "step_name": "步骤名", "step_id": 123}
        self._uid_display_map = {}
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # iOS Minimal：标题栏同一行 + 右侧"添加步骤"主按钮
        self.section = CollapsibleSection("步骤列表", collapsed=False, header_height=48, title_font_size=16, title_weight=700)
        group_layout = self.section.body_layout

        self.btn_add = QPushButton("添加步骤")
        self.btn_add.setObjectName("primaryHeaderBtn")
        self.btn_add.setFixedSize(86, 28)
        self.btn_add.clicked.connect(self._add_step)
        self.section.header_actions_layout.addWidget(self.btn_add)

        # 拖拽提示（新手可发现）
        self.drag_hint_label = QLabel("")
        self.drag_hint_label.setWordWrap(True)
        self.drag_hint_label.setStyleSheet("color:#6B7280; font-size:11px;")
        group_layout.addWidget(self.drag_hint_label)

        # 提示条（用于展示阶段计算/依赖错误等，不再静默吞错）
        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#6B7280; font-size:11px;")
        group_layout.addWidget(self.hint_label)

        # 表格 —— 使用自定义 ReorderableTable
        self.table = ReorderableTable()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.currentCellChanged.connect(self._on_selection_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed_by_selection)
        self.table.setAlternatingRowColors(False)   # 背景由自绘分组卡片负责

        # 设置列宽
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        header.sectionResized.connect(self._on_header_section_resized)
        self._apply_column_widths()
        # 舒适密度：避免控件挤压/堆叠
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setStyleSheet(self._build_table_stylesheet(COLORS))

        # 启用拖拽排序
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDrop)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setDropIndicatorShown(True)
        # 自定义拖拽信号：落库并 reload（不走 Qt InternalMove）
        self.table.rows_dragged.connect(self._on_rows_dragged)

        # 阶段标题栏点击折叠/展开
        self.table.cellPressed.connect(self._on_cell_pressed)

        group_layout.addWidget(self.table)

        layout.addWidget(self.section)

    def _build_table_stylesheet(self, colors: dict) -> str:
        return f"""
            QTableWidget {{
                background: transparent;
                border: none;
                border-radius: {CORNER_RADIUS["default"]}px;
            }}
            QWidget {{
                background: transparent;
                border: none;
            }}
            QHeaderView::section {{
                background: {colors["surface_header"]};
                color: {colors["text_secondary"]};
                font-weight: 600;
                border: none;
                padding: 6px 8px;
            }}
            QTableView::item {{
                background: transparent;
                padding: 4px 8px;
                color: {colors["text_primary"]};
            }}
            QTableView::item:selected {{
                background: {colors["selected_bg"]};
                color: {colors["selected_text"]};
            }}
            QTableView::item:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#tableIcon, QPushButton#tableIcon {{
                padding: 0px;
                border-radius: {CORNER_RADIUS["default"]}px;
                min-width: 32px;
                min-height: 32px;
                border: none;
                background: transparent;
            }}
            QToolButton#tableIcon:hover, QPushButton#tableIcon:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#tableIcon:pressed, QPushButton#tableIcon:pressed {{
                background: {colors["selected_bg"]};
            }}
            QToolButton#tableIcon:disabled, QPushButton#tableIcon:disabled {{
                background: transparent;
                border: none;
            }}
            QToolButton#tableDangerIcon, QPushButton#tableDangerIcon {{
                padding: 0px;
                border-radius: {CORNER_RADIUS["default"]}px;
                min-width: 32px;
                min-height: 32px;
                border: none;
                background: transparent;
            }}
            QToolButton#tableDangerIcon:hover, QPushButton#tableDangerIcon:hover {{
                background: {colors["danger"]}22;
            }}
            QToolButton#tableDangerIcon:pressed, QPushButton#tableDangerIcon:pressed {{
                background: {colors["danger"]}44;
            }}
            QToolButton#tableDangerIcon:disabled, QPushButton#tableDangerIcon:disabled {{
                background: transparent;
                border: none;
            }}

            QCheckBox {{
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1.5px solid {colors["border"]};
                border-radius: 4px;
                background: {colors["background"]};
            }}
            QCheckBox::indicator:checked {{
                background: {colors["primary"]};
                border: 1.5px solid {colors["primary"]};
            }}

            /* Stage header action pill (iOS-like compact toolbar) */
            QFrame#stagePill {{
                background: {colors["background"]};
                border: 1px solid {colors["border"]};
                border-radius: {CORNER_RADIUS["default"]}px;
            }}
            QToolButton#stagePillBtn {{
                padding: 0px;
                border: 0px;
                border-radius: {CORNER_RADIUS["small"]}px;
                background: transparent;
            }}
            QToolButton#stagePillBtn:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#stagePillBtn:pressed {{
                background: {colors["pressed"]};
            }}
            QToolButton#stagePillBtn:disabled {{
                background: transparent;
            }}
        """

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.section.refresh_theme(dark)
        self.table.setStyleSheet(self._build_table_stylesheet(colors))
        self.table.refresh_theme(dark)
        self.drag_hint_label.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")
        self.hint_label.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")

    def _default_column_widths(self) -> list[int]:
        return [int(w) for _, w in self.COLUMNS]

    def _load_column_widths(self) -> list[int] | None:
        raw = self._settings.value(self._column_widths_key, None)
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
            if len(widths) != self.table.columnCount():
                return None
            return widths
        except Exception:
            return None

    def _apply_column_widths(self):
        widths = self._load_column_widths() or self._default_column_widths()
        self._suspend_width_save = True
        try:
            for i, w in enumerate(widths):
                self.table.setColumnWidth(i, int(max(40, w)))
        finally:
            self._suspend_width_save = False

    def _save_column_widths(self):
        try:
            widths = [int(self.table.columnWidth(i)) for i in range(self.table.columnCount())]
            self._settings.setValue(self._column_widths_key, json.dumps(widths, ensure_ascii=False))
        except Exception:
            return

    def _on_header_section_resized(self, _logical: int, _old: int, _new: int):
        if self._suspend_width_save:
            return
        # debounce：避免拖拽时频繁写入 settings
        self._width_save_timer.start(200)

    def _reset_column_widths(self):
        self._settings.remove(self._column_widths_key)
        self._apply_column_widths()
        try:
            win = self.window()
            if win and hasattr(win, "statusBar"):
                sb = win.statusBar()
                if sb:
                    sb.showMessage("已重置步骤列表列宽", 4000)
        except Exception:
            return

    def _show_header_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))
        act_reset = menu.addAction("重置列宽")
        act_reset.triggered.connect(self._reset_column_widths)
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        self.btn_add.setEnabled(can_edit)

        self.drag_hint_label.setText(
            '拖拽：请先开启左侧"编辑"，从"顺序(Sx-y)"列拖拽排序；拖到其他用途阶段即改变归类。'
            if not can_edit
            else '拖拽：从"顺序(Sx-y)"列拖拽排序；拖到其他用途阶段可改变归类。右键步骤：移动阶段/新建阶段。'
        )

        # 拖拽排序与编辑模式联动（编辑关闭必须禁止拖拽）
        self.table.setDragEnabled(can_edit)
        self.table.setAcceptDrops(can_edit)
        self.table.setDragDropMode(
            QAbstractItemView.DragDrop if can_edit else QAbstractItemView.NoDragDrop
        )
        self.table.setDropIndicatorShown(can_edit)
        self.table.setToolTip(
            "" if can_edit else '编辑模式关闭：开启左侧"编辑"开关后可拖拽调整步骤顺序。'
        )

        # 行内控件需要重绘/重建才能正确禁用
        if self._workflow_id:
            self.load_steps(self._workflow_id)

    def load_steps(self, workflow_id: int):
        """加载步骤列表（按"用途阶段"分组展示；批次(Bx)由 compute_batches 自动计算）"""
        self._workflow_id = workflow_id
        self._selected_step_id = None
        self.table.setRowCount(0)
        self.table.clearSpans()
        self.hint_label.setVisible(False)
        self.hint_label.setText("")

        steps = get_steps_by_workflow(workflow_id)
        # CA1 修复：用轻量映射替代 list_workflows() 全 ORM 加载
        workflow_map = get_workflow_uid_name_map()
        if self._single_script_mode:
            steps = [s for s in steps if s.uid == "single_script"]

        # 用途阶段（人为归类）：始终展示阶段标题条（即使为空）
        self._stages = []
        self._stage_uid_to_index = {}
        if not self._single_script_mode:
            try:
                stages = list_stages(workflow_id)
            except Exception:
                stages = []
            for i, st in enumerate(stages):
                self._stages.append(
                    {
                        "uid": st.uid,
                        "name": st.name,
                        "order": int(st.order or 0),
                        "color": getattr(st, "color", None),
                    }
                )
                self._stage_uid_to_index[st.uid] = i

        # 执行批次（自动）：用于展示 Bx（与 DAG/预演一致）
        self._step_batch_map = {}
        self._batch_deps_map = {}
        stage_map = {}
        if steps and not self._single_script_mode:
            try:
                from engine import WorkflowEngine
                from exceptions import WorkflowError
                wf = get_workflow_by_id(workflow_id)
                stage_map = get_stage_order_map(workflow_id)
                if wf:
                    batches = WorkflowEngine.compute_batches(wf, steps, stage_map)
                    for batch_idx, batch in enumerate(batches):
                        deps = batch[0].get_depends_on() if batch else []
                        self._batch_deps_map[batch_idx] = list(deps)
                        for s in batch:
                            self._step_batch_map[s.id] = batch_idx
            except WorkflowError as e:
                self.hint_label.setText(f"批次计算失败：{e}（请检查依赖/阶段配置）。")
                self.hint_label.setToolTip(traceback.format_exc())
                self.hint_label.setVisible(True)
            except Exception as e:
                self.hint_label.setText(f"批次计算异常：{e}（已按顺序展示）。")
                self.hint_label.setToolTip(traceback.format_exc())
                self.hint_label.setVisible(True)

        # 计算"展示顺序"：按用途阶段 order + step.order
        def _purpose_stage_order(s):
            return int(stage_map.get(getattr(s, "stage_uid", None), 0) or 0)

        steps_sorted = list(sorted(steps, key=lambda s: (_purpose_stage_order(s), s.order)))
        prev_by_id = {}
        for i, s in enumerate(steps_sorted):
            prev_by_id[s.id] = steps_sorted[i - 1] if i > 0 else None

        # 构建视觉行模型（阶段标题条 + 该阶段步骤）
        self._row_meta = []
        if self._single_script_mode:
            for s in steps_sorted:
                self._row_meta.append({"kind": "step", "step_id": s.id, "stage_uid": getattr(s, "stage_uid", None)})
        else:
            # 确保至少一个阶段（防御：极端情况下 list_stages 失败）
            if not self._stages:
                self._stages = [{"uid": "", "name": "默认阶段", "order": 0, "color": None}]
                self._stage_uid_to_index = {"": 0}
            for st in self._stages:
                self._row_meta.append({"kind": "stage_header", "stage_uid": st["uid"]})
                for s in steps_sorted:
                    if getattr(s, "stage_uid", None) == st["uid"]:
                        self._row_meta.append({"kind": "step", "step_id": s.id, "stage_uid": st["uid"]})

        self.table.setRowCount(len(self._row_meta))
        self._update_group_ranges()
        # R2-#7: 空状态提示（无步骤时显式告知用户怎么办）
        if not steps:
            if self._single_script_mode:
                self.hint_label.setText("当前为单脚本模式：在右侧配置脚本路径")
            else:
                self.hint_label.setText("暂无步骤，点击「添加步骤」开始构建工作流")
            self.hint_label.setVisible(True)

        # 渲染
        # R3-#8: 预建 id→step 映射 + (stage_uid, step_id)→within_idx 映射，
        # 替换原先每行 next(s for s in steps_sorted if s.id == ...) 的 O(n²) 查找
        step_by_id = {s.id: s for s in steps_sorted}
        if self._single_script_mode:
            # 依赖展示映射（单脚本模式下仍给出稳定编码，避免 tooltip/依赖列空白）
            self._uid_display_map = {}
            for i, s in enumerate(steps_sorted, start=1):
                try:
                    self._uid_display_map[s.uid] = {
                        "code": f"S1-{i}",
                        "stage_name": "默认阶段",
                        "step_name": s.name,
                        "step_id": s.id,
                    }
                except Exception:
                    continue
            for row, meta in enumerate(self._row_meta):
                step = step_by_id.get(meta["step_id"])
                if not step:
                    continue
                prev_step = prev_by_id.get(step.id)
                self._set_row_data(row, step, prev_step, workflow_map, stage_idx=0)
        else:
            stage_uid_to_steps = {}
            for s in steps_sorted:
                stage_uid_to_steps.setdefault(getattr(s, "stage_uid", None), []).append(s)

            stage_display_index = {st["uid"]: i for i, st in enumerate(self._stages)}
            # R3-#8: 阶段名映射 + 阶段内 step_id→within_idx 映射，O(1) 取值
            stage_name_by_uid = {st["uid"]: st["name"] for st in self._stages}
            within_idx_by_step: dict = {}
            for st_uid, st_steps in stage_uid_to_steps.items():
                for idx, s in enumerate(st_steps):
                    within_idx_by_step[(st_uid, s.id)] = idx

            # uid -> Sx-y(阶段名) 映射（用于依赖列/tooltip），需在渲染前一次性建立，避免顺序依赖
            self._uid_display_map = {}
            for st_uid, st_idx in stage_display_index.items():
                st_name = stage_name_by_uid.get(st_uid, "")
                st_steps = stage_uid_to_steps.get(st_uid, [])
                for within, s in enumerate(st_steps, start=1):
                    try:
                        self._uid_display_map[s.uid] = {
                            "code": f"S{st_idx + 1}-{within}",
                            "stage_name": st_name,
                            "step_name": s.name,
                            "step_id": s.id,
                        }
                    except Exception:
                        continue

            for row, meta in enumerate(self._row_meta):
                if meta["kind"] == "stage_header":
                    stage_uid = meta["stage_uid"]
                    stage_idx = stage_display_index.get(stage_uid, 0)
                    self._render_stage_header_row(
                        row=row,
                        stage_uid=stage_uid,
                        stage_idx=stage_idx,
                        stage_name=stage_name_by_uid.get(stage_uid, "阶段"),
                        step_count=len(stage_uid_to_steps.get(stage_uid, [])),
                    )
                else:
                    step_id = meta["step_id"]
                    step = step_by_id.get(step_id)
                    if not step:
                        continue
                    prev_step = prev_by_id.get(step.id)
                    stage_uid = meta.get("stage_uid")
                    stage_idx = stage_display_index.get(stage_uid, 0)
                    within = within_idx_by_step.get((stage_uid, step.id), 0)
                    # 给依赖编码与 tooltip 用：缓存 uid/stage/within 到 row_meta
                    try:
                        meta["uid"] = step.uid
                        meta["stage_idx"] = int(stage_idx)
                        meta["within_idx"] = int(within)
                    except Exception:
                        pass
                    batch_idx = self._step_batch_map.get(step.id, 0)
                    self._set_row_data(row, step, prev_step, workflow_map, stage_idx, within_idx=within, batch_idx=batch_idx)

        self.btn_add.setEnabled(self._edit_enabled and (not self._single_script_mode))

        self._stage_header_rows = {}
        # R4-#5: 反查 dict，update_step_status / reset_all_status 不再扫整张表
        self._row_by_step_id = {}
        for row, meta in enumerate(self._row_meta):
            if meta.get("kind") == "stage_header":
                self._stage_header_rows[meta["stage_uid"]] = row
            elif meta.get("kind") == "step" and meta.get("step_id"):
                self._row_by_step_id[int(meta["step_id"])] = row

        for stage_uid, is_collapsed in list(self._stage_collapsed.items()):
            if is_collapsed:
                header_row = self._stage_header_rows.get(stage_uid)
                if header_row is None:
                    continue
                for r, m in enumerate(self._row_meta):
                    if m.get("kind") == "step" and m.get("stage_uid") == stage_uid:
                        self.table.setRowHidden(r, True)
                stage_idx = self._stage_uid_to_index.get(stage_uid, 0)
                stage_info = next((st for st in self._stages if st["uid"] == stage_uid), None) or {"name": "阶段"}
                steps_in_stage = [m for m in self._row_meta if m.get("kind") == "step" and m.get("stage_uid") == stage_uid]
                self._render_stage_header_row(header_row, stage_uid, stage_idx, stage_info.get("name", "阶段"), len(steps_in_stage))

        self._update_table_height()

    def _update_group_ranges(self):
        """把用途阶段的行范围同步给表格，用于"框住阶段"的卡片绘制"""
        ranges = []
        if not self._row_meta:
            self.table.set_group_ranges([])
            return

        start = None
        stage_uid = None
        for row, meta in enumerate(self._row_meta):
            if meta.get("kind") == "stage_header":
                # 收尾上一个
                if start is not None:
                    ranges.append({"start": start, "end": row - 1, "stage_uid": stage_uid})
                start = row
                stage_uid = meta.get("stage_uid")

        if start is not None:
            ranges.append({"start": start, "end": len(self._row_meta) - 1, "stage_uid": stage_uid})

        self.table.set_group_ranges(ranges)

    def _update_table_height(self):
        rows = sum(1 for r in range(self.table.rowCount()) if not self.table.isRowHidden(r))
        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height()
        padding = 18
        min_rows = 3
        visible_rows = max(min_rows, rows)
        desired = header_h + visible_rows * row_h + padding
        self.table.setMinimumHeight(desired)

    def _render_stage_header_row(
        self,
        row: int,
        stage_uid: str,
        stage_idx: int,
        stage_name: str,
        step_count: int,
    ):
        """渲染用途阶段标题条（iOS grouped list 风格）"""
        colors = get_colors(self._dark)
        # 清理旧内容
        for col in range(self.table.columnCount()):
            try:
                self.table.takeItem(row, col)
            except Exception:
                pass
            try:
                self.table.setCellWidget(row, col, None)
            except Exception:
                pass

        self.table.setSpan(row, 0, 1, self.table.columnCount())
        # 标题条行高（按定稿：40）
        self.table.setRowHeight(row, 40)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignVCenter)

        # 左侧强调条：增强"这是阶段标题"的辨识度
        accent = QFrame()
        accent.setFixedSize(3, 18)
        accent.setStyleSheet(f"background:{colors['primary']}; border-radius:2px;")
        header_layout.addWidget(accent)

        is_collapsed = self._stage_collapsed.get(stage_uid, False)
        chevron_text = "▶" if is_collapsed else "▼"
        chevron = QLabel(chevron_text)
        chevron.setObjectName("stageChevron")
        chevron.setStyleSheet(f"color:{colors['text_secondary']}; font-size:12px;")
        chevron.setFixedWidth(14)
        header_layout.addWidget(chevron)

        title = QLabel(f"S{stage_idx + 1}  {stage_name}  ·  {step_count} 步")
        title.setStyleSheet(f"color:{colors['text_primary']}; font-size:13px; font-weight:600;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # 阶段顺序调整（A 方案：上移/下移按钮）
        can_edit = self._edit_enabled and (not self._single_script_mode)
        is_first = stage_idx <= 0
        is_last = stage_idx >= max(0, len(self._stages) - 1)

        pill = QFrame()
        pill.setObjectName("stagePill")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(6, 2, 6, 2)
        pill_layout.setSpacing(4)

        def _mk_btn(icon: QStyle.StandardPixmap, tip: str, enabled: bool, on_click):
            btn = QToolButton()
            btn.setObjectName("stagePillBtn")
            btn.setAutoRaise(True)
            # 行高 40 + header margins 下，32px 按钮容易被裁切（尤其 125% DPI）
            btn.setFixedSize(28, 28)
            btn.setIconSize(QSize(16, 16))
            btn.setIcon(self.style().standardIcon(icon))
            if (not can_edit) and (not enabled):
                btn.setToolTip(f"{tip}\n（需要先开启编辑）")
            else:
                btn.setToolTip(tip)
            btn.setEnabled(enabled)
            btn.clicked.connect(on_click)
            return btn

        pill_layout.addWidget(
            _mk_btn(
                QStyle.StandardPixmap.SP_ArrowUp,
                "上移阶段",
                can_edit and (not is_first),
                lambda: self._move_stage_order(stage_uid, -1),
            )
        )
        pill_layout.addWidget(
            _mk_btn(
                QStyle.StandardPixmap.SP_ArrowDown,
                "下移阶段",
                can_edit and (not is_last),
                lambda: self._move_stage_order(stage_uid, +1),
            )
        )
        pill_layout.addWidget(
            _mk_btn(
                QStyle.StandardPixmap.SP_FileDialogNewFolder,
                "在此阶段后插入新阶段",
                can_edit,
                lambda: self._insert_stage_after(stage_uid),
            )
        )
        pill_layout.addWidget(
            _mk_btn(
                QStyle.StandardPixmap.SP_TitleBarMenuButton,
                "阶段操作",
                can_edit,
                lambda: self._show_stage_menu(stage_uid, pill.mapToGlobal(pill.rect().bottomLeft())),
            )
        )

        header_layout.addWidget(pill)

        header_widget.setStyleSheet(
            f"background:transparent; border:none; border-radius:{CORNER_RADIUS['large']}px;"
        )

        # 使用一个空 item 作为占位（避免 selection/drag 误触发）
        item = QTableWidgetItem("")
        item.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, 0, item)
        self.table.setCellWidget(row, 0, header_widget)

    def _on_cell_pressed(self, row: int, col: int):
        if row < 0 or row >= len(self._row_meta):
            return
        meta = self._row_meta[row]
        if meta.get("kind") == "stage_header":
            self._toggle_stage_collapse(meta["stage_uid"])

    def _toggle_stage_collapse(self, stage_uid: str):
        is_collapsed = self._stage_collapsed.get(stage_uid, False)
        new_collapsed = not is_collapsed
        self._stage_collapsed[stage_uid] = new_collapsed

        for r, m in enumerate(self._row_meta):
            if m.get("kind") == "step" and m.get("stage_uid") == stage_uid:
                self.table.setRowHidden(r, new_collapsed)

        header_row = self._stage_header_rows.get(stage_uid)
        if header_row is not None:
            stage_idx = self._stage_uid_to_index.get(stage_uid, 0)
            stage_info = next((st for st in self._stages if st["uid"] == stage_uid), None) or {"name": "阶段"}
            steps_in_stage = [m for m in self._row_meta if m.get("kind") == "step" and m.get("stage_uid") == stage_uid]
            self._render_stage_header_row(header_row, stage_uid, stage_idx, stage_info.get("name", "阶段"), len(steps_in_stage))

        self._update_table_height()

    def _set_row_data(
        self,
        row: int,
        step,
        prev_step=None,
        workflow_map=None,
        stage_idx: int = 0,
        within_idx: int = 0,
        batch_idx: int = 0,
    ):
        """设置行数据"""
        # 顺序：用途阶段序号 + 阶段内序号 + 执行批次(Bx)
        order_text = f"S{stage_idx + 1}-{within_idx + 1}"
        if batch_idx is not None:
            order_text += f"  B{int(batch_idx) + 1}"
        order_item = QTableWidgetItem(order_text)
        order_item.setData(Qt.UserRole, step.id)
        order_item.setTextAlignment(Qt.AlignCenter)
        stage_name = ""
        try:
            stage_uid = getattr(step, "stage_uid", None)
            stage_name = next((s["name"] for s in self._stages if s["uid"] == stage_uid), "")
        except Exception:
            stage_name = ""
        batch_tip = f"执行批次 B{int(batch_idx) + 1}" if batch_idx is not None else "执行批次未知"
        order_item.setToolTip(f"用途阶段 S{stage_idx + 1} {stage_name}\n{batch_tip}")
        self.table.setItem(row, 0, order_item)

        # 类型（带类型特有颜色）
        type_name = StepType.display_name(step.step_type)
        type_item = QTableWidgetItem(type_name)
        type_tokens = get_type_tokens(self._dark)
        token = type_tokens.get(step.step_type)
        if token:
            type_item.setBackground(QColor(token["bg"]))
            type_item.setForeground(QColor(token["fg"]))
        type_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 1, type_item)

        # 名称（含阶段前缀标签）
        name_item = QTableWidgetItem(step.name)
        self.table.setItem(row, 2, name_item)

        # 脚本
        script_text = step.script_path or ""
        if step.step_type == "sub_workflow" and workflow_map:
            script_text = workflow_map.get(step.script_path, step.script_path or "")
        script_item = QTableWidgetItem(script_text)
        script_item.setToolTip(script_text)
        self.table.setItem(row, 3, script_item)

        # 依赖：显示 Sx-y 编码（不在表格内直接编辑，避免拥挤；编辑在步骤编辑器中完成）
        dep_displays = []
        dep_tool_lines = []
        try:
            for uid in (step.get_depends_on() or []):
                info = self._uid_display_map.get(uid)
                if not info:
                    continue
                code = info.get("code") or ""
                stn = info.get("stage_name") or ""
                display = f"{code}({stn})" if (code and stn) else code
                if display:
                    dep_displays.append(display)
                    dep_tool_lines.append(f"{display}  ·  {info.get('step_name') or ''}".rstrip())
        except Exception:
            dep_displays = []
            dep_tool_lines = []
        dep_text = ", ".join(dep_displays) if dep_displays else ""
        dep_item = QTableWidgetItem(dep_text)
        dep_item.setTextAlignment(Qt.AlignCenter)
        c = get_colors(self._dark)
        dep_item.setForeground(QColor(c["primary"]) if dep_text else QColor(c["text_tertiary"]))
        if dep_tool_lines:
            dep_item.setToolTip("依赖：\n" + "\n".join(dep_tool_lines))
        else:
            dep_item.setToolTip("（无显式依赖）")
        self.table.setItem(row, 4, dep_item)

        # 前置（开关）
        gate_widget = QWidget()
        gate_layout = QHBoxLayout(gate_widget)
        gate_layout.setContentsMargins(0, 0, 0, 0)
        gate_layout.setAlignment(Qt.AlignCenter)
        gate_check = QCheckBox()
        gate_check.setChecked(step.is_gate)
        gate_check.setToolTip("前置步骤：启用后会阻塞后续并行步骤（确保关键步骤先完成）。")
        gate_check.setEnabled(self._edit_enabled and (not self._single_script_mode))
        # 使用默认参数捕获当前值，避免闭包问题
        def _make_gate_handler(r, sid):
            return lambda state: self._on_gate_changed_with_select(r, sid, state)
        gate_check.stateChanged.connect(_make_gate_handler(row, step.id))
        gate_layout.addWidget(gate_check)
        self.table.setCellWidget(row, 5, gate_widget)

        # 操作（减法：去掉行内 ↑↓，使用拖拽排序）
        can_edit = self._edit_enabled and (not self._single_script_mode)
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(2, 0, 2, 0)
        action_layout.setSpacing(4)
        action_layout.setAlignment(Qt.AlignCenter)

        btn_delete = QToolButton()
        btn_delete.setObjectName("tableDangerIcon")
        btn_delete.setAutoRaise(True)
        btn_delete.setText("")
        btn_delete.setFixedSize(32, 32)
        btn_delete.setIconSize(QSize(16, 16))
        # 图标：优先使用垃圾桶，若不可用则降级为关闭图标
        icon = self.style().standardIcon(getattr(QStyle.StandardPixmap, "SP_TrashIcon", QStyle.StandardPixmap.SP_DialogCloseButton))
        btn_delete.setIcon(icon)
        # 确保图标在深色模式下可见：用 danger 色着色
        row_colors = get_colors(self._dark)
        danger_color = row_colors["danger"]
        pal = btn_delete.palette()
        pal.setColor(QPalette.ButtonText, QColor(danger_color))
        pal.setColor(QPalette.Text, QColor(danger_color))
        btn_delete.setPalette(pal)
        btn_delete.setToolTip("删除步骤" if can_edit else "删除步骤（需要先开启编辑）")
        btn_delete.setAccessibleName("删除步骤")
        btn_delete.setEnabled(can_edit)
        # 使用工厂函数避免闭包变量捕获问题
        def _make_delete_handler(r, sid):
            return lambda _: self._delete_step_with_select(r, sid)
        btn_delete.clicked.connect(_make_delete_handler(row, step.id))
        action_layout.addWidget(btn_delete)

        self.table.setCellWidget(row, 6, action_widget)

    def clear(self):
        """清空表格"""
        self._workflow_id = None
        self.table.setRowCount(0)
        self.hint_label.setVisible(False)
        self.hint_label.setText("")
        self._stages = []
        self._stage_uid_to_index = {}
        self._row_meta = []
        self._stage_collapsed = {}
        self._stage_header_rows = {}
        self._row_by_step_id = {}  # R4-#5
        self._step_batch_map = {}
        self._batch_deps_map = {}

    def _notify_status(self, message: str):
        """在主窗口状态栏显示提示（失败时静默降级）"""
        try:
            win = self.window()
            if win and hasattr(win, "statusBar"):
                sb = win.statusBar()
                if sb:
                    sb.showMessage(message, 5000)
        except Exception:
            # 不影响主流程
            return

    def set_single_script_mode(self, enabled: bool):
        """设置单脚本模式"""
        self._single_script_mode = enabled
        self._apply_enabled_state()

    def select_step(self, step_id: int):
        """根据 step_id 选中对应行

        R5-#6: 使用 _row_by_step_id O(1) 反查，与 update_step_status 一致。
        """
        if not step_id:
            return
        try:
            row = self._row_by_step_id.get(int(step_id))
        except (TypeError, ValueError):
            return
        if row is not None and 0 <= row < self.table.rowCount():
            self.table.setCurrentCell(row, 0)

    def update_step_status(self, step_id: int, status: str):
        """实时更新步骤状态背景色

        R4-#5: O(1) 行定位（_row_by_step_id），不再扫整张表
        """
        token = get_status_tokens(self._dark).get(status)
        if not token:
            return
        bg = QColor(token["bg"])
        try:
            row = self._row_by_step_id.get(int(step_id))
        except (TypeError, ValueError):
            return
        if row is None or row < 0 or row >= self.table.rowCount():
            return
        for col in range(self.table.columnCount()):
            cell = self.table.item(row, col)
            if cell:
                cell.setBackground(bg)

    def reset_all_status(self):
        """重置所有步骤的状态背景色（恢复默认透明，由分组卡片负责背景）"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole):
                step_id = item.data(Qt.UserRole)
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(QBrush())

    def highlight_step(self, step_id: int, status: str):
        """高亮步骤（兼容旧接口）"""
        self.update_step_status(step_id, status)

    def _add_step(self):
        """添加步骤"""
        if not self._workflow_id:
            return

        target_stage_uid = ""
        if self._selected_step_id:
            for meta in self._row_meta:
                if meta.get("kind") == "step" and meta.get("step_id") == self._selected_step_id:
                    target_stage_uid = meta.get("stage_uid", "")
                    break

        if not target_stage_uid and self._stages:
            target_stage_uid = self._stages[0]["uid"]

        steps = get_steps_by_workflow(self._workflow_id)
        max_order = max((s.order for s in steps), default=-1)

        try:
            step = create_step(
                workflow_id=self._workflow_id,
                name=f"新步骤 {len(steps) + 1}",
                step_type="python",
                order=max_order + 1,
                stage_uid=target_stage_uid,
            )
        except Exception as e:
            msg_critical(self, self._dark, "添加步骤失败", str(e))
            return

        if not step:
            msg_warning(self, self._dark, "添加步骤失败", "创建步骤返回空值，请检查数据库。")
            return

        self.load_steps(self._workflow_id)
        self.steps_changed.emit()

    def _delete_step(self, step_id: int):
        """删除步骤"""
        reply = msg_question(self, self._dark, "确认删除", "确定要删除这个步骤吗？")
        if reply == QMessageBox.Yes:
            delete_step(step_id)
            self.load_steps(self._workflow_id)
            self.steps_changed.emit()

    def _copy_step(self, step_id: int):
        """复制步骤"""
        if not self._workflow_id:
            return
        new_step = copy_step(step_id)
        if not new_step:
            msg_warning(self, self._dark, "复制失败", "未找到要复制的步骤。")
            return
        self.load_steps(self._workflow_id)
        # 选中新步骤
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == new_step.id:
                self.table.setCurrentCell(row, 0)
                break
        self.steps_changed.emit()

    def _move_row(self, row1: int, row2: int):
        """移动步骤（行内按钮）"""
        if row1 < 0 or row2 < 0 or row2 >= self.table.rowCount():
            return
        self._swap_steps(row1, row2)

    def _swap_steps(self, row1: int, row2: int):
        """交换两个步骤的顺序"""
        item1 = self.table.item(row1, 0)
        item2 = self.table.item(row2, 0)

        if not item1 or not item2:
            return

        step_id1 = item1.data(Qt.UserRole)
        step_id2 = item2.data(Qt.UserRole)

        # 交换顺序
        reorder_steps(self._workflow_id, {
            step_id1: row2,
            step_id2: row1
        })

        self.load_steps(self._workflow_id)
        self.table.setCurrentCell(row2, 0)
        self.steps_changed.emit()

    def _on_gate_changed(self, step_id: int, state: int):
        """前置开关变化"""
        is_gate = state == Qt.Checked
        if is_gate:
            update_step(step_id, is_gate=True)
        else:
            update_step(step_id, is_gate=False)
        self.steps_changed.emit()

    def _on_depends_prev_changed(self, step_id: int, prev_step, state: int):
        """依赖上一步（快捷）"""
        if not prev_step:
            return
        from database import get_session
        from models import Step
        with get_session() as session:
            step = session.query(Step).filter(Step.id == step_id).first()
            current = step.get_depends_on() if step else []
        if state == Qt.Checked:
            new_deps = list(dict.fromkeys([*current, prev_step.uid]))
        else:
            new_deps = [d for d in current if d != prev_step.uid]
        update_step(step_id, depends_on=json.dumps(new_deps, ensure_ascii=False) if new_deps else None)
        self.steps_changed.emit()

    def _on_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int):
        """选择变化"""
        if row < 0:
            self._selected_step_id = None
            return

        item = self.table.item(row, 0)
        if item:
            step_id = item.data(Qt.UserRole)
            if step_id:
                self._selected_step_id = step_id
                self.step_selected.emit(step_id)
            else:
                self._selected_step_id = None

    def _on_selection_changed_by_selection(self):
        """兜底：当点击 cellWidget 导致 currentCellChanged 不触发时，用 selectionChanged 补发 step_selected"""
        row = self.table.currentRow()
        if row < 0:
            self._selected_step_id = None
            return
        item = self.table.item(row, 0)
        if not item:
            self._selected_step_id = None
            return
        step_id = item.data(Qt.UserRole)
        if step_id:
            self._selected_step_id = step_id
            self.step_selected.emit(step_id)
        else:
            self._selected_step_id = None

    def _ensure_row_selected(self, row: int):
        if row is None or row < 0:
            return
        try:
            # 统一把交互焦点放到该行，避免"点了没反应"的错觉
            self.table.setCurrentCell(row, 0)
        except Exception:
            return

    def _delete_step_with_select(self, row: int, step_id: int):
        self._ensure_row_selected(row)
        self._delete_step(step_id)

    def _on_gate_changed_with_select(self, row: int, step_id: int, state: int):
        self._ensure_row_selected(row)
        self._on_gate_changed(step_id, state)

    def _on_depends_prev_changed_with_select(self, row: int, step_id: int, prev_step, state: int):
        self._ensure_row_selected(row)
        self._on_depends_prev_changed(step_id, prev_step, state)

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        step_item = self.table.item(row, 0)
        if not step_item:
            return
        step_id = step_item.data(Qt.UserRole)
        if not step_id:
            # 阶段标题条：请使用行内"⋯"按钮
            return

        can_edit = self._edit_enabled and (not self._single_script_mode)
        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))

        # 用途阶段：移动
        current_stage_uid = ""
        try:
            if 0 <= row < len(self._row_meta):
                current_stage_uid = self._row_meta[row].get("stage_uid") or ""
        except Exception:
            current_stage_uid = ""
        current_stage_index = int(self._stage_uid_to_index.get(current_stage_uid, 0) or 0)

        action_move_prev = menu.addAction("移动到上一阶段")
        action_move_prev.setEnabled(can_edit and current_stage_index > 0)
        if not can_edit:
            action_move_prev.setToolTip('需要先开启左侧"编辑"。')
        elif current_stage_index <= 0:
            action_move_prev.setToolTip("已在第一用途阶段。")
        if current_stage_index > 0:
            prev_stage_uid = self._stages[current_stage_index - 1]["uid"]
            action_move_prev.triggered.connect(lambda: self._move_step_to_stage(step_id, prev_stage_uid))

        move_menu = menu.addMenu("移动到指定阶段")
        move_menu.setStyleSheet(get_menu_stylesheet(self._dark))
        if not self._stages:
            move_menu.setEnabled(False)
        else:
            for st in self._stages:
                act = move_menu.addAction(st["name"])
                act.setEnabled(can_edit)
                if not can_edit:
                    act.setToolTip('需要先开启左侧"编辑"。')
                act.triggered.connect(lambda _, su=st["uid"]: self._move_step_to_stage(step_id, su))

        action_new_stage = menu.addAction("新建阶段（插入到当前阶段之后）")
        action_new_stage.setEnabled(can_edit)
        action_new_stage.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_new_stage.triggered.connect(lambda: self._insert_stage_after(current_stage_uid))

        menu.addSeparator()

        # 复制 / 删除
        action_copy = menu.addAction("复制步骤")
        action_copy.setEnabled(can_edit)
        action_copy.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_copy.triggered.connect(lambda: self._copy_step(step_id))

        action_delete = menu.addAction("删除步骤")
        action_delete.setEnabled(can_edit)
        action_delete.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_delete.triggered.connect(lambda: self._delete_step(step_id))

        menu.exec_(self.table.mapToGlobal(pos))

    def _show_stage_menu(self, stage_uid: str, global_pos):
        """阶段标题条的"⋯"菜单"""
        if not self._workflow_id or self._single_script_mode:
            return
        can_edit = self._edit_enabled

        stage = next((s for s in self._stages if s["uid"] == stage_uid), None)
        if not stage:
            return

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))
        menu.addSection(f"阶段：{stage['name']}")

        action_rename = menu.addAction("重命名阶段")
        action_rename.setEnabled(can_edit)
        action_rename.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')

        def _do_rename():
            text, ok = input_get_text(self, self._dark, "重命名阶段", "阶段名称：", text=stage["name"])
            if ok:
                update_stage(stage_uid, name=text.strip() or stage["name"])
                self.load_steps(self._workflow_id)
                self.steps_changed.emit()

        action_rename.triggered.connect(_do_rename)

        action_insert = menu.addAction("在此后插入新阶段")
        action_insert.setEnabled(can_edit)
        action_insert.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_insert.triggered.connect(lambda: self._insert_stage_after(stage_uid))

        action_insert_before = menu.addAction("在此前插入新阶段")
        action_insert_before.setEnabled(can_edit)
        action_insert_before.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_insert_before.triggered.connect(lambda: self._insert_stage_before(stage_uid))

        menu.addSeparator()
        action_up = menu.addAction("上移阶段")
        action_down = menu.addAction("下移阶段")
        stage_idx = next((i for i, s in enumerate(self._stages) if s["uid"] == stage_uid), 0)
        action_up.setEnabled(can_edit and stage_idx > 0)
        action_down.setEnabled(can_edit and stage_idx < len(self._stages) - 1)
        action_up.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_down.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
        action_up.triggered.connect(lambda: self._move_stage_order(stage_uid, -1))
        action_down.triggered.connect(lambda: self._move_stage_order(stage_uid, +1))

        action_delete = menu.addAction("删除阶段（仅允许空阶段）")
        action_delete.setEnabled(can_edit)
        action_delete.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')

        def _do_delete():
            if not can_edit:
                return
            steps = get_steps_by_workflow(self._workflow_id)
            used = [s for s in steps if getattr(s, "stage_uid", None) == stage_uid]
            if used:
                # 迁移向导：把该阶段的所有步骤移动到目标阶段后删除
                other_stages = [s for s in self._stages if s.get("uid") != stage_uid]
                if not other_stages:
                    msg_information(self, self._dark, "无法删除", "至少需要保留一个用途阶段。")
                    return
                names = [s.get("name", "阶段") for s in other_stages]
                default_idx = 0
                # 默认迁移到上一阶段（如果存在）
                cur_idx = next((i for i, s in enumerate(self._stages) if s.get("uid") == stage_uid), 0)
                if cur_idx > 0:
                    prev_uid = self._stages[cur_idx - 1].get("uid")
                    default_idx = next((i for i, s in enumerate(other_stages) if s.get("uid") == prev_uid), 0)
                choice, ok = input_get_item(
                    self, self._dark,
                    "删除阶段",
                    "该阶段下仍有步骤。\n请选择迁移目标阶段（会把该阶段所有步骤移动过去，然后删除该阶段）：",
                    names,
                    current=default_idx,
                    editable=False,
                )
                if not ok:
                    return
                target = next((s for s in other_stages if s.get("name") == choice), None)
                if not target:
                    return
                target_uid = target.get("uid")
                if not self._migrate_stage_steps(stage_uid, target_uid):
                    return
            if not delete_stage(stage_uid):
                msg_information(self, self._dark, "无法删除", "该阶段不可删除（可能是默认阶段或删除失败）。")
                return
            self.load_steps(self._workflow_id)
            self.steps_changed.emit()
            self._notify_status("已删除阶段。")

        action_delete.triggered.connect(_do_delete)

        menu.exec_(global_pos)

    def _migrate_stage_steps(self, from_stage_uid: str, to_stage_uid: str) -> bool:
        """把某用途阶段的所有步骤迁移到目标阶段（带预校验与回滚）"""
        if not self._workflow_id or self._single_script_mode:
            return False
        if from_stage_uid == to_stage_uid:
            return True

        steps = get_steps_by_workflow(self._workflow_id)
        stage_map = get_stage_order_map(self._workflow_id)
        steps_sorted = sorted(
            steps,
            key=lambda s: (int(stage_map.get(getattr(s, "stage_uid", None), 0) or 0), s.order),
        )
        moving = [s for s in steps_sorted if getattr(s, "stage_uid", None) == from_stage_uid]
        if not moving:
            return True

        keep_ids = [s.id for s in steps_sorted if getattr(s, "stage_uid", None) != from_stage_uid]
        moving_ids = [s.id for s in moving]

        # 插入到目标阶段末尾
        insert_at = 0
        for i, s in enumerate(steps_sorted):
            if getattr(s, "stage_uid", None) == to_stage_uid:
                # 注意：steps_sorted 含 moving，故先基于 keep_ids 计算插入点
                try:
                    sid = s.id
                    if sid in keep_ids:
                        insert_at = keep_ids.index(sid) + 1
                except Exception:
                    pass
        insert_at = max(0, min(insert_at, len(keep_ids)))
        new_order = keep_ids[:insert_at] + moving_ids + keep_ids[insert_at:]

        # 多步 stage_uid 覆盖
        overrides = {sid: to_stage_uid for sid in moving_ids}

        ok = self._apply_orders_and_stage_updates(overrides, new_order)
        if ok:
            self.load_steps(self._workflow_id)
            self.steps_changed.emit()
            self._notify_status("已迁移阶段内步骤。")
        return ok

    def _apply_orders_and_stage_updates(self, stage_overrides: dict[int, str], step_ids_in_order: list[int]) -> bool:
        """通用写库：全量 order + 多步 stage_uid 覆盖（带预校验与回滚）"""
        from models import Workflow as WorkflowModel, WorkflowStage as StageModel, Step as StepModel
        from engine import WorkflowEngine
        from exceptions import DependencyError, WorkflowError

        if not self._workflow_id:
            return False

        try:
            with get_session() as session:
                wf = session.query(WorkflowModel).filter(WorkflowModel.id == self._workflow_id).first()
                if not wf:
                    raise WorkflowError("工作流不存在")

                steps = session.query(StepModel).filter(StepModel.workflow_id == self._workflow_id).all()
                steps_by_id = {s.id: s for s in steps}

                for idx, sid in enumerate(step_ids_in_order):
                    st = steps_by_id.get(sid)
                    if st:
                        st.order = idx
                for sid, suid in (stage_overrides or {}).items():
                    st = steps_by_id.get(sid)
                    if st:
                        st.stage_uid = suid

                session.flush()

                stages = (
                    session.query(StageModel)
                    .filter(StageModel.workflow_id == self._workflow_id)
                    .order_by(StageModel.order.asc())
                    .all()
                )
                stage_map = {s.uid: int(s.order or 0) for s in stages}
                WorkflowEngine.compute_batches(wf, steps, stage_map)

                session.commit()
                return True
        except DependencyError as e:
            msg_warning(self, self._dark, "操作无效", f"{e}\n\n建议：检查依赖是否指向未来阶段；或调整用途阶段顺序/归类后再试。")
            return False
        except WorkflowError as e:
            msg_warning(self, self._dark, "保存失败", str(e))
            return False
        except Exception as e:
            msg_critical(self, self._dark, "保存失败", f"保存阶段/顺序时发生未知错误：{e}")
            return False

    def _move_stage_order(self, stage_uid: str, delta: int):
        """调整用途阶段顺序（带预校验与回滚）"""
        if not self._workflow_id or self._single_script_mode:
            return
        if not self._edit_enabled:
            self._notify_status('需要先开启左侧"编辑"开关。')
            return
        if delta not in (-1, 1):
            return

        from models import Workflow as WorkflowModel, WorkflowStage as StageModel, Step as StepModel
        from engine import WorkflowEngine
        from exceptions import DependencyError, WorkflowError

        try:
            with get_session() as session:
                wf = session.query(WorkflowModel).filter(WorkflowModel.id == self._workflow_id).first()
                if not wf:
                    raise WorkflowError("工作流不存在")

                stage = session.query(StageModel).filter(StageModel.uid == stage_uid).first()
                if not stage:
                    return

                stages = (
                    session.query(StageModel)
                    .filter(StageModel.workflow_id == self._workflow_id)
                    .order_by(StageModel.order.asc(), StageModel.created_at.asc())
                    .all()
                )
                idx = next((i for i, s in enumerate(stages) if s.uid == stage_uid), None)
                if idx is None:
                    return
                target_idx = idx + delta
                if target_idx < 0 or target_idx >= len(stages):
                    return
                other = stages[target_idx]

                stage.order, other.order = int(other.order or 0), int(stage.order or 0)
                session.flush()

                steps = session.query(StepModel).filter(StepModel.workflow_id == self._workflow_id).all()
                stage_map = {s.uid: int(s.order or 0) for s in stages}
                WorkflowEngine.compute_batches(wf, steps, stage_map)

                session.commit()
            self.load_steps(self._workflow_id)
            self.steps_changed.emit()
            self._notify_status("已调整用途阶段顺序。")
        except DependencyError as e:
            msg_warning(
                self, self._dark,
                "无法调整阶段顺序",
                f'{e}\n\n说明：调整用途阶段顺序会影响"禁止依赖未来阶段"的校验。\n建议：先调整步骤依赖或步骤归类后再试。',
            )
        except WorkflowError as e:
            msg_warning(self, self._dark, "保存失败", str(e))
        except Exception as e:
            msg_critical(self, self._dark, "保存失败", f"调整阶段顺序时发生未知错误：{e}")

    def _insert_stage_before(self, stage_uid: str):
        """在指定阶段之前插入一个新阶段"""
        if not self._workflow_id or self._single_script_mode:
            return
        if not self._edit_enabled:
            self._notify_status('需要先开启左侧"编辑"开关。')
            return
        stage = next((s for s in self._stages if s["uid"] == stage_uid), None)
        base_order = int(stage.get("order", 0) if stage else 0)
        new_stage = create_stage(self._workflow_id, name="新阶段", order=base_order)
        self.load_steps(self._workflow_id)
        self.steps_changed.emit()
        self._notify_status(f"已新增阶段：{new_stage.name}")

    def _insert_stage_after(self, stage_uid: str):
        """在指定阶段后插入一个新阶段（安全模式：不自动改步骤依赖）"""
        if not self._workflow_id or self._single_script_mode:
            return
        if not self._edit_enabled:
            self._notify_status('需要先开启左侧"编辑"开关。')
            return
        stage = next((s for s in self._stages if s["uid"] == stage_uid), None)
        base_order = int(stage.get("order", 0) if stage else 0)
        new_stage = create_stage(self._workflow_id, name="新阶段", order=base_order + 1)
        self.load_steps(self._workflow_id)
        self.steps_changed.emit()
        self._notify_status(f"已新增阶段：{new_stage.name}")

    def _get_step_ids_in_visual_order(self) -> list[int]:
        return [m["step_id"] for m in self._row_meta if m.get("kind") == "step" and m.get("step_id")]

    def get_stage_uid_for_step(self, step_id: int):
        """R3-#10: 从已缓存的 _row_meta 中读 stage_uid，避免再走一次 DB 查询。"""
        try:
            sid = int(step_id)
        except (TypeError, ValueError):
            return None
        for m in self._row_meta:
            if m.get("kind") == "step" and m.get("step_id") == sid:
                return m.get("stage_uid")
        return None

    def _apply_orders_and_stage_update(
        self,
        moved_step_id: int,
        target_stage_uid: str,
        step_ids_in_order: list[int],
    ) -> bool:
        """拖拽落库：更新 moved 的 stage_uid + 全量 order（带预校验与回滚）"""
        return self._apply_orders_and_stage_updates({int(moved_step_id): target_stage_uid}, step_ids_in_order)

    def _move_step_to_stage(self, step_id: int, target_stage_uid: str):
        """将步骤移动到指定用途阶段（默认放到该阶段末尾）"""
        if not self._workflow_id or self._single_script_mode:
            return
        if not self._edit_enabled:
            self._notify_status('需要先开启左侧"编辑"开关。')
            return

        # 当前展示顺序
        steps = get_steps_by_workflow(self._workflow_id)
        stage_map = get_stage_order_map(self._workflow_id)
        steps_sorted = sorted(steps, key=lambda s: (int(stage_map.get(getattr(s, "stage_uid", None), 0) or 0), s.order))
        step_ids = [s.id for s in steps_sorted]
        if step_id not in step_ids:
            return
        step_ids.remove(step_id)

        # 插入到目标阶段末尾
        insert_at = 0
        for i, s in enumerate(steps_sorted):
            if getattr(s, "stage_uid", None) == target_stage_uid:
                insert_at = i + 1
        insert_at = max(0, min(insert_at, len(step_ids)))
        step_ids.insert(insert_at, step_id)

        ok = self._apply_orders_and_stage_update(step_id, target_stage_uid, step_ids)
        self.load_steps(self._workflow_id)
        if ok:
            self.steps_changed.emit()
            self.select_step(step_id)
            self._notify_status("已移动到目标阶段。")

    def _on_rows_dragged(self, from_row: int, to_row: int):
        """自定义拖拽：默认只改"用途阶段归类+顺序"，不改依赖"""
        if not self._workflow_id:
            return
        if not self._edit_enabled or self._single_script_mode:
            self._notify_status('拖拽排序需要先开启左侧"编辑"开关。')
            return
        if from_row < 0 or to_row < 0 or from_row == to_row:
            return
        if from_row >= self.table.rowCount() or to_row >= self.table.rowCount():
            return

        moved_item = self.table.item(from_row, 0)
        if not moved_item:
            return
        moved_step_id = moved_item.data(Qt.UserRole)
        if not moved_step_id:
            return
        try:
            moved_step_id = int(moved_step_id)
        except (ValueError, TypeError):
            return

        target_stage_uid = ""
        try:
            if 0 <= to_row < len(self._row_meta):
                meta = self._row_meta[to_row]
                if meta.get("kind") == "stage_header":
                    target_stage_uid = meta.get("stage_uid") or ""
                elif meta.get("kind") == "step":
                    target_stage_uid = meta.get("stage_uid") or ""
        except Exception:
            target_stage_uid = ""

        if not target_stage_uid and self._stages:
            target_stage_uid = self._stages[-1]["uid"]

        step_ids = self._get_step_ids_in_visual_order()
        if moved_step_id not in step_ids:
            return

        from_idx = step_ids.index(moved_step_id)

        to_idx = len(step_ids)
        if 0 <= to_row < len(self._row_meta):
            target_meta = self._row_meta[to_row]
            if target_meta.get("kind") == "stage_header":
                last_step_in_stage = -1
                for r in range(to_row + 1, len(self._row_meta)):
                    if self._row_meta[r].get("kind") == "stage_header":
                        break
                    sid = self._row_meta[r].get("step_id")
                    if sid and sid in step_ids:
                        last_step_in_stage = step_ids.index(sid)
                if last_step_in_stage >= 0:
                    to_idx = last_step_in_stage + 1
                else:
                    prev_steps = 0
                    for r in range(0, to_row):
                        if self._row_meta[r].get("kind") == "step":
                            prev_steps += 1
                    to_idx = prev_steps
            else:
                sid = target_meta.get("step_id")
                if sid and sid in step_ids:
                    to_idx = step_ids.index(sid)

        step_ids.pop(from_idx)
        if to_idx > len(step_ids):
            to_idx = len(step_ids)
        step_ids.insert(to_idx, moved_step_id)

        try:
            step_orders = {sid: idx for idx, sid in enumerate(step_ids)}
            reorder_steps(self._workflow_id, step_orders)
            update_step(moved_step_id, stage_uid=target_stage_uid)
        except Exception as e:
            msg_critical(self, self._dark, "保存失败", f"拖拽排序时发生错误：{e}")
            return

        QTimer.singleShot(0, lambda: self._refresh_after_drag(moved_step_id))

    def _refresh_after_drag(self, moved_step_id: int):
        self.load_steps(self._workflow_id)
        self.steps_changed.emit()
        self.select_step(moved_step_id)
        self._notify_status("步骤已移动。")
