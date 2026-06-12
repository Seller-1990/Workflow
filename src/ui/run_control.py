# -*- coding: utf-8 -*-
"""运行控制面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

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
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        header = QLabel("运行控制")
        f = QFont(header.font())
        f.setPointSize(15)
        f.setWeight(QFont.Weight.Bold)
        header.setFont(f)
        layout.addWidget(header)

        # 选中步骤提示
        self.lbl_selected = QLabel("未选中步骤")
        self.lbl_selected.setObjectName("selectedStepLabel")
        self.lbl_selected.setStyleSheet(f"""
            QLabel#selectedStepLabel {{
                color: {COLORS["text_tertiary"]};
                font-size: 11px;
                padding: 2px 0px;
            }}
        """)
        layout.addWidget(self.lbl_selected)

        # 全流程运行（Primary）—— U-P1-2：Primary 升 36px 加强视觉权重 & 满足 Win11 推荐 32px 最小点击区
        self.btn_run_all = QPushButton("▶  全流程运行")
        self.btn_run_all.setObjectName("runPrimary")
        self.btn_run_all.setFixedHeight(36)
        self.btn_run_all.setToolTip("从第一阶段开始运行整个工作流")
        self.btn_run_all.setAccessibleName("全流程运行")
        self.btn_run_all.clicked.connect(self._run_all)
        layout.addWidget(self.btn_run_all)

        ghost = QWidget()
        ghost_layout = QVBoxLayout(ghost)
        ghost_layout.setContentsMargins(0, 0, 0, 0)
        ghost_layout.setSpacing(2)

        # Ghost buttons：高 32px（仍满足 Win11 推荐最小点击区）
        self.btn_run_from = QPushButton("从选中步骤开始")
        self.btn_run_from.setObjectName("runGhost")
        self.btn_run_from.setFixedHeight(32)
        self.btn_run_from.setToolTip("从当前选中的步骤开始运行后续步骤")
        self.btn_run_from.setAccessibleName("从选中步骤开始")
        self.btn_run_from.clicked.connect(self._run_from)
        ghost_layout.addWidget(self.btn_run_from)

        self.btn_run_only = QPushButton("只运行选中步骤")
        self.btn_run_only.setObjectName("runGhost")
        self.btn_run_only.setFixedHeight(32)
        self.btn_run_only.setToolTip("只运行当前选中的单个步骤")
        self.btn_run_only.setAccessibleName("只运行选中步骤")
        self.btn_run_only.clicked.connect(self._run_only)
        ghost_layout.addWidget(self.btn_run_only)

        self.btn_run_stage = QPushButton("只运行该阶段")
        self.btn_run_stage.setObjectName("runGhost")
        self.btn_run_stage.setFixedHeight(32)
        self.btn_run_stage.setToolTip("只运行当前选中步骤所属的阶段")
        self.btn_run_stage.setAccessibleName("只运行该阶段")
        self.btn_run_stage.clicked.connect(self._run_stage)
        ghost_layout.addWidget(self.btn_run_stage)

        self.btn_run_from_stage = QPushButton("从该阶段开始")
        self.btn_run_from_stage.setObjectName("runGhost")
        self.btn_run_from_stage.setFixedHeight(32)
        self.btn_run_from_stage.setToolTip("从当前阶段开始运行后续阶段")
        self.btn_run_from_stage.setAccessibleName("从该阶段开始")
        self.btn_run_from_stage.clicked.connect(self._run_from_stage)
        ghost_layout.addWidget(self.btn_run_from_stage)

        self.btn_retry = QPushButton("重试失败步骤")
        self.btn_retry.setObjectName("runGhost")
        self.btn_retry.setFixedHeight(32)
        self.btn_retry.setToolTip("重试最近一次运行失败的步骤")
        self.btn_retry.setAccessibleName("重试失败步骤")
        self.btn_retry.clicked.connect(self._retry_failed)
        ghost_layout.addWidget(self.btn_retry)

        # 预演（默认可用，但视觉为「次要」）
        self.btn_dry_run = QPushButton("工作流预演")
        self.btn_dry_run.setObjectName("runGhostMuted")
        self.btn_dry_run.setFixedHeight(28)
        self.btn_dry_run.setToolTip("预览执行计划，不实际执行")
        self.btn_dry_run.setAccessibleName("工作流预演")
        self.btn_dry_run.clicked.connect(self.dry_run_clicked.emit)
        ghost_layout.addWidget(self.btn_dry_run)

        layout.addWidget(ghost)

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
        self.btn_retry.setEnabled(can_run)
        self.btn_dry_run.setEnabled(can_run)
    
    def set_selected_step(self, step_id: int, stage_uid: str = None):
        """设置选中的步骤和所属阶段"""
        self._selected_step_id = step_id
        self._selected_stage_uid = stage_uid
        if step_id:
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

    def _run_all(self):
        """全流程运行"""
        self.run_requested.emit("full", None)
    
    def _run_from(self):
        """从指定步骤开始"""
        if self._selected_step_id:
            self.run_requested.emit("from_step", self._selected_step_id)
    
    def _run_only(self):
        """只运行指定步骤"""
        if self._selected_step_id:
            self.run_requested.emit("only_step", self._selected_step_id)
    
    def _run_stage(self):
        """只运行该阶段"""
        if self._selected_stage_uid:
            self.run_requested.emit("only_stage", self._selected_stage_uid)

    def _run_from_stage(self):
        """从该阶段开始运行"""
        if self._selected_stage_uid:
            self.run_requested.emit("from_stage", self._selected_stage_uid)
    
    def _retry_failed(self):
        """重试失败步骤"""
        self.run_requested.emit("retry_failed", None)
