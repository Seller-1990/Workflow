# -*- coding: utf-8 -*-
"""Workflow configuration panel"""

import json
import logging
from engine import WorkflowEngine
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QGroupBox,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QMessageBox,
    QComboBox,
    QPlainTextEdit,
    QGridLayout,
    QLabel,
    QFileDialog,
)
from PySide6.QtCore import Signal, Qt

from database import get_workflow_by_id, update_workflow, list_webhooks
from notifier import get_template_variables_help
from ui.collapsible_section import CollapsibleSection

logger = logging.getLogger(__name__)


class WorkflowConfigPanel(QWidget):
    """工作流基础配置（可折叠）"""

    workflow_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._is_collapsed = True  # 默认折叠
        self._edit_enabled = True
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题与折叠按钮同一行，避免按钮单独占用一行
        self.group = CollapsibleSection("基础配置", collapsed=self._is_collapsed, header_height=44, title_font_size=16, title_weight=700)
        self.group.collapsed_changed.connect(lambda c: setattr(self, "_is_collapsed", c))
        content_layout = self.group.body_layout

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        row = 0
        self.edit_name = QLineEdit()
        grid.addWidget(QLabel("工作流名称"), row, 0)
        grid.addWidget(self.edit_name, row, 1)

        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["default", "print_bw"])
        grid.addWidget(QLabel("图表主题"), row, 2)
        grid.addWidget(self.combo_theme, row, 3)
        row += 1

        # 步骤编排（默认启用，隐藏此选项）
        self.check_use_steps = QCheckBox("启用步骤编排")
        self.check_use_steps.setChecked(True)
        self.check_use_steps.setVisible(False)  # 隐藏此选项，保留后端兼容性

        self.check_parallel = QCheckBox("启用并行")
        grid.addWidget(QLabel("并行执行"), row, 0)
        grid.addWidget(self.check_parallel, row, 1)

        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 64)
        self.spin_workers.setValue(2)
        grid.addWidget(QLabel("最大并行数"), row, 2)
        grid.addWidget(self.spin_workers, row, 3)
        row += 1

        self.check_notify = QCheckBox("启用钉钉通知")
        grid.addWidget(QLabel("通知"), row, 0)
        grid.addWidget(self.check_notify, row, 1)
        row += 1

        # Webhook 多选列表
        self.webhook_list = QComboBox()
        self.webhook_list.setPlaceholderText("选择钉钉机器人（在 Webhook 管理中配置）")
        grid.addWidget(QLabel("钉钉机器人"), row, 0)
        grid.addWidget(self.webhook_list, row, 1, 1, 3)
        row += 1
        
        # 消息模板
        self.edit_template = QLineEdit()
        self.edit_template.setPlaceholderText("{工作流名称} - {状态} - 编号={运行编号}")
        grid.addWidget(QLabel("消息模板"), row, 0)
        grid.addWidget(self.edit_template, row, 1, 1, 3)
        row += 1
        
        # 模板变量提示
        template_hint = QLabel(get_template_variables_help())
        template_hint.setStyleSheet("color: #888; font-size: 11px;")
        grid.addWidget(template_hint, row, 1, 1, 3)
        row += 1

        self.check_watch = QCheckBox("启用监听")
        grid.addWidget(QLabel("文件夹监听"), row, 0)
        grid.addWidget(self.check_watch, row, 1)

        self.combo_watch_mode = QComboBox()
        self.combo_watch_mode.addItem("任意变动触发", "any_change")
        self.combo_watch_mode.addItem("全部目录更新后触发", "all_folders_updated_since_success")
        grid.addWidget(QLabel("监听模式"), row, 2)
        grid.addWidget(self.combo_watch_mode, row, 3)
        row += 1

        # 监听目录（带浏览按钮）
        watch_layout = QHBoxLayout()
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.setSpacing(8)
        self.edit_watch_folders = QPlainTextEdit()
        self.edit_watch_folders.setPlaceholderText("每行一个目录（支持完整路径）")
        self.edit_watch_folders.setMinimumHeight(80)
        self.edit_watch_folders.setMaximumHeight(100)
        watch_layout.addWidget(self.edit_watch_folders)

        watch_btn_layout = QVBoxLayout()
        watch_btn_layout.setContentsMargins(0, 0, 0, 0)
        watch_btn_layout.setSpacing(4)
        self.btn_add_watch_folder = QPushButton("添加...")
        self.btn_add_watch_folder.setFixedWidth(60)
        self.btn_add_watch_folder.clicked.connect(self._browse_watch_folder)
        watch_btn_layout.addWidget(self.btn_add_watch_folder)
        watch_btn_layout.addStretch()
        watch_layout.addLayout(watch_btn_layout)

        watch_widget = QWidget()
        watch_widget.setLayout(watch_layout)
        grid.addWidget(QLabel("监听目录"), row, 0)
        grid.addWidget(watch_widget, row, 1, 1, 3)
        row += 1

        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(1, 3600)
        self.spin_cooldown.setValue(8)
        grid.addWidget(QLabel("扫描间隔(秒)"), row, 0)
        grid.addWidget(self.spin_cooldown, row, 1)

        self.spin_settle = QSpinBox()
        self.spin_settle.setRange(0, 3600)
        self.spin_settle.setValue(15)
        grid.addWidget(QLabel("延迟触发(秒)"), row, 2)
        grid.addWidget(self.spin_settle, row, 3)
        row += 1

        content_layout.addLayout(grid)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("保存配置")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)
        content_layout.addLayout(btn_layout)

        layout.addWidget(self.group)

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        # 折叠按钮始终可用
        self.group.body.setEnabled(self._edit_enabled)
        self.btn_save.setEnabled(self._edit_enabled)

    def _load_webhook_list(self):
        """加载 Webhook 列表"""
        current_data = self.webhook_list.currentData()
        self.webhook_list.clear()
        self.webhook_list.addItem("（未选择）", None)
        
        webhooks = list_webhooks()
        for webhook in webhooks:
            display = f"{webhook.name}"
            if webhook.keyword:
                display += f" ({webhook.keyword})"
            self.webhook_list.addItem(display, webhook.id)
        
        # 恢复选择
        if current_data:
            idx = self.webhook_list.findData(current_data)
            if idx >= 0:
                self.webhook_list.setCurrentIndex(idx)

    def load_workflow(self, workflow_id: int):
        """加载工作流配置"""
        self._workflow_id = workflow_id
        wf = get_workflow_by_id(workflow_id)
        if not wf:
            self.clear()
            return

        self.edit_name.setText(wf.name)
        idx = self.combo_theme.findText(wf.chart_theme or "default")
        if idx >= 0:
            self.combo_theme.setCurrentIndex(idx)
        else:
            self.combo_theme.setCurrentText("default")

        self.check_parallel.setChecked(bool(wf.parallel_enabled))
        self.spin_workers.setValue(int(wf.max_workers or 2))

        notify = wf.get_notify_config()
        self.check_notify.setChecked(bool(notify.get("enabled", False)))
        
        # 加载 Webhook 列表
        self._load_webhook_list()
        webhook_id = notify.get("webhook_id")
        if webhook_id:
            idx = self.webhook_list.findData(webhook_id)
            if idx >= 0:
                self.webhook_list.setCurrentIndex(idx)
        
        self.edit_template.setText(
            notify.get("message_template", "{工作流名称} - {状态} - 编号={运行编号}")
        )

        # 保持步骤编排始终启用
        self.check_use_steps.setChecked(True)

        self.check_watch.setChecked(bool(wf.watch_enabled))
        mode_index = self.combo_watch_mode.findData(wf.watch_mode or "any_change")
        if mode_index >= 0:
            self.combo_watch_mode.setCurrentIndex(mode_index)
        self.edit_watch_folders.setPlainText("\n".join(wf.get_watch_folders()))
        self.spin_cooldown.setValue(int(wf.cooldown_seconds or 8))
        self.spin_settle.setValue(int(wf.settle_seconds or 15))
        self._apply_enabled_state()

    def clear(self):
        """清空配置"""
        self._workflow_id = None
        self.edit_name.clear()
        self.combo_theme.setCurrentIndex(0)
        self.check_parallel.setChecked(False)
        self.spin_workers.setValue(2)
        self.check_notify.setChecked(False)
        self.webhook_list.setCurrentIndex(-1)
        self.edit_template.clear()
        self.check_use_steps.setChecked(True)
        self.check_watch.setChecked(False)
        self.combo_watch_mode.setCurrentIndex(0)
        self.edit_watch_folders.clear()
        self.spin_cooldown.setValue(8)
        self.spin_settle.setValue(15)
        self._apply_enabled_state()

    def save_config(self):
        """保存配置"""
        if not self._workflow_id:
            return

        # 获取选中的 webhook ID
        webhook_id = self.webhook_list.currentData()
        
        notify_config = {
            "enabled": self.check_notify.isChecked(),
            "webhook_id": webhook_id,
            "message_template": self.edit_template.text().strip() or "{工作流名称} - {状态} - 编号={运行编号}"
        }

        watch_folders = [
            line.strip() for line in self.edit_watch_folders.toPlainText().splitlines()
            if line.strip()
        ]
        if self.check_watch.isChecked():
            try:
                watch_folders = WorkflowEngine().validate_watch_folders(watch_folders)
            except ValueError as e:
                QMessageBox.warning(self, "监听目录无效", str(e))
                return

        try:
            update_workflow(
                self._workflow_id,
                name=self.edit_name.text().strip(),
                chart_theme=self.combo_theme.currentText(),
                parallel_enabled=self.check_parallel.isChecked(),
                max_workers=self.spin_workers.value(),
                notify_config=json.dumps(notify_config, ensure_ascii=False),
                watch_enabled=self.check_watch.isChecked(),
                watch_mode=self.combo_watch_mode.currentData(),
                watch_folders=json.dumps(watch_folders, ensure_ascii=False) if watch_folders else None,
                cooldown_seconds=self.spin_cooldown.value(),
                settle_seconds=self.spin_settle.value(),
                # 单脚本模式始终禁用
                single_script_enabled=False
            )
            self.workflow_updated.emit()
        except Exception as e:
            logger.exception("保存工作流配置失败: workflow_id=%s", self._workflow_id)
            QMessageBox.critical(self, "保存失败", str(e))

    def _browse_watch_folder(self):
        """浏览并添加监听文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择监听目录"
        )
        
        if dir_path:
            current = self.edit_watch_folders.toPlainText()
            if current.strip():
                self.edit_watch_folders.setPlainText(current.rstrip('\n') + '\n' + dir_path)
            else:
                self.edit_watch_folders.setPlainText(dir_path)
