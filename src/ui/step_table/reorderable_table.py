# -*- coding: utf-8 -*-
"""步骤列表表格面板"""

import json
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMenu, QMessageBox, QGroupBox,
    QCheckBox, QComboBox, QAbstractItemView, QLabel, QInputDialog,
    QToolButton, QStyle, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot, QRectF, QSize, QSettings, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush

from config import StepType, APP_NAME
from database import (
    get_steps_by_workflow,
    create_step,
    delete_step,
    update_step,
    reorder_steps,
    list_workflows,
    copy_step,
    list_stages,
    create_stage,
    update_stage,
    delete_stage,
    get_stage_order_map,
    get_workflow_by_id,
    get_session,
)
from ui.theme import CORNER_RADIUS, get_colors
from ui.collapsible_section import CollapsibleSection


class ReorderableTable(QTableWidget):
    """支持拖拽排序的 QTableWidget 子类

    说明：
    - 不使用 Qt 的 InternalMove（QTableWidget + setCellWidget 容易触发 invalid index 警告）
    - 采用"自定义拖拽手势识别 → 计算 from/to → 上层落库并 reload"
    """
    rows_dragged = Signal(int, int)  # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._drag_from_row = -1
        self._drop_indicator_row = -1   # U-P1-6: 自绘插入指示线
        self._group_ranges: list[dict] = []
        self._hover_group_index: int | None = None
        # U-P1-6: 鼠标移动到第 0 列时切换手势光标
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        """U-P1-6：鼠标在第 0 列（顺序列）上时显示拖拽光标，提示该列可拖拽"""
        try:
            point = event.position().toPoint()
        except Exception:
            point = event.pos()
        col = self.columnAt(point.x())
        row = self.rowAt(point.y())
        if col == 0 and row >= 0 and self.dragEnabled():
            item = self.item(row, 0)
            if item and item.data(Qt.UserRole):
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def set_group_ranges(self, ranges: list[dict]):
        """设置用途阶段分组范围（用于绘制"框住阶段"的卡片视觉）"""
        self._group_ranges = ranges or []
        self._hover_group_index = None
        self.viewport().update()

    def refresh_theme(self, dark: bool):
        self._dark = dark
        self.viewport().update()

    def _notify_status(self, message: str):
        try:
            win = self.window()
            if win and hasattr(win, "statusBar"):
                sb = win.statusBar()
                if sb:
                    sb.showMessage(message, 5000)
        except Exception:
            return

    def startDrag(self, supportedActions):
        # 任务9：多选时禁用拖拽，避免多选+拖拽语义混乱
        if len(self.selectedItems()) > 1:
            self._notify_status("拖拽：多选时不支持拖拽，请单选后拖拽。")
            return
        self._drag_from_row = self.currentRow()
        if self._drag_from_row < 0:
            return
        item = self.item(self._drag_from_row, 0)
        if not item or not item.data(Qt.UserRole):
            self._notify_status("拖拽：请拖拽具体步骤行（阶段标题不可拖拽）。")
            return
        super().startDrag(supportedActions)

    def dropEvent(self, event):
        if self.dragDropMode() == QAbstractItemView.NoDragDrop or not self.dragEnabled():
            event.ignore()
            return

        from_row = self._drag_from_row
        if from_row is None or from_row < 0:
            event.ignore()
            return

        try:
            try:
                point = event.position().toPoint()
            except Exception:
                point = event.pos()

            to_row = self.indexAt(point).row()
            if to_row < 0:
                to_row = max(0, self.rowCount() - 1)

            event.acceptProposedAction()
            self._hover_group_index = None
            self._drop_indicator_row = -1
            self.viewport().update()
            self.rows_dragged.emit(from_row, to_row)
        finally:
            # M10 修复：dropEvent 后状态机闭合，避免下次外部拖入仍用上次值
            self._drag_from_row = -1
            self._drop_indicator_row = -1

    def dragMoveEvent(self, event):
        # 拖拽过程中高亮"目标用途阶段" + 自绘插入指示线（U-P1-6）
        try:
            point = event.position().toPoint()
        except Exception:
            point = event.pos()

        row = self.indexAt(point).row()
        hover = None
        if row >= 0:
            for i, r in enumerate(self._group_ranges):
                if int(r["start"]) <= row <= int(r["end"]):
                    hover = i
                    break

        changed = (hover != self._hover_group_index) or (row != self._drop_indicator_row)
        self._hover_group_index = hover
        self._drop_indicator_row = row if row >= 0 else -1
        if changed:
            self.viewport().update()

        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._drop_indicator_row = -1
        self.viewport().update()
        super().dragLeaveEvent(event)

    def leaveEvent(self, event):
        if self._hover_group_index is not None:
            self._hover_group_index = None
            self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        # 重要：避免在 QPainter 活跃时调用 super().paintEvent（可能导致 Qt 内部嵌套绘制崩溃）
        margin_x = 10
        margin_y = 6
        radius = CORNER_RADIUS["large"]
        colors = get_colors(self._dark)
        fill = QColor(colors["surface"])
        viewport_rect = self.viewport().rect()

        # 1) 先画背景（基底 + 卡片填充）
        painter_bg = QPainter(self.viewport())
        painter_bg.setRenderHint(QPainter.Antialiasing)
        painter_bg.fillRect(viewport_rect, QColor(colors["background"]))

        for i, r in enumerate(self._group_ranges):
            start = int(r["start"])
            end = int(r["end"])
            if start < 0 or end < 0 or start >= self.rowCount() or end >= self.rowCount():
                continue
            top_rect = self.visualRect(self.model().index(start, 0))
            bottom_rect = self.visualRect(self.model().index(end, 0))
            if top_rect.isNull() and bottom_rect.isNull():
                continue
            top = top_rect.top() if not top_rect.isNull() else bottom_rect.top()
            bottom = bottom_rect.bottom() if not bottom_rect.isNull() else top_rect.bottom()
            y = max(0, int(top + margin_y))
            h = int(max(0, (bottom - top) - margin_y * 2))
            if h < 10:
                continue
            rect = QRectF(margin_x, y, viewport_rect.width() - margin_x * 2, h)
            painter_bg.setPen(Qt.NoPen)
            painter_bg.setBrush(QBrush(fill))
            painter_bg.drawRoundedRect(rect, radius, radius)

        # V9.2：行交叉色——在卡片范围内对奇数行画半透明提亮，增强行间区分
        # 深色用 surface_secondary（更亮），浅色用 surface_card（白色提亮）
        alt_base = colors["surface_secondary"] if self._dark else colors["surface_card"]
        alt = QColor(alt_base)
        alt.setAlpha(150 if self._dark else 110)
        for i, r in enumerate(self._group_ranges):
            start = int(r["start"])
            end = int(r["end"])
            if start < 0 or end < 0 or start >= self.rowCount() or end >= self.rowCount():
                continue
            for row in range(start, end + 1):
                if (row - start) % 2 == 0:
                    continue
                row_rect = self.visualRect(self.model().index(row, 0))
                if row_rect.isNull():
                    continue
                band = QRectF(margin_x, row_rect.top() + 1, viewport_rect.width() - margin_x * 2, row_rect.height() - 2)
                painter_bg.setBrush(QBrush(alt))
                painter_bg.setPen(Qt.NoPen)
                painter_bg.drawRect(band)

        painter_bg.end()

        # 2) 让 Qt 绘制表格内容（文字、控件等）
        super().paintEvent(event)

        # 3) 再画边框/高亮（前景）
        painter_fg = QPainter(self.viewport())
        painter_fg.setRenderHint(QPainter.Antialiasing)
        border = QPen(QColor(colors["border"]), 1)
        border_hover = QPen(QColor(colors["primary"]), 2)

        for i, r in enumerate(self._group_ranges):
            start = int(r["start"])
            end = int(r["end"])
            if start < 0 or end < 0 or start >= self.rowCount() or end >= self.rowCount():
                continue
            top_rect = self.visualRect(self.model().index(start, 0))
            bottom_rect = self.visualRect(self.model().index(end, 0))
            if top_rect.isNull() and bottom_rect.isNull():
                continue
            top = top_rect.top() if not top_rect.isNull() else bottom_rect.top()
            bottom = bottom_rect.bottom() if not bottom_rect.isNull() else top_rect.bottom()
            y = max(0, int(top + margin_y))
            h = int(max(0, (bottom - top) - margin_y * 2))
            if h < 10:
                continue
            rect = QRectF(margin_x, y, viewport_rect.width() - margin_x * 2, h)
            painter_fg.setBrush(Qt.NoBrush)
            painter_fg.setPen(border_hover if self._hover_group_index == i else border)
            painter_fg.drawRoundedRect(rect, radius, radius)

        painter_fg.end()

        # 4) U-P1-6：自绘拖拽插入指示线（2px 蓝色）
        if self._drop_indicator_row >= 0:
            painter_ind = QPainter(self.viewport())
            painter_ind.setRenderHint(QPainter.Antialiasing)
            target_rect = self.visualRect(self.model().index(self._drop_indicator_row, 0))
            if not target_rect.isNull():
                y = target_rect.top()
                pen = QPen(QColor(colors["primary"]), 2)
                painter_ind.setPen(pen)
                painter_ind.drawLine(margin_x, y, viewport_rect.width() - margin_x, y)
            painter_ind.end()
