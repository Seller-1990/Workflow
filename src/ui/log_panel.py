# -*- coding: utf-8 -*-
"""实时日志面板"""

from collections import deque

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout,
    QSizePolicy, QLineEdit, QToolButton, QMenu, QCheckBox,
    QWidgetAction, QFileDialog,
)
from PySide6.QtCore import Slot, Signal, QTimer, Qt
from PySide6.QtGui import QTextCursor, QFont, QAction

from ui.collapsible_section import CollapsibleSection
from ui.theme import COLORS, get_colors, get_log_level_colors, get_menu_stylesheet, get_status_tokens
from constants import MAX_LOG_LINES as _MAX_LOG_LINES


_LEVELS = ("ERROR", "WARNING", "INFO", "DEBUG")


class LogPanel(QWidget):
    """实时日志面板（U-P2-8: 支持级别过滤 + 防抖搜索 + 导出）"""

    stop_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._step_id = None
        self._is_running = False
        self._dark = False
        # L4: 批量刷新，避免高频日志触发 QTextEdit 单行 append 的布局风暴
        self._pending_html: list[str] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_pending)
        # U-P2-8: 日志条目存储 + 过滤状态
        # P-10: 用 deque(maxlen) 替代 list + 手动裁剪，O(1) FIFO，无拷贝
        self._entries: "deque[dict]" = deque(maxlen=_MAX_LOG_LINES)
        self._level_filter: set[str] = set(_LEVELS)  # 默认全选
        self._search_text: str = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._rerender)
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题与折叠按钮同一行（与全局卡片一致）
        self.section = CollapsibleSection("实时日志", collapsed=False, header_height=44, title_font_size=15, title_weight=700)
        self.section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        group_layout = self.section.body_layout

        # U-P2-8: header 工具条 —— 级别多选 + 搜索 + 导出 + 清空
        self.btn_level = QToolButton()
        self.btn_level.setText("级别 ▾")
        self.btn_level.setObjectName("headerLink")
        self.btn_level.setPopupMode(QToolButton.InstantPopup)
        self.btn_level.setFixedHeight(22)
        self.btn_level.setToolTip("按日志级别过滤")
        self._level_menu = QMenu(self.btn_level)
        self._level_menu.setStyleSheet(get_menu_stylesheet(self._dark))
        self._level_checks: dict[str, QCheckBox] = {}
        for lvl in _LEVELS:
            cb = QCheckBox(lvl, self._level_menu)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_level_check_changed)
            act = QWidgetAction(self._level_menu)
            act.setDefaultWidget(cb)
            self._level_menu.addAction(act)
            self._level_checks[lvl] = cb
        self.btn_level.setMenu(self._level_menu)
        self.section.header_actions_layout.addWidget(self.btn_level)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索…")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.setFixedHeight(22)
        self.edit_search.setMaximumWidth(200)
        self.edit_search.textChanged.connect(self._on_search_text_changed)
        self.section.header_actions_layout.addWidget(self.edit_search)

        self.btn_export = QPushButton("导出")
        self.btn_export.setObjectName("headerLink")
        self.btn_export.setFixedHeight(22)
        self.btn_export.setToolTip("导出当前可见日志到文件")
        self.btn_export.clicked.connect(self._on_export)
        self.section.header_actions_layout.addWidget(self.btn_export)

        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("headerLink")
        self.btn_clear.setFixedHeight(22)
        self.btn_clear.clicked.connect(self.clear)
        self.section.header_actions_layout.addWidget(self.btn_clear)

        # 任务12：紧凑模式切换——紧凑下行高降低、字体变小
        self.btn_compact = QPushButton("紧凑")
        self.btn_compact.setObjectName("headerLink")
        self.btn_compact.setCheckable(True)
        self.btn_compact.setFixedHeight(22)
        self.btn_compact.setToolTip("切换紧凑模式（更小字体、更低行高）")
        self.btn_compact.toggled.connect(self._on_compact_toggled)
        self.section.header_actions_layout.addWidget(self.btn_compact)
        self._compact_mode = False

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setAccessibleName("实时日志")
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['background']};
                color: {COLORS['text_primary']};
                border: none;
                border-radius: 12px;
                padding: 12px;
            }}
        """)
        group_layout.addWidget(self.log_text, stretch=1)

        layout.addWidget(self.section, stretch=1)

    def set_running(self, running: bool):
        """启用/禁用运行状态"""
        self._is_running = bool(running)
    
    # 日志级别 -> 颜色映射（U-P1-3：迁移到 theme.py 单一真相源）
    @property
    def _LEVEL_COLORS(self):
        return get_log_level_colors(self._dark)

    def _parse_log_level(self, message: str):
        """从日志消息中解析级别标签

        Returns:
            (level_str, clean_message) 或 (None, original_message)
        """
        import re
        match = re.match(r'^(\[\d{2}:\d{2}:\d{2}\])\s+\[(\w+)\]\s+(.*)', message)
        if match:
            return match.group(2), message  # 返回级别和原始消息
        return None, message

    def _render_entry_html(self, entry: dict) -> str:
        """按当前主题把日志条目渲染成 HTML。"""
        import html as html_mod
        plain = entry.get("plain", "")
        safe_msg = html_mod.escape(plain)
        level = entry.get("level")
        if level and level in self._LEVEL_COLORS:
            color = self._LEVEL_COLORS[level]
            return f'<span style="color:{color}">{safe_msg}</span>'
        return safe_msg

    @Slot(str)
    def append_log(self, message: str):
        """追加日志（根据级别自动着色，批量刷新；U-P2-8: 同时进入条目存储）"""
        level, _ = self._parse_log_level(message)
        # 存进条目区（用于过滤/搜索/导出）。无级别标签的归入 INFO。
        entry_level = (level if level in _LEVELS else "INFO")
        entry = {"level": entry_level, "plain": message}
        self._entries.append(entry)
        # 行数裁剪由 deque(maxlen) 自动处理，无需手工 del
        # 过滤匹配才进入 UI 缓冲
        if not self._entry_passes_filter(entry):
            return
        self._pending_html.append(self._render_entry_html(entry))
        # 阈值刷新（突发日志）+ 定时刷新（稀疏日志）
        if len(self._pending_html) >= 32:
            self._flush_pending()
        elif not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self):
        """L4: 把缓冲区里的日志一次性写入 QTextEdit"""
        if not self._pending_html:
            return
        pending = self._pending_html
        self._pending_html = []
        for html in pending:
            self.log_text.append(html)
        # 行数裁剪
        block_count = self.log_text.document().blockCount()
        if block_count > _MAX_LOG_LINES:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(
                QTextCursor.Down, QTextCursor.KeepAnchor,
                block_count - _MAX_LOG_LINES,
            )
            cursor.removeSelectedText()
            cursor.deleteChar()
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.section.refresh_theme(dark)
        self._level_menu.setStyleSheet(get_menu_stylesheet(dark))
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors['background']};
                color: {colors['text_primary']};
                border: none;
                border-radius: 12px;
                padding: 12px;
            }}
        """)
        if self._entries:
            self._rerender()
    
    def _on_compact_toggled(self, checked: bool):
        """任务12：紧凑模式切换——调整字体大小和行间距"""
        self._compact_mode = checked
        if checked:
            self.log_text.setFont(QFont("Consolas", 8))
            self.log_text.setStyleSheet(self._log_text_style(compact=True))
        else:
            self.log_text.setFont(QFont("Consolas", 9))
            self.log_text.setStyleSheet(self._log_text_style(compact=False))

    def _log_text_style(self, compact: bool = False) -> str:
        """任务12：日志文本框样式（紧凑/标准）"""
        colors = get_colors(self._dark)
        line_height = "16px" if compact else "20px"
        return f"""
            QTextEdit {{
                background: {colors['background']};
                color: {colors['text_primary']};
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, 'Courier New', monospace;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0;
            }}
        """

    def clear(self):
        """清空日志"""
        self._pending_html.clear()
        if self._flush_timer.isActive():
            self._flush_timer.stop()
        self._entries.clear()
        self.log_text.clear()

    # ── U-P2-8: 过滤 / 搜索 / 导出 ──
    def _entry_passes_filter(self, entry: dict) -> bool:
        if entry.get("level") not in self._level_filter:
            return False
        if self._search_text:
            return self._search_text.lower() in (entry.get("plain") or "").lower()
        return True

    def _on_level_check_changed(self, _state: int):
        active = {lvl for lvl, cb in self._level_checks.items() if cb.isChecked()}
        if not active:
            # 至少保留一个级别，避免空过滤导致无任何输出
            active = set(_LEVELS)
            for cb in self._level_checks.values():
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
        if active != self._level_filter:
            self._level_filter = active
            self._rerender()

    def _on_search_text_changed(self, text: str):
        self._search_text = (text or "").strip()
        # 防抖：用户停顿 300ms 后再重渲
        self._search_timer.start()

    def _rerender(self):
        """根据当前过滤条件重建 QTextEdit 内容"""
        self._pending_html.clear()
        if self._flush_timer.isActive():
            self._flush_timer.stop()
        self.log_text.clear()
        for entry in self._entries:
            if self._entry_passes_filter(entry):
                self.log_text.append(self._render_entry_html(entry))
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

    def _on_export(self):
        """把当前过滤后的日志条目导出为 .log/.txt"""
        from datetime import datetime
        default_name = f"workflow_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", default_name, "日志文件 (*.log *.txt);;全部文件 (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for entry in self._entries:
                    if self._entry_passes_filter(entry):
                        f.write(entry.get("plain", ""))
                        f.write("\n")
        except OSError as e:
            from ui.theme import msg_critical
            msg_critical(self, self._dark, "导出失败", f"无法写入文件:\n{e}")

    def set_context(self, workflow_id: int = None, step_id: int = None):
        """设置当前上下文"""
        self._workflow_id = workflow_id
        self._step_id = step_id

    def open_step_log(self):
        """打开当前上下文对应步骤在最新运行中的日志目录（或 stdout 文件）"""
        if not self._workflow_id or not self._step_id:
            return
        try:
            import os
            # P-11: 改用单条 IN 查询批量获取最近 20 个 run 的对应 step_log，
            # 替代原"循环 history × 每条查 step_logs"的 N+1 调用
            from database import get_recent_step_logs_for_step

            logs = get_recent_step_logs_for_step(self._workflow_id, self._step_id, limit=20) or []
            for target in logs:
                stdout_path = getattr(target, "stdout_path", None)
                if stdout_path and os.path.isfile(stdout_path):
                    os.startfile(stdout_path)
                    return
                if stdout_path:
                    parent = os.path.dirname(stdout_path)
                    if os.path.isdir(parent):
                        os.startfile(parent)
                        return
        except Exception:
            return

    def append_error_details(self, error_list: list):
        """内联展示失败步骤摘要"""
        if not error_list:
            return
        # 先把缓冲区里的常规日志刷出去，保证错误摘要紧跟在最近日志后面
        self._flush_pending()
        # U-P2-3: 走主题 token，避免硬编码
        err_color = get_status_tokens(self._dark)["failure"]["fg"]
        self.log_text.append("")
        self.log_text.append(
            f'<span style="color:{err_color};font-weight:bold;">'
            f'══ {len(error_list)} 个步骤失败 ══</span>'
        )
        for item in error_list:
            name = item.get("step_name", "")
            err = item.get("error_message", "")
            self.log_text.append(
                f'<span style="color:{err_color};">  ✖ {name}: {err}</span>'
            )
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
