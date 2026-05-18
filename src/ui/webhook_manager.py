# -*- coding: utf-8 -*-
"""Webhook 管理对话框"""

from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QGroupBox, QFormLayout,
    QHeaderView, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer

from database import list_webhooks, create_webhook, update_webhook, delete_webhook
from notifier import send_dingtalk_message
from ui.theme import get_colors, msg_information, msg_warning, msg_question


class WebhookManagerDialog(QDialog):
    """Webhook 管理对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Webhook 管理")
        self.setMinimumSize(700, 500)
        self._current_webhook_id = None
        self._test_result_timer = None
        self._dark = False
        win = parent.window() if parent else None
        if win and hasattr(win, '_dark_mode'):
            self._dark = win._dark_mode
        elif win and hasattr(win, '_dark'):
            self._dark = win._dark
        self._setup_ui()
        self._load_webhooks()
        # U-P3-6: 让对话框沿用主窗口主题，避免在暗色模式下出现系统色突兀的弹窗
        try:
            from ui.theme import get_stylesheet
            self.setStyleSheet(get_stylesheet(self._dark))
        except Exception:
            pass
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QHBoxLayout(self)
        
        # 左侧：列表
        left_layout = QVBoxLayout()
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["名称", "关键字"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 100)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("新增")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)
        
        layout.addLayout(left_layout, 1)
        
        # 右侧：编辑表单
        right_layout = QVBoxLayout()
        
        form_group = QGroupBox("配置详情")
        form_layout = QFormLayout(form_group)
        
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("如：财务部机器人")
        form_layout.addRow("名称", self.edit_name)
        
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("https://oapi.dingtalk.com/robot/send?access_token=...")
        form_layout.addRow("Webhook URL", self.edit_url)
        
        self.edit_keyword = QLineEdit()
        self.edit_keyword.setPlaceholderText("钉钉安全设置中的关键字")
        form_layout.addRow("关键字", self.edit_keyword)
        
        self.edit_desc = QTextEdit()
        self.edit_desc.setMaximumHeight(60)
        self.edit_desc.setPlaceholderText("备注说明（可选）")
        form_layout.addRow("备注", self.edit_desc)
        
        right_layout.addWidget(form_group)
        
        # 操作按钮
        action_layout = QHBoxLayout()
        self.btn_test = QPushButton("🔔 测试发送")
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test_result = QLabel()
        self.lbl_test_result.setStyleSheet("font-size: 12px; padding-left: 8px;")
        self.btn_save = QPushButton("保存")
        self.btn_save.clicked.connect(self._on_save)
        action_layout.addWidget(self.btn_test)
        action_layout.addWidget(self.lbl_test_result)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_save)
        right_layout.addLayout(action_layout)
        
        right_layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        right_layout.addWidget(close_btn)
        
        layout.addLayout(right_layout, 1)
    
    def _load_webhooks(self):
        """加载 Webhook 列表"""
        self.table.setRowCount(0)
        webhooks = list_webhooks()
        
        for row, webhook in enumerate(webhooks):
            self.table.insertRow(row)
            
            name_item = QTableWidgetItem(webhook.name)
            name_item.setData(Qt.UserRole, webhook.id)
            self.table.setItem(row, 0, name_item)
            
            keyword_item = QTableWidgetItem(webhook.keyword or "")
            self.table.setItem(row, 1, keyword_item)
    
    def _on_selection_changed(self):
        """选择变化"""
        selected = self.table.selectedItems()
        if not selected:
            self._current_webhook_id = None
            self._clear_form()
            self.btn_delete.setEnabled(False)
            return
        
        row = self.table.row(selected[0])
        name_item = self.table.item(row, 0)
        webhook_id = name_item.data(Qt.UserRole)
        
        from database import get_webhook_by_id
        webhook = get_webhook_by_id(webhook_id)
        
        if webhook:
            self._current_webhook_id = webhook.id
            self.edit_name.setText(webhook.name)
            self.edit_url.setText(webhook.webhook_url)
            self.edit_keyword.setText(webhook.keyword or "")
            self.edit_desc.setPlainText(webhook.description or "")
            self.btn_delete.setEnabled(True)
    
    def _clear_form(self):
        """清空表单"""
        self._current_webhook_id = None
        self.edit_name.clear()
        self.edit_url.clear()
        self.edit_keyword.clear()
        self.edit_desc.clear()

    def _validate_webhook_url(self, url: str) -> bool:
        """验证 Webhook URL 格式"""
        if not url.startswith("https://"):
            return False
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    def _on_add(self):
        """新增"""
        self.table.clearSelection()
        self._clear_form()
        self.edit_name.setFocus()
    
    def _on_delete(self):
        """删除"""
        win = self.window()
        if hasattr(win, 'is_edit_mode') and not win.is_edit_mode():
            msg_information(self, self._dark, "提示", "请先开启编辑模式")
            return

        if not self._current_webhook_id:
            return
        
        reply = msg_question(
            self, self._dark, "确认删除",
            f"确定要删除「{self.edit_name.text()}」吗？",
        )
        
        if reply == QMessageBox.Yes:
            delete_webhook(self._current_webhook_id)
            self._clear_form()
            self._load_webhooks()
    
    def _on_save(self):
        """保存"""
        win = self.window()
        if hasattr(win, 'is_edit_mode') and not win.is_edit_mode():
            msg_information(self, self._dark, "提示", "请先开启编辑模式")
            return

        name = self.edit_name.text().strip()
        url = self.edit_url.text().strip()
        keyword = self.edit_keyword.text().strip()
        desc = self.edit_desc.toPlainText().strip()
        
        if not name:
            msg_warning(self, self._dark, "提示", "请输入名称")
            return
        
        if not url:
            msg_warning(self, self._dark, "提示", "请输入 Webhook URL")
            return
        
        if not self._validate_webhook_url(url):
            msg_warning(self, self._dark, "提示", "Webhook URL 格式无效，必须以 https:// 开头且为有效的 URL")
            return
        
        if self._current_webhook_id:
            update_webhook(
                self._current_webhook_id,
                name=name,
                webhook_url=url,
                keyword=keyword,
                description=desc
            )
            msg_information(self, self._dark, "成功", "Webhook 已更新")
        else:
            create_webhook(name, url, keyword, desc)
            msg_information(self, self._dark, "成功", "Webhook 已创建")
        
        self._load_webhooks()
    
    def _on_test(self):
        """测试发送"""
        url = self.edit_url.text().strip()
        keyword = self.edit_keyword.text().strip()
        
        if not url:
            msg_warning(self, self._dark, "提示", "请先输入 Webhook URL")
            return
        
        success, msg = send_dingtalk_message(
            url,
            f"【工作流管理】测试消息 - 来自「{self.edit_name.text() or '未命名'}」",
            keyword
        )
        
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
        self._test_result_timer = QTimer(self)
        self._test_result_timer.setSingleShot(True)
        self._test_result_timer.timeout.connect(self._clear_test_result)
        self._test_result_timer.start(5000)

    def _clear_test_result(self):
        """清除测试结果标签"""
        self.lbl_test_result.clear()

    def closeEvent(self, event):
        if self._test_result_timer is not None:
            self._test_result_timer.stop()
            self._test_result_timer = None
        super().closeEvent(event)
