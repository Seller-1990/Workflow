# -*- coding: utf-8 -*-
"""步骤列表面板（StepTablePanel）

UI 构建与渲染实现在 ui.step_table.panel_build；
步骤/阶段操作与事件处理实现在 ui.step_table.panel_actions（均为纯移动提取）。
"""

import re
import traceback

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout,
    QMessageBox,
    QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QSettings, QTimer
from PySide6.QtGui import QColor, QBrush

from config import APP_NAME
from database import (
    get_steps_by_workflow,
    get_workflow_uid_name_map,
    list_stages,
    get_stage_order_map,
    get_workflow_by_id,
    get_session,
)
from exceptions import DependencyError
from ui.step_table import panel_actions, panel_build
from ui.step_table.view_model import (
    build_prev_by_id,
    build_row_meta,
    build_stage_records,
    build_stage_render_context,
    build_single_script_uid_display_map,
    ensure_default_stage_records,
    sort_steps_by_stage,
)
from ui.theme import (
    get_status_tokens,
    msg_warning,
)
from ui.step_table.reorderable_table import STAGE_COLORS


class StepTablePanel(QWidget):
    """步骤列表表格面板

    列：顺序 / 类型 / 名称 / 脚本 / 上游依赖 / 检查点 / 操作
    """

    # 信号
    step_selected = Signal(int)  # step_id
    step_deleted = Signal(int)  # step_id
    steps_changed = Signal()

    # 列定义
    COLUMNS = [
        ("顺序", 56),
        ("类型", 76),
        ("名称", 136),
        ("脚本", 220),
        ("上游依赖", 104),
        ("检查点", 78),
        ("操作", 84),
    ]
    COLUMN_MIN_WIDTHS = [56, 72, 120, 160, 96, 78, 82]
    FIXED_VISIBLE_COLUMNS = {
        0: 56,
        1: 76,
        4: 104,
        5: 78,
        6: 84,
    }
    NAME_MIN_WIDTH = 132
    SCRIPT_MIN_WIDTH = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._workflow_id = None
        self._single_script_mode = False
        self._edit_enabled = True
        self._parallel_available = True
        self._selected_step_id = None
        self._selected_stage_uid = None
        self._last_emitted_selection = None

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
        """设置 UI（实现在 ui.step_table.panel_build）"""
        panel_build.setup_ui(self)

    def refresh_theme(self, dark: bool):
        """刷新主题（实现在 ui.step_table.panel_build）"""
        panel_build.refresh_theme(self, dark)

    def _default_column_widths(self) -> list[int]:
        return panel_build.default_column_widths(self)

    def _sanitize_column_widths(self, widths: list[int]) -> list[int]:
        return panel_build.sanitize_column_widths(self, widths)

    def _load_column_widths(self) -> list[int] | None:
        return panel_build.load_column_widths(self)

    def _apply_column_widths(self):
        panel_build.apply_column_widths(self)

    def _fit_columns_to_viewport(self):
        """让关键列默认可见（实现在 ui.step_table.panel_build）"""
        panel_build.fit_columns_to_viewport(self)

    def _save_column_widths(self):
        panel_build.save_column_widths(self)

    def _on_header_section_resized(self, _logical: int, _old: int, _new: int):
        if self._suspend_width_save:
            return
        # debounce：避免拖拽时频繁写入 settings
        self._width_save_timer.start(200)

    def _reset_column_widths(self):
        panel_build.reset_column_widths(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_columns_to_viewport)

    def _show_header_menu(self, pos):
        panel_build.show_header_menu(self, pos)

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        """编辑/单脚本模式联动（实现在 ui.step_table.panel_build）"""
        panel_build.apply_enabled_state(self)

    def load_steps(self, workflow_id: int):
        """加载步骤列表（按执行阶段分组展示；批次(Bx)由 compute_batches 自动计算）"""
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

        # 执行阶段（固定顺序屏障）：始终展示阶段标题条（即使为空）
        self._stages = []
        self._stage_uid_to_index = {}
        if not self._single_script_mode:
            try:
                self._stages, self._stage_uid_to_index = build_stage_records(list_stages(workflow_id))
            except Exception:
                self._stages, self._stage_uid_to_index = [], {}

        stage_uids = {st["uid"] for st in self._stages}
        if self._single_script_mode:
            self._selected_stage_uid = None
        elif self._selected_stage_uid not in stage_uids:
            self._selected_stage_uid = None

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

        steps_sorted = sort_steps_by_stage(steps, stage_map)
        prev_by_id = build_prev_by_id(steps_sorted)

        # 构建视觉行模型（阶段标题条 + 该阶段步骤）
        if self._single_script_mode:
            self._row_meta = build_row_meta(steps_sorted, self._stages, single_script_mode=True)
        else:
            # 确保至少一个阶段（防御：极端情况下 list_stages 失败）
            self._stages, self._stage_uid_to_index = ensure_default_stage_records(self._stages)
            self._row_meta = build_row_meta(steps_sorted, self._stages, single_script_mode=False)

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
            self._uid_display_map = build_single_script_uid_display_map(steps_sorted)
            for row, meta in enumerate(self._row_meta):
                step = step_by_id.get(meta["step_id"])
                if not step:
                    continue
                prev_step = prev_by_id.get(step.id)
                self._set_row_data(row, step, prev_step, workflow_map, stage_idx=0)
        else:
            render_context = build_stage_render_context(steps_sorted, self._stages)
            stage_uid_to_steps = render_context["stage_uid_to_steps"]
            stage_display_index = render_context["stage_display_index"]
            stage_name_by_uid = render_context["stage_name_by_uid"]
            within_idx_by_step = render_context["within_idx_by_step"]
            self._uid_display_map = render_context["uid_display_map"]

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
        self._update_stage_context_ui()
        QTimer.singleShot(0, self._fit_columns_to_viewport)

    def _update_group_ranges(self):
        """同步阶段行范围给表格（实现在 ui.step_table.panel_build）"""
        panel_build.update_group_ranges(self)

    def _update_table_height(self):
        panel_build.update_table_height(self)

    def _stage_label_for_uid(self, stage_uid: str | None) -> str:
        return panel_build.stage_label_for_uid(self, stage_uid)

    def _set_stage_context(self, stage_uid: str | None):
        if self._single_script_mode:
            stage_uid = None
        if self._selected_stage_uid == stage_uid:
            self._update_stage_context_ui()
            return
        self._selected_stage_uid = stage_uid
        self._update_stage_context_ui()
        self._refresh_stage_headers()

    def _update_stage_context_ui(self):
        panel_build.update_stage_context_ui(self)

    def _refresh_stage_headers(self):
        panel_build.refresh_stage_headers(self)

    def _render_stage_header_row(
        self,
        row: int,
        stage_uid: str,
        stage_idx: int,
        stage_name: str,
        step_count: int,
    ):
        """渲染用途阶段标题条（实现在 ui.step_table.panel_build）"""
        panel_build.render_stage_header_row(self, row, stage_uid, stage_idx, stage_name, step_count)

    def _on_cell_pressed(self, row: int, col: int):
        if row < 0 or row >= len(self._row_meta):
            return
        meta = self._row_meta[row]
        if meta.get("kind") == "stage_header":
            self._set_stage_context(meta.get("stage_uid"))

    def _toggle_stage_collapse(self, stage_uid: str):
        """折叠/展开阶段（实现在 ui.step_table.panel_actions）"""
        panel_actions.toggle_stage_collapse(self, stage_uid)

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
        """设置行数据（实现在 ui.step_table.panel_build）"""
        panel_build.set_row_data(
            self, row, step, prev_step, workflow_map, stage_idx, within_idx, batch_idx
        )

    def clear(self):
        """清空表格"""
        self._workflow_id = None
        self._selected_step_id = None
        self._selected_stage_uid = None
        self._last_emitted_selection = None
        self.table.setRowCount(0)
        self.hint_label.setVisible(False)
        self.hint_label.setText("")
        self.stage_context_label.setText("")
        self._stages = []
        self._stage_uid_to_index = {}
        self._row_meta = []
        self._stage_collapsed = {}
        self._stage_header_rows = {}
        self._row_by_step_id = {}  # R4-#5
        self._step_batch_map = {}
        self._batch_deps_map = {}
        self._update_stage_context_ui()

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

    def set_selected_stage_context(self, stage_uid: str | None, *, clear_step_selection: bool = False):
        """同步当前阶段上下文，供外部视图切换后复用「添加步骤」目标阶段。"""
        self._set_stage_context(stage_uid)
        if not clear_step_selection:
            return
        self._selected_step_id = None
        self._last_emitted_selection = None
        table = getattr(self, "table", None)
        if table is None:
            return
        blocked = table.signalsBlocked()
        table.blockSignals(True)
        try:
            if hasattr(table, "clearSelection"):
                table.clearSelection()
            selection_model = table.selectionModel() if hasattr(table, "selectionModel") else None
            if selection_model is not None and hasattr(selection_model, "clearCurrentIndex"):
                selection_model.clearCurrentIndex()
            elif hasattr(table, "setCurrentCell"):
                table.setCurrentCell(-1, -1)
        finally:
            table.blockSignals(blocked)

    def get_selection_snapshot(self) -> dict[str, int | str | None]:
        """返回当前公开可见的选中快照，避免外部直接读取私有字段。"""
        return {
            "step_id": self._selected_step_id,
            "stage_uid": self._selected_stage_uid,
        }

    def has_step(self, step_id: int) -> bool:
        """判断当前表格缓存中是否包含指定步骤。"""
        try:
            return int(step_id) in self._row_by_step_id
        except (TypeError, ValueError):
            return False

    def select_step(self, step_id: int, emit_signal: bool = True):
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
            meta = self._row_meta[row] if row < len(self._row_meta) else {}
            if meta.get("kind") == "step":
                stage_uid = meta.get("stage_uid")
                if self._stage_collapsed.get(stage_uid):
                    self._toggle_stage_collapse(stage_uid)
                self._set_stage_context(meta.get("stage_uid"))
            if emit_signal:
                self.table.setCurrentCell(row, 0)
                return
            blocked = self.table.signalsBlocked()
            self.table.blockSignals(True)
            try:
                self._selected_step_id = int(step_id)
                self.table.setCurrentCell(row, 0)
            finally:
                self.table.blockSignals(blocked)

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
        """添加步骤（实现在 ui.step_table.panel_actions）"""
        panel_actions.add_step(self)

    def _delete_step(self, step_id: int):
        """删除步骤（实现在 ui.step_table.panel_actions）"""
        panel_actions.delete_step(self, step_id)

    def _get_selected_step_rows(self):
        """任务9：返回所有选中步骤的行号列表（仅步骤行，排除阶段标题条）"""
        rows = []
        for item in self.table.selectedItems():
            row = item.row()
            if 0 <= row < len(self._row_meta):
                meta = self._row_meta[row]
                if meta.get("kind") == "step" and meta.get("step_id"):
                    if row not in rows:
                        rows.append(row)
        return rows

    def _batch_delete_steps(self, rows):
        """任务9：批量删除步骤"""
        if not rows:
            return
        if not self._edit_enabled:
            from ui.theme import msg_information
            msg_information(self, "提示", '请先开启"编辑"。')
            return
        step_ids = []
        for row in rows:
            if 0 <= row < len(self._row_meta):
                meta = self._row_meta[row]
                sid = meta.get("step_id")
                if sid and sid not in step_ids:
                    step_ids.append(sid)
        if not step_ids:
            return
        from ui.theme import msg_question
        answer = msg_question(
            self, "批量删除确认",
            f"确定删除选中的 {len(step_ids)} 个步骤吗？此操作不可撤销。",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            from database import delete_step as db_delete_step
            for sid in step_ids:
                db_delete_step(sid)
            self._selected_step_id = None
            self._last_emitted_selection = None
            self.step_selected.emit(0)
            self.load_steps(self._workflow_id)
        except Exception as e:
            from ui.theme import msg_critical
            msg_critical(self, "批量删除失败", str(e))

    def _batch_change_stage(self, rows, target_stage_uid):
        """任务9：批量改阶段"""
        if not rows or not target_stage_uid:
            return
        if not self._edit_enabled:
            from ui.theme import msg_information
            msg_information(self, "提示", '请先开启"编辑"。')
            return
        step_ids = []
        for row in rows:
            if 0 <= row < len(self._row_meta):
                meta = self._row_meta[row]
                sid = meta.get("step_id")
                if sid and sid not in step_ids:
                    step_ids.append(sid)
        if not step_ids:
            return
        try:
            from stage_mutation_service import move_step_to_stage as move_step_to_stage_service
            for sid in step_ids:
                move_step_to_stage_service(self._workflow_id, sid, target_stage_uid)
            self.load_steps(self._workflow_id)
        except Exception as e:
            from ui.theme import msg_critical
            msg_critical(self, "批量改阶段失败", str(e))

    def _copy_step(self, step_id: int):
        """复制步骤（实现在 ui.step_table.panel_actions）"""
        panel_actions.copy_step(self, step_id)

    def _move_row(self, row1: int, row2: int):
        """移动步骤（行内按钮）"""
        if row1 < 0 or row2 < 0 or row2 >= self.table.rowCount():
            return
        self._swap_steps(row1, row2)

    def _swap_steps(self, row1: int, row2: int):
        """交换两个步骤的顺序（实现在 ui.step_table.panel_actions）"""
        panel_actions.swap_steps(self, row1, row2)

    def _on_gate_changed(self, step_id: int, state: int):
        """检查点开关变化（实现在 ui.step_table.panel_actions）"""
        panel_actions.on_gate_changed(self, step_id, state)

    def _on_depends_prev_changed(self, step_id: int, prev_step, state: int):
        """依赖上一步（快捷）（实现在 ui.step_table.panel_actions）"""
        panel_actions.on_depends_prev_changed(self, step_id, prev_step, state)

    def _on_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int):
        """选择变化（实现在 ui.step_table.panel_actions）"""
        panel_actions.on_selection_changed(self, row, col, prev_row, prev_col)

    def _on_selection_changed_by_selection(self):
        """兜底补发 step_selected（实现在 ui.step_table.panel_actions）"""
        panel_actions.on_selection_changed_by_selection(self)

    def _emit_step_selected_once(self, step_id: int, row: int) -> None:
        selection_key = (int(step_id), int(row))
        if self._last_emitted_selection == selection_key:
            return
        self._last_emitted_selection = selection_key
        self.step_selected.emit(int(step_id))

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
        """显示右键菜单（实现在 ui.step_table.panel_actions）"""
        panel_actions.show_context_menu(self, pos)

    def _show_stage_menu(self, stage_uid: str, global_pos):
        """阶段标题条的"⋯"菜单（实现在 ui.step_table.panel_actions）"""
        panel_actions.show_stage_menu(self, stage_uid, global_pos)

    def _show_dependency_mutation_error(self, title: str, error: DependencyError, detail: str = "") -> None:
        """Show an actionable dependency error and optionally focus the offending step.

        Stage/order operations can fail because a step would depend on a future stage.
        A plain text warning leaves users hunting through the table, so expose a direct
        "定位问题步骤" action when the offending dependency uid can be resolved.
        """
        text = f"{error}\n\n{detail}" if detail else str(error)
        focus_step_id = self._find_step_id_referenced_by_dependency_error(error)
        if not focus_step_id:
            msg_warning(self, self._dark, title, text)
            return

        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.Warning)
        locate_button = msg.addButton("定位问题步骤", QMessageBox.AcceptRole)
        msg.addButton(QMessageBox.Ok)
        try:
            from ui.theme import _style_colors, _MSG_BOX_STYLE

            msg.setStyleSheet(_MSG_BOX_STYLE.format(**_style_colors(self._dark)))
        except (ImportError, KeyError, ValueError):
            pass
        msg.exec()
        if msg.clickedButton() is locate_button:
            try:
                self.select_step(focus_step_id)
            except (RuntimeError, ValueError, TypeError) as exc:
                self._notify_status(f"未能定位触发依赖校验的步骤：{exc}")
                return
            self._notify_status("已定位到触发依赖校验的步骤。")

    def _find_step_id_referenced_by_dependency_error(self, error: DependencyError) -> int | None:
        """Return the visible step id mentioned by a DependencyError, if any.

        Service-side dependency messages have appeared in several formats over time,
        for example ``uid=abc``, ``uid='abc'`` or JSON-like ``"uid": "abc"``.
        Keep the UI locator tolerant so the actionable dialog does not silently fall
        back to a generic warning when the wording changes slightly.
        """
        message = str(error)
        uid_tokens = set()
        for pattern in (
            r"\buid\s*=\s*['\"]?([^'\"\s,;，。)）]+)",
            r"['\"]uid['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        ):
            uid_tokens.update(match.group(1) for match in re.finditer(pattern, message))
        if not uid_tokens:
            return None

        steps = []
        if self._workflow_id:
            steps = get_steps_by_workflow(self._workflow_id)
        for step in steps:
            uid = getattr(step, "uid", None)
            if uid and str(uid) in uid_tokens:
                try:
                    return int(step.id)
                except (TypeError, ValueError):
                    return None
        return None

    def _run_stage_mutation(self, action, dependency_title: str, dependency_detail: str, unknown_message: str) -> bool:
        """阶段写库异常包装（实现在 ui.step_table.panel_actions）"""
        return panel_actions.run_stage_mutation(self, action, dependency_title, dependency_detail, unknown_message)

    def _migrate_stage_steps(self, from_stage_uid: str, to_stage_uid: str) -> bool:
        """把某用途阶段的所有步骤迁移到目标阶段（实现在 ui.step_table.panel_actions）"""
        return panel_actions.migrate_stage_steps(self, from_stage_uid, to_stage_uid)

    def _apply_orders_and_stage_updates(self, stage_overrides: dict[int, str], step_ids_in_order: list[int]) -> bool:
        """通用写库：全量 order + 多步 stage_uid 覆盖（实现在 ui.step_table.panel_actions）"""
        return panel_actions.apply_orders_and_stage_updates(self, stage_overrides, step_ids_in_order)

    def apply_orders_and_stage_updates(self, stage_overrides: dict[int, str], step_ids_in_order: list[int]) -> bool:
        """公开的阶段/顺序更新 facade，供外部面板复用。"""
        return self._apply_orders_and_stage_updates(stage_overrides, step_ids_in_order)

    def _move_stage_order(self, stage_uid: str, delta: int):
        """调整用途阶段顺序（实现在 ui.step_table.panel_actions）"""
        panel_actions.move_stage_order(self, stage_uid, delta)

    def _insert_stage_before(self, stage_uid: str):
        """在指定阶段之前插入一个新阶段（实现在 ui.step_table.panel_actions）"""
        panel_actions.insert_stage_before(self, stage_uid)

    def _insert_stage_after(self, stage_uid: str):
        """在指定阶段后插入一个新阶段（实现在 ui.step_table.panel_actions）"""
        panel_actions.insert_stage_after(self, stage_uid)

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
        """拖拽落库（实现在 ui.step_table.panel_actions）"""
        return panel_actions.apply_orders_and_stage_update(self, moved_step_id, target_stage_uid, step_ids_in_order)

    def _move_step_to_stage(self, step_id: int, target_stage_uid: str):
        """将步骤移动到指定用途阶段（实现在 ui.step_table.panel_actions）"""
        panel_actions.move_step_to_stage(self, step_id, target_stage_uid)

    def _on_rows_dragged(self, from_row: int, to_row: int):
        """自定义拖拽落库（实现在 ui.step_table.panel_actions）"""
        panel_actions.on_rows_dragged(self, from_row, to_row)

    def _refresh_after_drag(self, moved_step_id: int):
        panel_actions.refresh_after_drag(self, moved_step_id)
