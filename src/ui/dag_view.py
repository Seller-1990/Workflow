# -*- coding: utf-8 -*-
"""DAG 可视化面板 - Style B 详细卡片样式"""

from typing import Dict, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsLineItem,
    QGroupBox, QPushButton, QHBoxLayout, QGraphicsItem
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QFont, QPainter, QPainterPath

from database import get_steps_by_workflow


# 类型配色方案
TYPE_COLORS = {
    "python": {"bg": "#EEF2FF", "text": "#4338CA", "label": "Python"},
    "excel_powerquery": {"bg": "#ECFDF5", "text": "#047857", "label": "Excel PQ"},
    "powerbi_refresh": {"bg": "#FEF3C7", "text": "#B45309", "label": "Power BI"},
    "sub_workflow": {"bg": "#F3E8FF", "text": "#7C3AED", "label": "子工作流"},
}

# 状态配色方案
STATUS_COLORS = {
    "pending": {"border": "#D1D5DB", "accent": "#9CA3AF", "bg": "#F9FAFB"},
    "running": {"border": "#3B82F6", "accent": "#3B82F6", "bg": "#EFF6FF"},
    "success": {"border": "#10B981", "accent": "#10B981", "bg": "#ECFDF5"},
    "failure": {"border": "#EF4444", "accent": "#EF4444", "bg": "#FEF2F2"},
}


