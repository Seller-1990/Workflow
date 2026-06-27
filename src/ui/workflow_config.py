# -*- coding: utf-8 -*-
"""Workflow configuration panel"""

import json
import logging
from engine import WorkflowEngine
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QComboBox,
    QGridLayout,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

from database import get_steps_by_workflow, get_workflow_by_id, update_workflow, list_webhooks
from notifier import get_template_variables_help
from ui.collapsible_section import CollapsibleSection
from ui.theme import get_colors, msg_warning, msg_critical
from watch_rules import detect_watch_output_conflicts

logger = logging.getLogger(__name__)


class WorkflowConfigPanel(QWidget):
    """工作流基础配置（可折叠）"""

    workflow_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._workflow_id = None
        self._is_collapsed = False
        self._edit_enabled = False
        self._is_dirty = False
        self._suppress_dirty = False
        self._setup_ui()
        self._connect_dirty_tracking()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.group = CollapsibleSection("配置", collapsed=False, header_height=44, title_font_size=16, title_weight=700)
        self.group.btn_toggle.hide()
        self.group.collapsed_changed.connect(lambda c: setattr(self, "_is_collapsed", c))
        self.group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        content_layout = self.group.body_layout
        content_layout.setSpacing(12)

        # U-P3-7: 统一表单 label 宽度 + 右对齐，消除 12 个 QLabel 自适应导致的对齐错乱
        def _form_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(76)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        def _section_title(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("ConfigSectionTitle")
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return lbl

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        row = 0
        grid.addWidget(_section_title("执行策略"), row, 0, 1, 4)
        row += 1

        self.edit_name = QLineEdit()
        self.edit_name.setFixedHeight(30)
        self.edit_name.setToolTip("当前工作流在左侧列表和运行历史中显示的名称")
        grid.addWidget(_form_label("名称"), row, 0)
        grid.addWidget(self.edit_name, row, 1)

        self.combo_theme = QComboBox()
        self.combo_theme.setFixedHeight(30)
        self.combo_theme.addItems(["default", "print_bw"])
        self.combo_theme.setToolTip("图表类步骤使用的默认主题")
        grid.addWidget(_form_label("主题"), row, 2)
        grid.addWidget(self.combo_theme, row, 3)
        row += 1

        # 步骤编排（默认启用，隐藏此选项）
        self.check_use_steps = QCheckBox("启用步骤编排")
        self.check_use_steps.setChecked(True)
        self.check_use_steps.setVisible(False)  # 隐藏此选项，保留后端兼容性

        self.check_parallel = QCheckBox("启用")
        self.check_parallel.setToolTip("工作流级自动并行：同一阶段内依赖满足的普通步骤可并行执行")
        grid.addWidget(_form_label("自动并行"), row, 0)
        grid.addWidget(self.check_parallel, row, 1)

        self.spin_workers = QSpinBox()
        self.spin_workers.setFixedHeight(30)
        self.spin_workers.setRange(1, 64)
        self.spin_workers.setValue(2)
        self.spin_workers.setToolTip("同时运行的最大步骤数量")
        grid.addWidget(_form_label("并行数"), row, 2)
        grid.addWidget(self.spin_workers, row, 3)
        row += 1

        grid.addWidget(_section_title("通知"), row, 0, 1, 4)
        row += 1

        self.check_notify = QCheckBox("启用")
        self.check_notify.setToolTip("工作流完成、失败或取消时发送钉钉通知")
        grid.addWidget(_form_label("通知"), row, 0)
        grid.addWidget(self.check_notify, row, 1)
        row += 1

        # Webhook 多选列表
        self.webhook_list = QComboBox()
        self.webhook_list.setFixedHeight(30)
        self.webhook_list.setPlaceholderText("选择钉钉机器人（在 Webhook 管理中配置）")
        self.webhook_list.setToolTip("选择通知要使用的钉钉机器人")
        grid.addWidget(_form_label("机器人"), row, 0)
        grid.addWidget(self.webhook_list, row, 1, 1, 3)
        row += 1
        
        # 消息模板
        self.edit_template = QLineEdit()
        self.edit_template.setFixedHeight(30)
        self.edit_template.setPlaceholderText("{工作流名称} - {状态} - 编号={运行编号}")
        self.edit_template.setToolTip("通知正文模板，可使用下方变量")
        grid.addWidget(_form_label("模板"), row, 0)
        grid.addWidget(self.edit_template, row, 1, 1, 3)
        row += 1
        
        # 模板变量提示
        self._template_hint = QLabel("可用变量：{工作流名称} / {状态} / {运行编号}")
        self._template_hint.setToolTip(get_template_variables_help())
        self._template_hint.setStyleSheet(f"color: {get_colors(self._dark)['text_tertiary']}; font-size: 11px;")
        grid.addWidget(self._template_hint, row, 1, 1, 3)
        row += 1

        grid.addWidget(_section_title("文件夹监听"), row, 0, 1, 4)
        row += 1

        self.check_watch = QCheckBox("启用")
        self.check_watch.setToolTip("监听目录变化并自动触发当前工作流")
        grid.addWidget(_form_label("监听"), row, 0)
        grid.addWidget(self.check_watch, row, 1)

        self.combo_watch_mode = QComboBox()
        self.combo_watch_mode.setFixedHeight(30)
        self.combo_watch_mode.addItem("任意变动触发", "any_change")
        self.combo_watch_mode.addItem("全部目录更新后触发", "all_folders_updated_since_success")
        self.combo_watch_mode.setToolTip("选择目录变化触发工作流的规则")
        grid.addWidget(_form_label("模式"), row, 2)
        grid.addWidget(self.combo_watch_mode, row, 3)
        row += 1

        # 监听目录（U-P2-6: QListWidget + 行内 ✕ + 存在性图标）
        watch_layout = QHBoxLayout()
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.setSpacing(8)
        self.list_watch_folders = QListWidget()
        self.list_watch_folders.setMinimumHeight(72)
        self.list_watch_folders.setMaximumHeight(112)
        self.list_watch_folders.setToolTip("当前工作流监听的目录列表")
        self.list_watch_folders.setSelectionMode(QListWidget.NoSelection)
        self.list_watch_folders.setFocusPolicy(Qt.NoFocus)
        self.list_watch_folders.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        watch_layout.addWidget(self.list_watch_folders)

        watch_btn_layout = QVBoxLayout()
        watch_btn_layout.setContentsMargins(0, 0, 0, 0)
        watch_btn_layout.setSpacing(4)
        self.btn_add_watch_folder = QPushButton("添加")
        self.btn_add_watch_folder.setFixedSize(56, 30)
        self.btn_add_watch_folder.setToolTip("添加一个监听目录")
        self.btn_add_watch_folder.setAccessibleName("添加监听目录")
        self.btn_add_watch_folder.clicked.connect(self._browse_watch_folder)
        watch_btn_layout.addWidget(self.btn_add_watch_folder)
        watch_btn_layout.addStretch()
        watch_layout.addLayout(watch_btn_layout)

        watch_widget = QWidget()
        watch_widget.setLayout(watch_layout)
        grid.addWidget(_form_label("目录"), row, 0)
        grid.addWidget(watch_widget, row, 1, 1, 3)
        row += 1

        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setFixedHeight(30)
        self.spin_cooldown.setRange(1, 3600)
        self.spin_cooldown.setValue(8)
        self.spin_cooldown.setSuffix(" 秒")
        self.spin_cooldown.setToolTip("两次扫描之间的间隔")
        grid.addWidget(_form_label("扫描间隔"), row, 0)
        grid.addWidget(self.spin_cooldown, row, 1)

        self.spin_settle = QSpinBox()
        self.spin_settle.setFixedHeight(30)
        self.spin_settle.setRange(0, 3600)
        self.spin_settle.setValue(15)
        self.spin_settle.setSuffix(" 秒")
        self.spin_settle.setToolTip("检测到变动后等待文件稳定的时间")
        grid.addWidget(_form_label("延迟触发"), row, 2)
        grid.addWidget(self.spin_settle, row, 3)
        row += 1

        content_layout.addLayout(grid)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 2, 0, 0)
        btn_layout.addStretch()
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("primaryRect")
        self.btn_save.setFixedSize(96, 32)
        self.btn_save.setToolTip("保存当前工作流配置")
        self.btn_save.setAccessibleName("保存配置")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)
        content_layout.addLayout(btn_layout)

        layout.addWidget(self.group, alignment=Qt.AlignTop)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.group.refresh_theme(dark)
        self._template_hint.setStyleSheet(f"color: {colors['text_tertiary']}; font-size: 11px;")
        self.setStyleSheet(f"""
            QLabel#ConfigSectionTitle {{
                color: {colors['text_primary']};
                font-size: 13px;
                font-weight: 700;
                padding-top: 8px;
                padding-bottom: 2px;
            }}
        """)

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        self.group.body.setEnabled(self._edit_enabled)
        self.group.set_collapsed(False)
        self.group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.btn_save.setEnabled(self._edit_enabled)
        self.btn_save.setToolTip("保存当前工作流配置" if self._edit_enabled else "保存配置（需要先开启编辑）")
        self.btn_add_watch_folder.setToolTip("添加一个监听目录" if self._edit_enabled else "添加监听目录（需要先开启编辑）")

    def _load_webhook_list(self):
        """加载 Webhook 列表"""
        current_data = self.webhook_list.currentData()
        previous_suppress = self._suppress_dirty
        self._suppress_dirty = True
        try:
            self.webhook_list.clear()
            self.webhook_list.addItem("（未选择）", None)

            webhooks = list_webhooks()
            for webhook in webhooks:
                display = f"{webhook.name}"
                if webhook.keyword:
                    display += f" ({webhook.keyword})"
                self.webhook_list.addItem(display, webhook.id)

            # 恢复选择
            if current_data is not None:
                idx = self.webhook_list.findData(current_data)
                if idx >= 0:
                    self.webhook_list.setCurrentIndex(idx)
        finally:
            self._suppress_dirty = previous_suppress

    def refresh_webhooks(self) -> None:
        """公开刷新 Webhook 下拉项，供外部窗口安全调用。"""
        self._load_webhook_list()

    def load_workflow(self, workflow_id: int):
        """加载工作流配置"""
        if workflow_id is None:
            self.clear()
            return
        try:
            wid = int(workflow_id)
        except (ValueError, TypeError):
            self.clear()
            return
        self._workflow_id = wid
        wf = get_workflow_by_id(wid)
        if not wf:
            self.clear()
            return

        self._suppress_dirty = True
        try:
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
            if webhook_id is not None:
                idx = self.webhook_list.findData(webhook_id)
                if idx >= 0:
                    self.webhook_list.setCurrentIndex(idx)
                else:
                    self.webhook_list.setCurrentIndex(0)
            else:
                self.webhook_list.setCurrentIndex(0)

            self.edit_template.setText(
                notify.get("message_template", "{工作流名称} - {状态} - 编号={运行编号}")
            )

            # 保持步骤编排始终启用
            self.check_use_steps.setChecked(True)

            self.check_watch.setChecked(bool(wf.watch_enabled))
            mode_index = self.combo_watch_mode.findData(wf.watch_mode or "any_change")
            if mode_index >= 0:
                self.combo_watch_mode.setCurrentIndex(mode_index)
            self._set_watch_folders(wf.get_watch_folders())
            self.spin_cooldown.setValue(int(wf.cooldown_seconds or 8))
            self.spin_settle.setValue(int(wf.settle_seconds or 15))
            self._apply_enabled_state()
        finally:
            self._suppress_dirty = False
        self._is_dirty = False

    def clear(self):
        """清空配置"""
        self._suppress_dirty = True
        try:
            self._workflow_id = None
            self.edit_name.clear()
            self.combo_theme.setCurrentIndex(0)
            self.check_parallel.setChecked(False)
            self.spin_workers.setValue(2)
            self.check_notify.setChecked(False)
            if self.webhook_list.count():
                self.webhook_list.setCurrentIndex(0)
            else:
                self.webhook_list.setCurrentIndex(-1)
            self.edit_template.clear()
            self.check_use_steps.setChecked(True)
            self.check_watch.setChecked(False)
            self.combo_watch_mode.setCurrentIndex(0)
            self.list_watch_folders.clear()
            self.spin_cooldown.setValue(8)
            self.spin_settle.setValue(15)
            self._apply_enabled_state()
        finally:
            self._suppress_dirty = False
        self._is_dirty = False

    def save_config(self) -> bool:
        """保存配置"""
        if self._workflow_id is None:
            msg_warning(self, self._dark, "保存失败", "未选择工作流")
            return False

        # 获取选中的 webhook ID
        webhook_id = self.webhook_list.currentData()
        
        notify_config = {
            "enabled": self.check_notify.isChecked(),
            "webhook_id": webhook_id,
            "message_template": self.edit_template.text().strip() or "{工作流名称} - {状态} - 编号={运行编号}"
        }

        watch_folders = self._get_watch_folders()
        if self.check_watch.isChecked():
            try:
                watch_folders = WorkflowEngine.validate_watch_folders(watch_folders)
            except ValueError as e:
                msg_warning(self, self._dark, "监听目录无效", str(e))
                return False
            conflicts = detect_watch_output_conflicts(
                watch_folders,
                get_steps_by_workflow(self._workflow_id),
            )
            if conflicts:
                joined = "\n".join(conflicts)
                msg_warning(
                    self,
                    self._dark,
                    "监听目录高风险",
                    f"以下监听目录与当前工作流输出目录重叠，保存已阻止：\n{joined}",
                )
                return False

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
            self._is_dirty = False
            # #6: 保存成功反馈，避免用户对静默 emit 产生疑问
            try:
                window = self.window()
                statusbar = getattr(window, "statusbar", None)
                if statusbar is not None:
                    statusbar.showMessage("配置已保存", 2000)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.exception("保存工作流配置失败: workflow_id=%s", self._workflow_id)
            msg_critical(self, self._dark, "保存失败", str(e))
            return False

    def _browse_watch_folder(self):
        """浏览并添加监听文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择监听目录"
        )

        if dir_path:
            # U-P2-6: 去重，避免同一路径多次添加
            existing = set(self._get_watch_folders())
            if dir_path not in existing:
                self._add_watch_folder_item(dir_path)

    # ── U-P2-6: 监听目录列表项辅助 ──
    def _add_watch_folder_item(self, path: str) -> None:
        """以行内 ✕ + 存在性图标的形式追加一行监听目录"""
        import os
        item = QListWidgetItem()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(8)

        icon_label = QLabel("✓" if os.path.isdir(path) else "✕")
        icon_label.setFixedWidth(16)
        # V9.2：路径状态图标色从主题模板取（success/danger）
        _colors = get_colors(self._dark)
        icon_color = _colors["success"] if os.path.isdir(path) else _colors["danger"]
        icon_label.setStyleSheet(f"color: {icon_color}; font-weight: 700;")
        icon_label.setToolTip("目录存在" if os.path.isdir(path) else "目录不存在")
        layout.addWidget(icon_label)

        path_label = QLabel(path)
        path_label.setToolTip(path)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(path_label, stretch=1)

        btn_delete = QToolButton()
        btn_delete.setText("✕")
        btn_delete.setToolTip("删除该监听目录")
        btn_delete.setFixedSize(24, 24)
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setAutoRaise(True)
        btn_delete.clicked.connect(lambda _=False, p=path: self._remove_watch_folder(p))
        layout.addWidget(btn_delete)

        # 记录路径到 item.data，方便取/删
        item.setData(Qt.UserRole, path)
        item.setSizeHint(row.sizeHint())
        self.list_watch_folders.addItem(item)
        self.list_watch_folders.setItemWidget(item, row)
        self._mark_dirty()

    def _remove_watch_folder(self, path: str) -> None:
        for i in range(self.list_watch_folders.count() - 1, -1, -1):
            it = self.list_watch_folders.item(i)
            if it and it.data(Qt.UserRole) == path:
                self.list_watch_folders.takeItem(i)
                self._mark_dirty()
                break

    def _get_watch_folders(self) -> list:
        result = []
        for i in range(self.list_watch_folders.count()):
            it = self.list_watch_folders.item(i)
            if it:
                p = it.data(Qt.UserRole)
                if isinstance(p, str) and p.strip():
                    result.append(p.strip())
        return result

    def _set_watch_folders(self, folders) -> None:
        self.list_watch_folders.clear()
        for path in folders or []:
            if path and isinstance(path, str):
                self._add_watch_folder_item(path.strip())

    def is_dirty(self) -> bool:
        return bool(self._is_dirty and self._workflow_id is not None)

    def reset_dirty_state(self) -> None:
        self._is_dirty = False

    def discard_changes(self) -> None:
        if self._workflow_id is None:
            self.clear()
            return
        self.load_workflow(self._workflow_id)

    def _mark_dirty(self, *_args, **_kwargs) -> None:
        if self._suppress_dirty:
            return
        self._is_dirty = True

    def _connect_dirty_tracking(self) -> None:
        for widget in (self.edit_name, self.edit_template):
            try:
                widget.textChanged.connect(self._mark_dirty)
            except Exception:
                pass
        for widget in (self.check_parallel, self.check_notify, self.check_watch):
            try:
                widget.stateChanged.connect(self._mark_dirty)
            except Exception:
                pass
        for widget in (self.spin_workers, self.spin_cooldown, self.spin_settle):
            try:
                widget.valueChanged.connect(self._mark_dirty)
            except Exception:
                pass
        for widget in (self.combo_theme, self.webhook_list, self.combo_watch_mode):
            try:
                widget.currentIndexChanged.connect(self._mark_dirty)
            except Exception:
                pass
