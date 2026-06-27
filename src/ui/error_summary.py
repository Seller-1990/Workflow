# -*- coding: utf-8 -*-
"""错误汇总弹窗：工作流运行失败后显示所有失败步骤的摘要"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QHBoxLayout, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from ui.theme import COLORS, get_colors, get_status_tokens, msg_information


class ErrorSummaryDialog(QDialog):
    """错误汇总弹窗
    
    接收 error_details 信号的数据：
    [{"step_id": int, "step_name": str, "error_message": str}, ...]
    """
    navigate_to_step = Signal(int)     # step_id
    retry_failed = Signal()            # 一键重试失败步骤
    open_step_log = Signal(int)        # step_id（可选：外部处理）
    
    def __init__(self, error_list: list, parent=None, workflow_id: int = None):
        super().__init__(parent)
        self.setWindowTitle("运行失败汇总")
        self.setMinimumSize(600, 300)
        # 任务11：从父窗口继承暗色模式（若父窗口有 _dark_mode 字段）
        self._dark = False
        if parent is not None and hasattr(parent, "_dark_mode"):
            self._dark = bool(parent._dark_mode)
        self._error_list = error_list or []
        self._workflow_id = workflow_id
        self._setup_ui(self._error_list)
    
    def _setup_ui(self, error_list: list):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # 标题
        header = QLabel(f"共 {len(error_list)} 个步骤失败：")
        header.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLORS['danger']};")
        layout.addWidget(header)
        
        # 失败步骤表格（3列：步骤名称、错误信息、修复建议）
        self.table = QTableWidget(len(error_list), 3)
        self.table.setHorizontalHeaderLabels(["步骤名称", "错误信息", "修复建议"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.cellDoubleClicked.connect(self._navigate_row)

        for row, item in enumerate(error_list):
            step_id = item.get("step_id")
            name_cell = QTableWidgetItem(item.get("step_name", ""))
            name_cell.setTextAlignment(Qt.AlignCenter)
            if step_id:
                name_cell.setData(Qt.UserRole, int(step_id))
            # U-P2-3: 走主题 token，避免硬编码
            tokens = get_status_tokens(self._dark)
            colors = get_colors(self._dark)
            fail_bg = QColor(tokens["failure"]["bg"])
            primary_fg = QColor(colors["primary"])
            name_cell.setBackground(fail_bg)
            self.table.setItem(row, 0, name_cell)

            err_cell = QTableWidgetItem(item.get("error_message", ""))
            err_cell.setToolTip(item.get("error_message", ""))
            err_cell.setBackground(fail_bg)
            self.table.setItem(row, 1, err_cell)

            # 修复建议列
            fix_text = item.get("suggested_fix", "")
            fix_cell = QTableWidgetItem(fix_text if fix_text else "")
            fix_cell.setToolTip(fix_text if fix_text else "暂无建议")
            if fix_text:
                fix_cell.setForeground(primary_fg)
            fix_cell.setBackground(fail_bg)
            self.table.setItem(row, 2, fix_cell)
        
        layout.addWidget(self.table)
        
        # 底部按钮（U-P1-8 修复：建立主次区分 - Primary=重试失败步骤，关闭右对齐）
        btn_layout = QHBoxLayout()
        btn_locate = QPushButton("定位到步骤")
        btn_locate.setMinimumWidth(100)
        btn_locate.clicked.connect(self._navigate_selected)
        btn_layout.addWidget(btn_locate)

        btn_open_log = QPushButton("打开步骤日志")
        btn_open_log.setMinimumWidth(110)
        btn_open_log.clicked.connect(self._open_selected_log)
        btn_layout.addWidget(btn_open_log)

        btn_copy = QPushButton("复制到剪贴板")
        btn_copy.setMinimumWidth(100)
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()

        # Primary：重试（更显眼，作为默认动作）
        btn_retry = QPushButton("重试失败步骤")
        btn_retry.setMinimumWidth(120)
        btn_retry.setObjectName("primaryAction")
        btn_retry.setDefault(True)
        c = get_colors(self._dark)
        primary = c["primary"]
        primary_hover = c["primary_hover"]
        btn_retry.setStyleSheet(
            f"QPushButton#primaryAction {{"
            f"  background-color: {primary}; color: {c['on_primary']};"
            f"  border-radius: 6px; padding: 6px 12px; font-weight: 600;"
            f"}}"
            f"QPushButton#primaryAction:hover {{ background-color: {primary_hover}; }}"
        )
        btn_retry.clicked.connect(lambda: self.retry_failed.emit())
        btn_layout.addWidget(btn_retry)

        btn_close = QPushButton("关闭")
        btn_close.setMinimumWidth(80)
        btn_close.setShortcut("Esc")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def _selected_step_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        step_id = item.data(Qt.UserRole)
        return int(step_id) if step_id else None

    def _navigate_row(self, row: int):
        """双击指定行时导航到对应步骤"""
        item = self.table.item(row, 0)
        if item:
            step_id = item.data(Qt.UserRole)
            if step_id:
                self.navigate_to_step.emit(int(step_id))

    def _navigate_selected(self):
        step_id = self._selected_step_id()
        if not step_id:
            msg_information(self, self._dark, "提示", "请先选中一个失败步骤。")
            return
        self.navigate_to_step.emit(step_id)

    def _open_selected_log(self):
        step_id = self._selected_step_id()
        if not step_id:
            msg_information(self, self._dark, "提示", "请先选中一个失败步骤。")
            return
        # 外部若绑定了 open_step_log，则优先交给外部（便于复用 LogPanel 的上下文）
        if self.receivers("2open_step_log(int)") > 0:
            self.open_step_log.emit(step_id)
            return
        # 否则做一个最小可用的打开动作
        try:
            import os
            from database import get_latest_run_history, get_step_logs_by_run

            workflow_id = self._workflow_id
            if workflow_id:
                latest = get_latest_run_history(workflow_id)
                if latest:
                    logs = get_step_logs_by_run(latest.id)
                    target = next((l for l in logs if l.step_id == step_id), None)
                    if target:
                        for path in [getattr(target, "stdout_path", None), getattr(target, "stderr_path", None)]:
                            if path and os.path.exists(path):
                                os.startfile(path)
                                return
        except Exception:
            pass
        msg_information(self, self._dark, "提示", "未找到该步骤可打开的日志文件。")

    def _copy_to_clipboard(self):
        """复制错误列表到剪贴板"""
        text = []
        for row in range(self.table.rowCount()):
            step_name = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
            error_msg = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
            fix_suggestion = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            text.append(f"{step_name}\t{error_msg}\t{fix_suggestion}")

        QApplication.clipboard().setText("\n".join(text))
        msg_information(self, self._dark, "提示", "已复制到剪贴板")

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        header = self.layout().itemAt(0).widget()
        if isinstance(header, QLabel):
            header.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {colors['danger']};")
        # V9.2：同步刷新 btn_retry 样式（原 init 用 color:white，主题切换后不刷新）
        primary = colors["primary"]
        primary_hover = colors["primary_hover"]
        btn_bar = self.layout().itemAt(self.layout().count() - 1)
        if btn_bar and btn_bar.layout():
            for i in range(btn_bar.layout().count()):
                w = btn_bar.layout().itemAt(i).widget()
                if isinstance(w, QPushButton) and w.objectName() == "primaryAction":
                    w.setStyleSheet(
                        f"QPushButton#primaryAction {{"
                        f"  background-color: {primary}; color: {colors['on_primary']};"
                        f"  border-radius: 6px; padding: 6px 12px; font-weight: 600;"
                        f"}}"
                        f"QPushButton#primaryAction:hover {{ background-color: {primary_hover}; }}"
                    )
                    break
        # U-P3-5: 同步刷新表格行的失败底色与建议文字色（原实现只刷 header label）
        try:
            tokens = get_status_tokens(dark)
            fail_bg = QColor(tokens["failure"]["bg"])
            primary_fg = QColor(colors["primary"])
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(fail_bg)
                fix_cell = self.table.item(row, 2)
                if fix_cell and fix_cell.text():
                    fix_cell.setForeground(primary_fg)
        except Exception:
            pass
