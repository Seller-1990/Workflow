# -*- coding: utf-8 -*-
"""运行历史面板（增强版：筛选/搜索/触发原因/耗时可视化）"""

import logging
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QMessageBox, QComboBox, QLineEdit, QLabel,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor

from database import (
    get_run_histories_by_workflow, clear_run_histories, get_step_log_summary_by_runs
)
from ui.collapsible_section import CollapsibleSection
from ui.theme import (
    COLORS,
    get_colors,
    get_status_tokens,
    get_duration_tokens,
    get_menu_stylesheet,
    msg_question,
)

logger = logging.getLogger(__name__)


class RunHistoryPanel(QWidget):
    """运行历史面板（增强版）"""

    open_failures_requested = Signal(int)  # run_history_id
    force_stop_requested = Signal(int)        # run_history_id

    # 列定义（新增：触发原因）
    COLUMNS = [
        ("运行编号", 90),
        ("状态", 55),
        ("触发原因", 70),
        ("开始时间", 125),
        ("耗时", 60),
    ]

    # 原因映射
    REASON_MAP = {
        "manual": "手动",
        "watch": "监听",
        "sub_workflow": "子流程",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._all_histories = []
        self._history_step_summary = {}
        self._status_filter = "all"
        self._search_text = ""
        self._dark = False
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        self.section = CollapsibleSection(
            "运行历史", collapsed=False, header_height=44,
            title_font_size=15, title_weight=700
        )
        self.section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        group_layout = self.section.body_layout

        # 筛选行：状态下拉 + 搜索框
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("筛选:"))

        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["全部", "成功", "失败", "运行中", "已取消"])
        self.cmb_status.setFixedWidth(75)
        self.cmb_status.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {COLORS["border"]}; border-radius: 6px;
                padding: 3px 6px; background: {COLORS["background"]};
            }}
        """)
        self.cmb_status.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.cmb_status)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("搜索运行编号…")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setFixedWidth(140)
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COLORS["border"]}; border-radius: 6px;
                padding: 3px 8px; background: {COLORS["background"]};
            }}
        """)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._on_search_timeout)
        self.txt_search.textChanged.connect(lambda: self._search_timer.start(300))
        filter_row.addWidget(self.txt_search)

        filter_row.addStretch()
        group_layout.addLayout(filter_row)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setFixedHeight(30)
        self.table.horizontalHeader().setStretchLastSection(False)

        self.table.setStyleSheet("""
            QTableWidget {
                background: #FFFFFF;
                border: none;
                border-radius: 12px;
            }
            QHeaderView::section {
                background: #FAFBFC;
                border: none;
                padding: 6px 8px;
                color: #6B7280;
                font-size: 11px;
                font-weight: 600;
            }
            QTableWidget::item { padding: 6px 8px; }
        """)

        for i, (_, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)

        self.table.horizontalHeader().setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Stretch)

        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        group_layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.section, stretch=1)

    def load_history(self, workflow_id: int):
        """加载运行历史"""
        self._workflow_id = workflow_id
        self._all_histories = get_run_histories_by_workflow(workflow_id, limit=100)
        # 安全地提取history ID，确保所有ID都是有效的整数
        history_ids = []
        for h in self._all_histories:
            hid = getattr(h, "id", None)
            if hid is not None:
                try:
                    history_ids.append(int(hid))
                except (ValueError, TypeError):
                    pass
        if history_ids:
            try:
                self._history_step_summary = get_step_log_summary_by_runs(history_ids)
            except Exception:
                logger.exception("加载运行历史统计失败: workflow_id=%s", workflow_id)
                self._history_step_summary = {}
        else:
            self._history_step_summary = {}
        self._apply_filter()

    def _on_filter_changed(self):
        """状态筛选变更"""
        idx = self.cmb_status.currentIndex()
        self._status_filter = ["all", "success", "failure", "running", "cancelled"][idx]
        self._apply_filter()

    def _on_search_timeout(self):
        """搜索文本变更（防抖）"""
        self._search_text = self.txt_search.text().strip()
        self._apply_filter()

    def _apply_filter(self):
        """应用筛选条件并刷新表格"""
        filtered = self._all_histories

        # 状态筛选
        if self._status_filter != "all":
            filtered = [h for h in filtered if h.status == self._status_filter]

        # 搜索（运行编号包含搜索文本）
        if self._search_text:
            filtered = [h for h in filtered if self._search_text.lower() in (h.run_id or "").lower()]

        self._render_table(filtered)

    def _render_table(self, histories):
        """渲染表格"""
        self.table.setRowCount(0)
        try:
            self.table.clearSpans()
        except Exception:
            pass
        # R2-#7: 空状态占位
        if not histories:
            self.table.setRowCount(1)
            if self._workflow_id is None:
                msg = "请先选择一个工作流"
            elif self._search_text or self._status_filter != "all":
                msg = "无匹配的运行记录"
            else:
                msg = "暂无运行历史，运行一次工作流后会出现在这里"
            placeholder = QTableWidgetItem(msg)
            placeholder.setTextAlignment(Qt.AlignCenter)
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setForeground(QColor(get_colors(self._dark)["text_tertiary"]))
            self.table.setItem(0, 0, placeholder)
            try:
                self.table.setSpan(0, 0, 1, len(self.COLUMNS))
            except Exception:
                pass
            return
        self.table.setRowCount(len(histories))

        for row, history in enumerate(histories):
            counts = self._history_step_summary.get(int(history.id), {})
            # 行背景色
            status_tokens = get_status_tokens(self._dark).get(history.status, get_status_tokens(self._dark)["pending"])
            row_bg = QColor(status_tokens["bg"])

            # 运行编号
            run_item = QTableWidgetItem(history.run_id)
            run_item.setData(Qt.UserRole, history.id)
            run_item.setData(Qt.UserRole + 1, history.log_dir)
            run_item.setData(Qt.UserRole + 2, history.status)
            if row_bg:
                run_item.setBackground(row_bg)
            self.table.setItem(row, 0, run_item)

            # 状态
            status_map = {
                "success": "成功", "failure": "失败",
                "running": "运行中", "cancelled": "已取消", "pending": "等待",
            }
            status_text = status_map.get(history.status, history.status)
            # ROI-1: 通知结果标记（sent → 📨✓；failed → 📨✗ 并在 tooltip 展示全文；
            # skipped / 未回写 → 不显示）。旧记录可能没有 notify_status 字段，用 getattr 兜底。
            notify_status = str(getattr(history, "notify_status", None) or "")
            notify_tooltip = ""
            if notify_status == "sent":
                status_text = f"{status_text} 📨✓"
            elif notify_status.startswith("failed"):
                status_text = f"{status_text} 📨✗"
                notify_tooltip = notify_status
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor(status_tokens["fg"]))
            if notify_tooltip:
                status_item.setToolTip(notify_tooltip)
            if row_bg:
                status_item.setBackground(row_bg)
            self.table.setItem(row, 1, status_item)

            # 触发原因
            reason_text = self.REASON_MAP.get(history.reason, history.reason or "")
            reason_item = QTableWidgetItem(reason_text)
            reason_item.setTextAlignment(Qt.AlignCenter)
            if row_bg:
                reason_item.setBackground(row_bg)
            self.table.setItem(row, 2, reason_item)

            # 开始时间
            start_text = ""
            if history.start_time:
                start_text = history.start_time.strftime("%m-%d %H:%M:%S")
            start_item = QTableWidgetItem(start_text)
            if row_bg:
                start_item.setBackground(row_bg)
            self.table.setItem(row, 3, start_item)

            # 耗时（带颜色分级）
            duration_text = ""
            duration_color = None
            duration_tokens = get_duration_tokens(self._dark)
            if history.duration_seconds is not None:
                ds = history.duration_seconds
                if ds < 60:
                    duration_text = f"{ds:.0f}s"
                elif ds < 3600:
                    minutes = int(ds // 60)
                    seconds = int(ds % 60)
                    duration_text = f"{minutes}m{seconds:02d}s"
                else:
                    hours = int(ds // 3600)
                    minutes = int((ds % 3600) // 60)
                    duration_text = f"{hours}h{minutes:02d}m"

                # 颜色分级：快(绿) / 中(黄) / 慢(红)
                if ds < 30:
                    duration_color = QColor(duration_tokens["fast"])
                elif ds < 300:
                    duration_color = QColor(duration_tokens["medium"])
                else:
                    duration_color = QColor(duration_tokens["slow"])

            duration_item = QTableWidgetItem(duration_text)
            duration_item.setTextAlignment(Qt.AlignCenter)
            if duration_color:
                duration_item.setForeground(duration_color)
            if row_bg:
                duration_item.setBackground(row_bg)
            self.table.setItem(row, 4, duration_item)

            # 步骤统计 tooltip
            summary_parts = [
                f"成功{int(counts.get('success', 0))}",
                f"失败{int(counts.get('failure', 0))}",
                f"跳过{int(counts.get('skipped', 0))}",
            ]
            cancelled_count = int(counts.get('cancelled', 0))
            if cancelled_count:
                summary_parts.append(f"取消{cancelled_count}")
            run_item.setToolTip(f"步骤: {' '.join(summary_parts)}")

    def clear(self):
        """清空"""
        self._workflow_id = None
        self._all_histories = []
        self._history_step_summary = {}
        self.table.setRowCount(0)
        try:
            self.table.clearSpans()
        except Exception:
            pass

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.table.itemAt(pos)
        if not item:
            return

        row = self.table.row(item)
        run_item = self.table.item(row, 0)
        if not run_item:
            return

        history_id = run_item.data(Qt.UserRole)
        log_dir = run_item.data(Qt.UserRole + 1)
        history_status = run_item.data(Qt.UserRole + 2) or ""

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))
        action_failures = menu.addAction("查看失败步骤")
        summary = self._history_step_summary.get(int(history_id), {}) if history_id else {}
        has_failures = int(summary.get("failure", 0)) > 0
        action_failures.setEnabled(bool(history_id) and has_failures)
        action_failures.triggered.connect(
            lambda: self.open_failures_requested.emit(int(history_id))
        )

        # 强制停止（仅对运行中的任务显示）
        if history_status == "running":
            menu.addSeparator()
            action_force_stop = menu.addAction("⚠ 强制停止")
            action_force_stop.triggered.connect(
                lambda: self.force_stop_requested.emit(int(history_id))
            )

        menu.addSeparator()

        # 打开日志目录
        action_open_log = menu.addAction("打开日志目录")
        action_open_log.setEnabled(bool(log_dir) and os.path.isdir(str(log_dir)))
        action_open_log.triggered.connect(lambda: self._open_log_dir(str(log_dir)))

        # 清除历史
        menu.addSeparator()
        action_clear = menu.addAction("清除所有历史")
        action_clear.triggered.connect(self._clear_history)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_log_dir(self, log_dir: str):
        """打开日志目录"""
        os.startfile(log_dir)

    def _on_row_double_clicked(self, row: int, col: int):
        """双击行打开日志目录"""
        run_item = self.table.item(row, 0)
        if run_item:
            log_dir = run_item.data(Qt.UserRole + 1)
            if log_dir and os.path.isdir(str(log_dir)):
                os.startfile(str(log_dir))

    def _clear_history(self):
        """清除运行历史"""
        if not self._workflow_id:
            return
        reply = msg_question(self, self._dark, "确认", "确定要清除所有运行历史吗？")
        if reply == QMessageBox.Yes:
            clear_run_histories(self._workflow_id)
            self.load_history(self._workflow_id)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.section.refresh_theme(dark)
        table_bg = colors['background']
        header_bg = '#2C2C2E' if dark else '#FAFBFC'
        header_color = '#AAAAAA' if dark else '#6B7280'
        self.cmb_status.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {colors['border']}; border-radius: 6px;
                padding: 3px 6px; background: {colors['background']};
            }}
        """)
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {colors['border']}; border-radius: 6px;
                padding: 3px 8px; background: {colors['background']};
            }}
        """)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: {table_bg};
                border: none;
                border-radius: 12px;
            }}
            QHeaderView::section {{
                background: {header_bg};
                border: none;
                padding: 6px 8px;
                color: {header_color};
                font-size: 11px;
                font-weight: 600;
            }}
            QTableWidget::item {{ padding: 6px 8px; color: {colors['text_primary']}; }}
        """)
        if self._workflow_id is not None:
            self._apply_filter()