class DAGNode(QGraphicsRectItem):
    """DAG 节点 - Style B 详细卡片"""
    
    def __init__(
        self, 
        step_id: int, 
        order: int, 
        name: str, 
        step_type: str = "python",
        is_gate: bool = False
    ):
        super().__init__()
        
        self.step_id = step_id
        self.order = order
        self.name = name
        self.step_type = step_type
        self.is_gate = is_gate
        self._status = "pending"
        
        # 节点大小
        self.node_width = 180
        self.node_height = 64
        self.radius = 8
        self.accent_width = 4
        
        self.setRect(0, 0, self.node_width, self.node_height)
        
        # 类型信息
        type_info = TYPE_COLORS.get(step_type, TYPE_COLORS["python"])
        self.type_label = type_info["label"]
        self.type_bg = QColor(type_info["bg"])
        self.type_text_color = QColor(type_info["text"])
        
        # 状态颜色
        self._update_colors()
        
        # 步骤名称
        self.name_text = QGraphicsTextItem(self)
        display_name = f"{order + 1}. {name}"
        if len(display_name) > 20:
            display_name = display_name[:17] + "..."
        self.name_text.setPlainText(display_name)
        self.name_text.setDefaultTextColor(QColor("#111827"))
        self.name_text.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self.name_text.setPos(self.accent_width + 10, 8)
        
        # 类型标签
        self.type_text = QGraphicsTextItem(self)
        self.type_text.setPlainText(self.type_label)
        self.type_text.setDefaultTextColor(self.type_text_color)
        self.type_text.setFont(QFont("Microsoft YaHei", 8))
        self.type_text.setPos(self.accent_width + 10, 32)
        
        # 状态图标占位
        self.status_text = QGraphicsTextItem(self)
        self.status_text.setFont(QFont("Segoe UI Symbol", 12))
        self.status_text.setPos(self.node_width - 28, 20)
        self._update_status_icon()
        
        self.setToolTip(f"步骤 {order + 1}: {name}\n类型: {self.type_label}\n状态: {self._status}")
        
        # 允许鼠标悬停效果
        self.setAcceptHoverEvents(True)
    
    def _update_colors(self):
        """更新状态颜色"""
        status_info = STATUS_COLORS.get(self._status, STATUS_COLORS["pending"])
        self.border_color = QColor(status_info["border"])
        self.accent_color = QColor(status_info["accent"])
        self.bg_color = QColor(status_info["bg"])
    
    def _update_status_icon(self):
        """更新状态图标"""
        status_info = STATUS_COLORS.get(self._status, STATUS_COLORS["pending"])
        icons = {
            "pending": ("○", "#9CA3AF"),
            "running": ("◉", "#3B82F6"),
            "success": ("✓", "#10B981"),
            "failure": ("✗", "#EF4444"),
        }
        icon, color = icons.get(self._status, icons["pending"])
        self.status_text.setPlainText(icon)
        self.status_text.setDefaultTextColor(QColor(color))
    
    def set_status(self, status: str):
        """设置状态"""
        if status not in STATUS_COLORS:
            status = "pending"
        self._status = status
        self._update_colors()
        self._update_status_icon()
        self.setToolTip(f"步骤 {self.order + 1}: {self.name}\n类型: {self.type_label}\n状态: {self._status}")
        self.update()
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        
        # 阴影
        shadow_rect = rect.adjusted(2, 2, 2, 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 15))
        painter.drawRoundedRect(shadow_rect, self.radius, self.radius)
        
        # 背景
        painter.setPen(QPen(self.border_color, 1.5))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRoundedRect(rect, self.radius, self.radius)
        
        # 左侧强调条
        accent_path = QPainterPath()
        accent_rect = QRectF(0, 0, self.accent_width, self.node_height)
        accent_path.addRoundedRect(accent_rect, self.radius, self.radius)
        # 裁剪右侧
        clip_rect = QRectF(0, 0, self.accent_width, self.node_height)
        painter.setClipRect(clip_rect)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.accent_color))
        painter.drawRoundedRect(QRectF(0, 0, self.radius * 2, self.node_height), self.radius, self.radius)
        painter.setClipping(False)
        
        # 类型标签背景
        label_rect = QRectF(self.accent_width + 8, 34, 60, 18)
        painter.setBrush(QBrush(self.type_bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(label_rect, 4, 4)
    
    def hoverEnterEvent(self, event):
        self.setOpacity(0.9)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.setOpacity(1.0)
        super().hoverLeaveEvent(event)


class DAGViewPanel(QWidget):
    """DAG 可视化面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._is_collapsed = False
        self._nodes: Dict[int, DAGNode] = {}  # step_id -> DAGNode
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        self.group = QGroupBox("DAG 可视化")
        group_layout = QVBoxLayout(self.group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 折叠按钮
        header = QHBoxLayout()
        self.btn_toggle = QPushButton("折叠")
        self.btn_toggle.setFixedWidth(60)
        self.btn_toggle.clicked.connect(self._toggle_collapse)
        header.addStretch()
        header.addWidget(self.btn_toggle)
        group_layout.addLayout(header)
        
        # 视图 - 水平滚动
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setFixedHeight(120)  # 固定高度，单行
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet("""
            QGraphicsView {
                background-color: #FAFAFA;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        """)
        group_layout.addWidget(self.view)
        
        layout.addWidget(self.group)
    
    def _toggle_collapse(self):
        """切换折叠状态"""
        self._is_collapsed = not self._is_collapsed
        self.view.setVisible(not self._is_collapsed)
        self.btn_toggle.setText("展开" if self._is_collapsed else "折叠")
    
    def update_dag(self, workflow_id: int):
        """更新 DAG"""
        self._workflow_id = workflow_id
        self.scene.clear()
        self._nodes.clear()
        
        steps = get_steps_by_workflow(workflow_id)
        if not steps:
            return
        
        # 布局参数 - 水平单行排列
        node_width = 180
        node_height = 64
        h_spacing = 40
        start_x = 20
        start_y = 15
        
        step_by_id = {s.id: s for s in steps}
        step_by_uid = {s.uid: s for s in steps}
        positions = {}
        
        # 创建节点 - 全部水平排列
        for i, step in enumerate(steps):
            x = start_x + i * (node_width + h_spacing)
            y = start_y
            
            node = DAGNode(
                step.id, 
                step.order, 
                step.name, 
                step.step_type,
                step.is_gate
            )
            node.setPos(x, y)
            self.scene.addItem(node)
            
            self._nodes[step.id] = node
            positions[step.id] = (x, y)
        
        # 绘制连线
        pen = QPen(QColor("#CBD5E1"), 2)
        pen.setStyle(Qt.SolidLine)
        
        # 优先使用依赖关系
        has_deps = any(s.get_depends_on() for s in steps)
        if has_deps:
            for step in steps:
                deps = step.get_depends_on()
                for dep_uid in deps:
                    dep_step = step_by_uid.get(dep_uid)
                    if not dep_step or dep_step.id not in positions or step.id not in positions:
                        continue
                    x1, y1 = positions[dep_step.id]
                    x2, y2 = positions[step.id]
                    self._draw_connection(x1, y1, x2, y2, node_width, node_height, pen)
        else:
            for i in range(len(steps) - 1):
                step = steps[i]
                next_step = steps[i + 1]
                if step.id in positions and next_step.id in positions:
                    x1, y1 = positions[step.id]
                    x2, y2 = positions[next_step.id]
                    self._draw_connection(x1, y1, x2, y2, node_width, node_height, pen)
        
        # 调整场景大小
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-10, -10, 10, 10))
    
    def _draw_connection(self, x1, y1, x2, y2, node_width, node_height, pen):
        """绘制连接线"""
        if y1 == y2:
            # 同行，水平连线
            line = QGraphicsLineItem(
                x1 + node_width, y1 + node_height / 2,
                x2, y2 + node_height / 2
            )
        else:
            # 不同行，垂直连线
            line = QGraphicsLineItem(
                x1 + node_width / 2, y1 + node_height,
                x2 + node_width / 2, y2
            )
        line.setPen(pen)
        self.scene.addItem(line)
    
    def update_step_status(self, step_id: int, status: str):
        """更新步骤状态"""
        if step_id in self._nodes:
            self._nodes[step_id].set_status(status)
    
    def reset_all_status(self):
        """重置所有步骤状态为 pending"""
        for node in self._nodes.values():
            node.set_status("pending")
    
    def clear(self):
        """清空"""
        self._workflow_id = None
        self._nodes.clear()
        self.scene.clear()
