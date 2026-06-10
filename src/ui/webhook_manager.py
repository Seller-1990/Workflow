# -*- coding: utf-8 -*-
"""Webhook 管理对话框"""

import logging
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFormLayout,
    QHeaderView, QMessageBox, QFrame, QToolButton
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor

from database import list_webhooks, create_webhook, update_webhook, delete_webhook
from notifier import send_dingtalk_message
from ui.theme import get_colors, get_stylesheet, msg_information, msg_warning, msg_question, msg_critical
from webhook_url_policy import is_valid_dingtalk_webhook_url


logger = logging.getLogger(__name__)

# M3: 存量非法 URL 的提示文案（列表行 tooltip 与详情面板共用）
_INVALID_WEBHOOK_URL_HINT = (
    "Webhook URL 非法或不受信任（4.1.0 起发送前校验），发送将失败，请重新保存有效地址"
)


class WebhookManagerDialog(QDialog):
    """Webhook 管理对话框"""

    # M8: 后台测试发送完成信号（worker 线程发出，自动以队列方式回到 GUI 线程）
    _test_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Webhook 管理")
        self.setMinimumSize(660, 440)
        self._current_webhook_id = None
        self._test_result_timer = None
        self._test_in_flight = False
        self._is_dirty = False
        self._suppress_dirty = False
        self._suppress_selection_change = False
        # 产品已固定浅色主题，Webhook 设置也强制浅色，避免系统/旧偏好带回深色界面。
        self._dark = False
        self._setup_ui()
        self._test_finished.connect(self._on_test_finished)
        self._connect_dirty_tracking()
        self._load_webhooks()
        self.setStyleSheet(self._build_stylesheet(False))
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.left_panel = QFrame()
        self.left_panel.setObjectName("WebhookListPanel")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        left_head = QHBoxLayout()
        left_head.setContentsMargins(0, 0, 0, 0)
        left_head.setSpacing(8)
        left_title = QLabel("机器人列表")
        left_title.setObjectName("PanelTitle")
        left_head.addWidget(left_title)
        left_head.addStretch()
        self.btn_add = QPushButton("新增")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_add.setObjectName("ghostRect")
        self.btn_add.setFixedHeight(30)
        self.btn_add.setToolTip("新增一个 Webhook")
        left_head.addWidget(self.btn_add)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setObjectName("dangerTextButton")
        self.btn_delete.setFixedHeight(30)
        self.btn_delete.setEnabled(False)
        self.btn_delete.setToolTip("删除当前选中的 Webhook")
        left_head.addWidget(self.btn_delete)
        left_layout.addLayout(left_head)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["名称", "关键字"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(1, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.table)

        layout.addWidget(self.left_panel, 1)

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("WebhookDetailPanel")
        right_layout = QVBoxLayout(self.detail_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        right_head = QHBoxLayout()
        right_head.setContentsMargins(0, 0, 0, 0)
        right_head.setSpacing(8)
        detail_title = QLabel("配置详情")
        detail_title.setObjectName("PanelTitle")
        right_head.addWidget(detail_title)
        right_head.addStretch()
        self.detail_state = QLabel("选择左侧条目进行编辑")
        self.detail_state.setObjectName("PanelHint")
        right_head.addWidget(self.detail_state)
        right_layout.addLayout(right_head)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(8)

        def _label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(78)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("如：财务部机器人")
        self.edit_name.setFixedHeight(30)
        self.edit_name.setToolTip("Webhook 显示名称")
        form_layout.addRow(_label("名称"), self.edit_name)
        
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("https://oapi.dingtalk.com/robot/send?access_token=...")
        self.edit_url.setFixedHeight(30)
        self.edit_url.setEchoMode(QLineEdit.Password)
        self.edit_url.setToolTip("钉钉机器人的 Webhook 地址")
        url_layout = QHBoxLayout()
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(6)
        url_layout.addWidget(self.edit_url, stretch=1)
        self.btn_toggle_url = QToolButton()
        self.btn_toggle_url.setText("显示")
        self.btn_toggle_url.setCheckable(True)
        self.btn_toggle_url.setFixedHeight(30)
        self.btn_toggle_url.setToolTip("显示或隐藏 Webhook URL")
        self.btn_toggle_url.toggled.connect(self._toggle_url_visibility)
        url_layout.addWidget(self.btn_toggle_url)
        form_layout.addRow(_label("URL"), url_layout)
        
        self.edit_keyword = QLineEdit()
        self.edit_keyword.setPlaceholderText("钉钉安全设置中的关键字")
        self.edit_keyword.setFixedHeight(30)
        self.edit_keyword.setToolTip("钉钉机器人安全关键字")
        form_layout.addRow(_label("关键字"), self.edit_keyword)
        
        self.edit_desc = QTextEdit()
        self.edit_desc.setMaximumHeight(72)
        self.edit_desc.setPlaceholderText("备注说明（可选）")
        self.edit_desc.setToolTip("备注说明，不影响发送")
        form_layout.addRow(_label("备注"), self.edit_desc)

        right_layout.addLayout(form_layout)

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 2, 0, 0)
        self.btn_test = QPushButton("测试发送")
        self.btn_test.setObjectName("ghostRect")
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test_result = QLabel()
        self.lbl_test_result.setObjectName("TestResult")
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("primaryRect")
        self.btn_save.clicked.connect(self._on_save)
        action_layout.addWidget(self.btn_test)
        action_layout.addWidget(self.lbl_test_result)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_save)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("ghostRect")
        # 走 close() 触发 closeEvent，保证未保存确认与窗口 X 行为一致
        self.btn_close.clicked.connect(self.close)
        action_layout.addWidget(self.btn_close)
        right_layout.addLayout(action_layout)

        layout.addWidget(self.detail_panel, 1)

    def _build_stylesheet(self, dark: bool) -> str:
        colors = get_colors(dark)
        return get_stylesheet(False) + f"""
            QFrame#WebhookListPanel, QFrame#WebhookDetailPanel {{
                background: {colors['surface_card']};
                border: 1px solid {colors['border_subtle']};
                border-radius: 12px;
            }}
            QLabel#PanelTitle {{
                color: {colors['text_primary']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#PanelHint {{
                color: {colors['text_tertiary']};
                font-size: 11px;
            }}
            QLabel#TestResult {{
                color: {colors['text_tertiary']};
                font-size: 12px;
                padding-left: 6px;
            }}
            QTableWidget {{
                background: {colors['background']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
            }}
            QHeaderView::section {{
                background: {colors['surface_header']};
                color: {colors['text_secondary']};
                border: none;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QTableWidget::item {{
                padding: 5px 8px;
            }}
            QTableWidget::item:selected {{
                background: {colors['selected_bg']};
                color: {colors['selected_text']};
            }}
            QLineEdit, QTextEdit {{
                background: {colors['background']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 0px 10px;
            }}
            QTextEdit {{
                padding-top: 8px;
                padding-bottom: 8px;
            }}
            QPushButton#ghostRect {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 0px 12px;
                color: {colors['text_primary']};
                font-weight: 600;
            }}
            QPushButton#ghostRect:hover {{
                background: {colors['hover']};
            }}
            QPushButton#dangerTextButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 0px 8px;
                color: {colors['danger']};
                font-weight: 600;
            }}
            QPushButton#dangerTextButton:hover {{
                background: {colors['danger']}1A;
            }}
            QPushButton#primaryRect {{
                background: {colors['primary']};
                color: {colors['text_inverse']};
                border: none;
                border-radius: 10px;
                padding: 0px 14px;
                font-weight: 600;
            }}
            QPushButton#primaryRect:hover {{
                background: {colors['primary_hover']};
            }}
            QToolButton {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 0px 10px;
                color: {colors['text_primary']};
                font-weight: 600;
            }}
            QToolButton:hover {{
                background: {colors['hover']};
            }}
        """
    
    def _load_webhooks(self, selected_id: int | None = None):
        """加载 Webhook 列表"""
        if selected_id is None:
            selected = self.table.selectedItems()
            if selected:
                row = self.table.row(selected[0])
                name_item = self.table.item(row, 0)
                selected_id = name_item.data(Qt.UserRole) if name_item else None
            else:
                selected_id = self._current_webhook_id
        self._suppress_selection_change = True
        self.table.setRowCount(0)
        webhooks = list_webhooks()
        selected_row = None

        for row, webhook in enumerate(webhooks):
            self.table.insertRow(row)

            name_item = QTableWidgetItem(webhook.name)
            name_item.setData(Qt.UserRole, webhook.id)
            # M3: 存量非法 URL（4.1.0 之前可能保存）发送时会被拒绝，列表中直接标红提示
            if not is_valid_dingtalk_webhook_url(webhook.webhook_url):
                danger_color = get_colors(self._dark)["danger"]
                name_item.setForeground(QBrush(QColor(danger_color)))
                name_item.setToolTip(_INVALID_WEBHOOK_URL_HINT)
            self.table.setItem(row, 0, name_item)

            keyword_item = QTableWidgetItem(webhook.keyword or "")
            self.table.setItem(row, 1, keyword_item)
            if selected_id == webhook.id:
                selected_row = row

        try:
            if selected_row is not None:
                self.table.selectRow(selected_row)
            else:
                self.table.clearSelection()
        finally:
            self._suppress_selection_change = False
        if selected_row is not None:
            item = self.table.item(selected_row, 0)
            webhook_id = item.data(Qt.UserRole) if item else None
            self._load_webhook_by_id(webhook_id)
            return

        self._clear_form()
        self.btn_delete.setEnabled(False)
        self.detail_state.setText("选择左侧条目进行编辑")
    
    def _on_selection_changed(self):
        """选择变化"""
        if self._suppress_selection_change:
            return
        selected = self.table.selectedItems()
        target_webhook_id = None
        if selected:
            row = self.table.row(selected[0])
            name_item = self.table.item(row, 0)
            target_webhook_id = name_item.data(Qt.UserRole) if name_item else None
        if target_webhook_id == self._current_webhook_id:
            return
        if not self._confirm_discard_unsaved(action="switch"):
            self._restore_selection()
            return
        if target_webhook_id is None:
            self._clear_form()
            self.btn_delete.setEnabled(False)
            self.detail_state.setText("选择左侧条目进行编辑")
            return
        self._load_webhook_by_id(target_webhook_id)
    
    def _clear_form(self):
        """清空表单"""
        self._suppress_dirty = True
        try:
            self._current_webhook_id = None
            self.edit_name.clear()
            self.edit_url.clear()
            self.btn_toggle_url.setChecked(False)
            self.edit_keyword.clear()
            self.edit_desc.clear()
        finally:
            self._suppress_dirty = False
        self._is_dirty = False

    def _validate_webhook_url(self, url: str) -> bool:
        """验证钉钉机器人 Webhook URL 格式。"""
        return is_valid_dingtalk_webhook_url(url)

    def _toggle_url_visibility(self, visible: bool) -> None:
        self.edit_url.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.btn_toggle_url.setText("隐藏" if visible else "显示")

    def _ensure_edit_mode(self) -> bool:
        host = self.parentWidget() or self
        if hasattr(host, "is_edit_mode") and not host.is_edit_mode():
            msg_information(self, self._dark, "提示", "请先开启编辑模式")
            return False
        return True

    def _handle_action_error(self, action_name: str, exc: Exception) -> None:
        logger.exception("Webhook%s失败: %s", action_name, exc)
        msg_critical(self, self._dark, f"{action_name}失败", str(exc))

    def _restart_test_result_timer(self) -> None:
        if self._test_result_timer is None:
            self._test_result_timer = QTimer(self)
            self._test_result_timer.setSingleShot(True)
            self._test_result_timer.timeout.connect(self._clear_test_result)
        else:
            self._test_result_timer.stop()
        self._test_result_timer.start(5000)
    
    def _on_add(self):
        """新增"""
        if not self._confirm_discard_unsaved(action="add"):
            return
        self._suppress_selection_change = True
        try:
            self.table.clearSelection()
        finally:
            self._suppress_selection_change = False
        self._clear_form()
        self.btn_delete.setEnabled(False)
        self.edit_name.setFocus()
        self.detail_state.setText("新增一个 Webhook")
    
    def _on_delete(self):
        """删除"""
        if not self._ensure_edit_mode():
            return

        if not self._current_webhook_id:
            return
        
        reply = msg_question(
            self, self._dark, "确认删除",
            f"确定要删除「{self.edit_name.text()}」吗？",
        )
        
        if reply == QMessageBox.Yes:
            try:
                if not delete_webhook(self._current_webhook_id):
                    raise ValueError("Webhook 不存在或删除失败。")
            except Exception as exc:
                self._handle_action_error("删除", exc)
                return
            self._clear_form()
            self._load_webhooks()
    
    def _on_save(self):
        """保存"""
        self._save_current_webhook(show_success=True)

    def _save_current_webhook(self, *, show_success: bool) -> bool:
        if not self._ensure_edit_mode():
            return False

        name = self.edit_name.text().strip()
        url = self.edit_url.text().strip()
        keyword = self.edit_keyword.text().strip()
        desc = self.edit_desc.toPlainText().strip()
        
        if not name:
            msg_warning(self, self._dark, "提示", "请输入名称")
            return False
        
        if not url:
            msg_warning(self, self._dark, "提示", "请输入 Webhook URL")
            return False
        
        if not self._validate_webhook_url(url):
            msg_warning(self, self._dark, "提示", "Webhook URL 格式无效，请使用钉钉机器人 HTTPS URL")
            return False
        
        try:
            if self._current_webhook_id:
                saved_webhook = update_webhook(
                    self._current_webhook_id,
                    name=name,
                    webhook_url=url,
                    keyword=keyword,
                    description=desc
                )
                if saved_webhook is None:
                    raise ValueError("Webhook 不存在或更新失败。")
                success_message = "Webhook 已更新"
            else:
                saved_webhook = create_webhook(name, url, keyword, desc)
                success_message = "Webhook 已创建"
        except Exception as exc:
            self._handle_action_error("保存", exc)
            return False

        self._load_webhooks(selected_id=getattr(saved_webhook, "id", self._current_webhook_id))
        self._is_dirty = False
        if show_success:
            msg_information(self, self._dark, "成功", success_message)
        return True
    
    def _on_test(self):
        """测试发送（M8: 网络请求在后台线程执行，避免阻塞 GUI 最长 10 秒）"""
        if not self._ensure_edit_mode():
            return

        url = self.edit_url.text().strip()
        keyword = self.edit_keyword.text().strip()

        if not url:
            msg_warning(self, self._dark, "提示", "请先输入 Webhook URL")
            return

        if not self._validate_webhook_url(url):
            msg_warning(self, self._dark, "提示", "Webhook URL 格式无效，请使用钉钉机器人 HTTPS URL")
            return

        message = f"【工作流管理】测试消息 - 来自「{self.edit_name.text() or '未命名'}」"
        self._test_in_flight = True
        self.btn_test.setEnabled(False)
        hint_color = get_colors(getattr(self, "_dark", False))["text_tertiary"]
        self.lbl_test_result.setStyleSheet(
            f"font-size: 12px; padding-left: 8px; color: {hint_color};"
        )
        self.lbl_test_result.setText("发送中...")
        self._restart_test_result_timer()

        # 在启动线程前解析发送函数，确保测试中 monkeypatch 的替身不会与
        # 线程启动时序竞争（生产环境两者等价）
        send_func = send_dingtalk_message

        def _send_in_background():
            ok, msg = send_func(url, message, keyword)
            try:
                self._test_finished.emit(ok, msg)
            except RuntimeError:
                # 对话框已被销毁（C++ 对象释放），结果无处投递，直接丢弃
                pass

        threading.Thread(
            target=_send_in_background,
            name="webhook-test-send",
            daemon=True,
        ).start()

    def _on_test_finished(self, success: bool, msg: str):
        """测试发送结果回到 GUI 线程后的展示逻辑（由 _test_finished 信号触发）"""
        self._test_in_flight = False
        self.btn_test.setEnabled(True)
        if success:
            ok_color = get_colors(getattr(self, "_dark", False))["success"]
            self.lbl_test_result.setStyleSheet(
                f"font-size: 12px; padding-left: 8px; color: {ok_color};"
            )
            self.lbl_test_result.setText("发送成功")
        else:
            err_color = get_colors(getattr(self, "_dark", False))["danger"]
            self.lbl_test_result.setStyleSheet(
                f"font-size: 12px; padding-left: 8px; color: {err_color};"
            )
            self.lbl_test_result.setText(f"发送失败: {msg}")
        self._restart_test_result_timer()

    def _clear_test_result(self):
        """清除测试结果标签"""
        if self._test_in_flight:
            # 后台发送仍在进行，保留"发送中..."提示并顺延清除时间
            self._restart_test_result_timer()
            return
        self.lbl_test_result.clear()
        if self._test_result_timer is not None:
            self._test_result_timer.stop()

    def closeEvent(self, event):
        if not self._confirm_discard_unsaved(action="close"):
            event.ignore()
            return
        if self._test_result_timer is not None:
            self._test_result_timer.stop()
            self._test_result_timer = None
        super().closeEvent(event)

    def is_dirty(self) -> bool:
        return bool(self._is_dirty)

    def reset_dirty_state(self) -> None:
        self._is_dirty = False

    def _mark_dirty(self, *_args, **_kwargs) -> None:
        if self._suppress_dirty:
            return
        self._is_dirty = True

    def _connect_dirty_tracking(self) -> None:
        for widget in (self.edit_name, self.edit_url, self.edit_keyword):
            try:
                widget.textChanged.connect(self._mark_dirty)
            except Exception:
                pass
        try:
            self.edit_desc.textChanged.connect(self._mark_dirty)
        except Exception:
            pass

    def _load_webhook_by_id(self, webhook_id: int | None) -> None:
        if not webhook_id:
            self._clear_form()
            self.btn_delete.setEnabled(False)
            self.detail_state.setText("选择左侧条目进行编辑")
            return
        from database import get_webhook_by_id

        webhook = get_webhook_by_id(webhook_id)
        if not webhook:
            self._clear_form()
            self.btn_delete.setEnabled(False)
            self.detail_state.setText("选择左侧条目进行编辑")
            return
        self._suppress_dirty = True
        try:
            self._current_webhook_id = webhook.id
            self.edit_name.setText(webhook.name)
            self.edit_url.setText(webhook.webhook_url)
            self.edit_keyword.setText(webhook.keyword or "")
            self.edit_desc.setPlainText(webhook.description or "")
            self.btn_delete.setEnabled(True)
            # M3: 加载到表单时同样提示存量非法 URL，发送将失败
            if not is_valid_dingtalk_webhook_url(webhook.webhook_url):
                self.detail_state.setText(_INVALID_WEBHOOK_URL_HINT)
            else:
                self.detail_state.setText("当前正在编辑")
        finally:
            self._suppress_dirty = False
        self._is_dirty = False

    def _restore_selection(self) -> None:
        self._suppress_selection_change = True
        try:
            if self._current_webhook_id:
                for row in range(self.table.rowCount()):
                    name_item = self.table.item(row, 0)
                    if name_item and name_item.data(Qt.UserRole) == self._current_webhook_id:
                        self.table.selectRow(row)
                        return
            self.table.clearSelection()
        finally:
            self._suppress_selection_change = False

    def _confirm_discard_unsaved(self, *, action: str) -> bool:
        if not self.is_dirty():
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        if action == "switch":
            box.setWindowTitle("切换 Webhook 前是否保存？")
            box.setText("当前 Webhook 有未保存的修改。\n切换条目前要先保存吗？")
            save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
        elif action == "add":
            box.setWindowTitle("新增 Webhook 前是否保存？")
            box.setText("当前 Webhook 有未保存的修改。\n新增条目前要先保存吗？")
            save_btn = box.addButton("保存并新增", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存直接新增", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
        else:
            box.setWindowTitle("关闭前是否保存？")
            box.setText("当前 Webhook 有未保存的修改。\n关闭前要先保存吗？")
            save_btn = box.addButton("保存并关闭", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存直接关闭", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save_btn:
            return self._save_current_webhook(show_success=False)
        if clicked is discard_btn:
            self.reset_dirty_state()
            return True
        return False
