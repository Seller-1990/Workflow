# -*- coding: utf-8 -*-
"""步骤列表表格面板"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMenu, QMessageBox, QGroupBox,
    QCheckBox, QComboBox
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor

from config import StepType
from database import (
    get_steps_by_workflow, create_step, delete_step,
    update_step, reorder_steps, list_workflows
)


class StepTablePanel(QWidget):
    """步骤列表表格面板
    
    列：顺序 / 类型 / 名称 / 脚本 / 依赖 / 是否前置 / 并行 / 操作
    """
    
    # 信号
    step_selected = Signal(int)  # step_id
    steps_changed = Signal()
    
    # 列定义
    COLUMNS = [
        ("顺序", 50),
        ("类型", 90),
        ("名称", 180),
        ("脚本", 260),
        ("依赖", 70),
        ("前置", 50),
        ("并行", 50),
        ("操作", 140),
    ]
    
    # 状态颜色
    STATUS_COLORS = {
        "running": QColor(255, 193, 7),   # 黄色
        "success": QColor(76, 175, 80),   # 绿色
        "failure": QColor(244, 67, 54),   # 红色
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._single_script_mode = False
        self._edit_enabled = True
        self._parallel_available = True
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        group = QGroupBox("步骤列表")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 工具栏
        toolbar = QHBoxLayout()
        self.btn_add = QPushButton("添加步骤")
        self.btn_add.clicked.connect(self._add_step)
        toolbar.addWidget(self.btn_add)
        toolbar.addStretch()
        group_layout.addLayout(toolbar)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.currentCellChanged.connect(self._on_selection_changed)
        self.table.setAlternatingRowColors(True)
        
        # 设置列宽
        header = self.table.horizontalHeader()
        for i, (_, width) in enumerate(self.COLUMNS):
            if i == 3:  # 脚本列
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                self.table.setColumnWidth(i, width)
        self.table.verticalHeader().setDefaultSectionSize(34)
        
        group_layout.addWidget(self.table)
        
        layout.addWidget(group)

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        self.btn_add.setEnabled(can_edit)
        # 行内控件需要重绘/重建才能正确禁用
        if self._workflow_id:
            self.load_steps(self._workflow_id)
    
    def load_steps(self, workflow_id: int):
        """加载步骤列表"""
        self._workflow_id = workflow_id
        self.table.setRowCount(0)
        
        steps = get_steps_by_workflow(workflow_id)
        workflow_map = {wf.uid: wf.name for wf in list_workflows()}
        if self._single_script_mode:
            steps = [s for s in steps if s.uid == "single_script"]
        self.table.setRowCount(len(steps))
        
        for row, step in enumerate(steps):
            prev_step = steps[row - 1] if row > 0 else None
            self._set_row_data(row, step, prev_step, workflow_map)

        self.btn_add.setEnabled(self._edit_enabled and (not self._single_script_mode))
        self._update_table_height()

    def _update_table_height(self):
        # 让“步骤列表”在中区滚动时尽量展示完整步骤行，避免只看到 1 行
        rows = self.table.rowCount()
        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height()
        padding = 18
        min_rows = 3
        visible_rows = max(min_rows, rows)
        desired = header_h + visible_rows * row_h + padding
        self.table.setMinimumHeight(desired)
    
    def _set_row_data(self, row: int, step, prev_step=None, workflow_map=None):
        """设置行数据"""
        # 顺序
        order_item = QTableWidgetItem(str(step.order + 1))
        order_item.setData(Qt.UserRole, step.id)
        order_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, order_item)
        
        # 类型
        type_item = QTableWidgetItem(StepType.display_name(step.step_type))
        self.table.setItem(row, 1, type_item)
        
        # 名称
        name_item = QTableWidgetItem(step.name)
        self.table.setItem(row, 2, name_item)
        
        # 脚本
        script_text = step.script_path or ""
        if step.step_type == "sub_workflow" and workflow_map:
            script_text = workflow_map.get(step.script_path, step.script_path or "")
        script_item = QTableWidgetItem(script_text)
        script_item.setToolTip(script_text)
        self.table.setItem(row, 3, script_item)
        
        # 依赖（快捷：依赖上一步）
        depends_widget = QWidget()
        depends_layout = QHBoxLayout(depends_widget)
        depends_layout.setContentsMargins(0, 0, 0, 0)
        depends_layout.setAlignment(Qt.AlignCenter)
        depends_check = QCheckBox("上一")
        depends_check.setEnabled(prev_step is not None)
        depends_check.setToolTip("勾选后：本步骤需要等待上一步骤执行成功后才会执行。")
        deps = step.get_depends_on()
        if prev_step and prev_step.uid in deps:
            depends_check.setChecked(True)
        depends_check.setEnabled(self._edit_enabled and (prev_step is not None) and (not self._single_script_mode))
        depends_check.stateChanged.connect(
            lambda state, s=step, p=prev_step: self._on_depends_prev_changed(s.id, p, state)
        )
        depends_layout.addWidget(depends_check)
        self.table.setCellWidget(row, 4, depends_widget)

        # 前置（开关）
        gate_widget = QWidget()
        gate_layout = QHBoxLayout(gate_widget)
        gate_layout.setContentsMargins(0, 0, 0, 0)
        gate_layout.setAlignment(Qt.AlignCenter)
        gate_check = QCheckBox()
        gate_check.setChecked(step.is_gate)
        gate_check.setToolTip("前置步骤：启用后会阻塞后续并行步骤（确保关键步骤先完成）。")
        gate_check.setEnabled(self._edit_enabled and (not self._single_script_mode))
        gate_check.stateChanged.connect(
            lambda state, s=step: self._on_gate_changed(s.id, state)
        )
        gate_layout.addWidget(gate_check)
        self.table.setCellWidget(row, 5, gate_widget)
        
        # 并行（开关）
        parallel_widget = QWidget()
        parallel_layout = QHBoxLayout(parallel_widget)
        parallel_layout.setContentsMargins(0, 0, 0, 0)
        parallel_layout.setAlignment(Qt.AlignCenter)
        parallel_check = QCheckBox()
        parallel_check.setChecked(step.is_parallel)
        parallel_check.setToolTip("并行：仅在基础配置启用并行后生效；且前置步骤不能并行。")
        parallel_check.setEnabled(
            self._edit_enabled
            and (not self._single_script_mode)
            and self._parallel_available
            and (not step.is_gate)
        )
        parallel_check.stateChanged.connect(
            lambda state, s=step: self._on_parallel_changed(s.id, state)
        )
        parallel_layout.addWidget(parallel_check)
        self.table.setCellWidget(row, 6, parallel_widget)
        
        # 操作
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(2, 0, 2, 0)
        action_layout.setSpacing(4)

        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(30)
        btn_up.setEnabled(self._edit_enabled and (not self._single_script_mode))
        btn_up.clicked.connect(lambda _, r=row: self._move_row(r, r - 1))
        action_layout.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setFixedWidth(30)
        btn_down.setEnabled(self._edit_enabled and (not self._single_script_mode))
        btn_down.clicked.connect(lambda _, r=row: self._move_row(r, r + 1))
        action_layout.addWidget(btn_down)
        
        btn_delete = QPushButton("删除")
        btn_delete.setFixedWidth(45)
        btn_delete.setEnabled(self._edit_enabled and (not self._single_script_mode))
        btn_delete.clicked.connect(lambda _, s=step: self._delete_step(s.id))
        action_layout.addWidget(btn_delete)
        
        self.table.setCellWidget(row, 7, action_widget)
    
    def clear(self):
        """清空表格"""
        self._workflow_id = None
        self.table.setRowCount(0)

    def set_single_script_mode(self, enabled: bool):
        """设置单脚本模式"""
        self._single_script_mode = enabled
        self._apply_enabled_state()
    
    def highlight_step(self, step_id: int, status: str):
        """高亮步骤"""
        color = self.STATUS_COLORS.get(status)
        if not color:
            return
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == step_id:
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(color)
                break
    
    def _add_step(self):
        """添加步骤"""
        if not self._workflow_id:
            return
        
        # 获取当前最大顺序
        row_count = self.table.rowCount()
        
        step = create_step(
            workflow_id=self._workflow_id,
            name=f"新步骤 {row_count + 1}",
            step_type="python",
            order=row_count
        )
        
        self.load_steps(self._workflow_id)
        self.steps_changed.emit()
    
    def _delete_step(self, step_id: int):
        """删除步骤"""
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除这个步骤吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            delete_step(step_id)
            self.load_steps(self._workflow_id)
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
        # 前置步骤不能并行：启用前置时强制关闭并行标记
        if is_gate:
            update_step(step_id, is_gate=True, is_parallel=False)
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
    
    def _on_parallel_changed(self, step_id: int, state: int):
        """并行开关变化"""
        if not self._parallel_available:
            return
        update_step(step_id, is_parallel=(state == Qt.Checked))
        self.steps_changed.emit()
    
    def _on_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int):
        """选择变化"""
        if row < 0:
            return
        
        item = self.table.item(row, 0)
        if item:
            step_id = item.data(Qt.UserRole)
            self.step_selected.emit(step_id)
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.table.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        
        action_delete = menu.addAction("删除步骤")
        action_delete.setEnabled(self._edit_enabled and (not self._single_script_mode))
        row = self.table.row(item)
        step_item = self.table.item(row, 0)
        if step_item:
            step_id = step_item.data(Qt.UserRole)
            action_delete.triggered.connect(lambda: self._delete_step(step_id))
        
        menu.exec_(self.table.mapToGlobal(pos))
