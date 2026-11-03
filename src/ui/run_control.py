# -*- coding: utf-8 -*-
"""运行控制面板"""

import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QDialog, QFormLayout, QComboBox, QDialogButtonBox,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from ui.run_control_build import RUN_MODE_BUTTONS, setup_run_controls
from ui.theme import COLORS, get_colors


class RunControlPanel(QWidget):
    """运行控制面板
    
    五种运行模式：
    1. 全流程运行
    2. 从指定步骤开始
    3. 只运行指定步骤
    4. 从指定阶段开始
    5. 重试失败步骤
    """
    
    # 信号
    run_requested = Signal(str, object)  # mode, param
    dry_run_clicked = Signal()  # 预演模式
    run_stage_requested = Signal(str)   # stage_uid
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._selected_step_id = None
        self._selected_stage_uid = None
        self._is_running = False
        self._setup_ui()
    
    def _setup_ui(self):
        from ui.icons import set_icon_button

        setup_run_controls(
            self, ui=sys.modules[__name__], colors=COLORS, set_icon_button=set_icon_button,
        )

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.lbl_selected.setStyleSheet(f"""
            QLabel#selectedStepLabel {{
                color: {colors["text_tertiary"]};
                font-size: 11px;
                padding: 2px 0px;
            }}
        """)
        # V9.3：重建按钮图标（颜色创建时烘焙）；图标色与按钮文字色一致
        from ui.icons import set_icon_button

        set_icon_button(self.btn_run_all, "run.all", color=colors["text_inverse"])
        for attr, _text, _tip, _accessible, key, _mode in RUN_MODE_BUTTONS:
            set_icon_button(getattr(self, attr), key, color=colors["primary"])
        set_icon_button(self.btn_dry_run, "run.dry", color=colors["primary"])

    def set_running(self, running: bool):
        """设置运行状态（用于避免重复触发运行）"""
        self._is_running = bool(running)
        # 运行中禁止再次触发运行/预演，避免用户误操作产生「已有工作流正在运行」的错误日志
        can_run = not self._is_running
        self.btn_run_all.setEnabled(can_run)
        # 更新选中步骤相关按钮
        has_step = self._selected_step_id is not None
        has_stage = self._selected_stage_uid is not None
        self.btn_run_from.setEnabled(has_step and can_run)
        self.btn_run_only.setEnabled(has_step and can_run)
        self.btn_run_stage.setEnabled(has_stage and can_run)
        self.btn_run_from_stage.setEnabled(has_stage and can_run)
        self.btn_run_range.setEnabled(can_run)
        self.btn_retry.setEnabled(can_run)
        self.btn_dry_run.setEnabled(can_run)
    
    def set_selected_step(self, step_id: int, stage_uid: str = None):
        """设置选中的步骤和所属阶段"""
        self._selected_step_id = step_id
        self._selected_stage_uid = stage_uid
        if step_id is not None:
            stage_info = f" | 阶段: {stage_uid}" if stage_uid else ""
            self.lbl_selected.setText(f"已选中步骤 ID: {step_id}{stage_info}")
        else:
            self.lbl_selected.setText("未选中步骤")
        # 更新按钮状态
        has_step = step_id is not None
        has_stage = stage_uid is not None
        self.btn_run_from.setEnabled(has_step and not self._is_running)
        self.btn_run_only.setEnabled(has_step and not self._is_running)
        self.btn_run_stage.setEnabled(has_stage and not self._is_running)
        self.btn_run_from_stage.setEnabled(has_stage and not self._is_running)

    def _run(self, mode: str, param=None):
        """统一运行入口（P2 精简：收敛原 _run_all/_run_from/_run_only/_run_stage/
        _run_from_stage/_retry_failed 六个近相同按钮体）。

        mode: full / from_step / only_step / step_range / only_stage / from_stage / retry_failed
        param: 显式参数；缺省时按 mode 从当前选中步骤/阶段推导。
        step_range 的 param 为 None 时由分发层弹出区间选择对话框（见 prompt_step_range）。
        """
        if mode in ("from_step", "only_step"):
            if not self._selected_step_id:
                return
            param = self._selected_step_id
        elif mode in ("from_stage", "only_stage"):
            if not self._selected_stage_uid:
                return
            param = self._selected_stage_uid
        self.run_requested.emit(mode, param)


def compute_range_step_ids(step_ids, start_step_id, end_step_id):
    """按全局顺序返回 [起点, 终点] 区间内的步骤 ID（含两端，反向自动交换）。

    纯函数，供对话框实时显示“将运行 N 个步骤”与测试复用；
    未找到起点/终点时返回空列表。
    """
    ids = list(step_ids)
    if start_step_id not in ids or end_step_id not in ids:
        return []
    a, b = ids.index(start_step_id), ids.index(end_step_id)
    if a > b:
        a, b = b, a
    return ids[a:b + 1]


class StepRangeDialog(QDialog):
    """区间运行对话框：选择起点/终点步骤（视觉精修留给后续 UI 任务）。"""

    def __init__(self, steps, default_start_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("区间运行")
        self.setModal(True)
        self._step_ids = [step.id for step in steps]

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb_start = QComboBox()
        self.cmb_end = QComboBox()
        for idx, step in enumerate(steps, start=1):
            label = f"{idx}. {getattr(step, 'name', '') or step.id}"
            self.cmb_start.addItem(label, step.id)
            self.cmb_end.addItem(label, step.id)
        self.cmb_start.setAccessibleName("起点步骤")
        self.cmb_end.setAccessibleName("终点步骤")
        form.addRow("起点步骤", self.cmb_start)
        form.addRow("终点步骤", self.cmb_end)
        layout.addLayout(form)

        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("selectedStepLabel")
        layout.addWidget(self.lbl_count)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("开始运行")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 默认：起点 = 当前选中步骤（无则第一步），终点 = 最后一步
        start_index = self.cmb_start.findData(default_start_id) if default_start_id is not None else -1
        self.cmb_start.setCurrentIndex(start_index if start_index >= 0 else 0)
        self.cmb_end.setCurrentIndex(max(self.cmb_end.count() - 1, 0))

        self.cmb_start.currentIndexChanged.connect(self._update_count)
        self.cmb_end.currentIndexChanged.connect(self._update_count)
        self._update_count()

    def selected_range(self):
        return self.cmb_start.currentData(), self.cmb_end.currentData()

    def _update_count(self):
        start_id, end_id = self.selected_range()
        n = len(compute_range_step_ids(self._step_ids, start_id, end_id))
        hint = ""
        if self.cmb_start.currentIndex() > self.cmb_end.currentIndex():
            hint = "（起点在终点之后，将自动交换）"
        self.lbl_count.setText(f"将运行 {n} 个步骤{hint}")


def prompt_step_range(parent, steps, default_start_id=None):
    """弹出区间选择对话框；返回 (起点 ID, 终点 ID)，取消返回 None。"""
    if not steps:
        return None
    dialog = StepRangeDialog(steps, default_start_id=default_start_id, parent=parent)
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.selected_range()
