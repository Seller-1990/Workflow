# -*- coding: utf-8 -*-
"""DAG 可视化面板（按用途阶段分列，iOS 极简定稿对齐）

Pencil SSOT: `designs/ios_minimal_focus.pen` 的 DAG Card（QNGnx）
- 列 = 用途阶段（S1/S2…）
- 卡片 = 紧凑节点（高度 52，圆角 12，左侧状态色条 4px）
- 默认不画“依赖连线”（设计稿未展示），依赖信息放在 tooltip
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
)

from database import get_steps_by_workflow, list_stages
from ui.collapsible_section import CollapsibleSection
from ui.theme import COLORS


TYPE_COLORS = {
    "python": {"text": "#2563EB", "label": "Python"},
    "excel_powerquery": {"text": "#047857", "label": "Excel PQ"},
    "powerbi_refresh": {"text": "#B45309", "label": "Power BI"},
    "sub_workflow": {"text": "#7C3AED", "label": "子工作流"},
}


STATUS_STYLES = {
    "pending": {"strip": "#9CA3AF", "bg": "#FFFFFF"},
    "running": {"strip": "#3B82F6", "bg": "#EFF6FF"},
    "success": {"strip": "#10B981", "bg": "#FFFFFF"},
    "failure": {"strip": "#EF4444", "bg": "#FEF2F2"},
}


LANE_BGS = ["#FAFBFC", "#F8FAFC", "#F5F3FF"]


class NodeCard(QFrame):
    """一个步骤节点卡片（与 Pencil 定稿一致的紧凑外观）。"""

    activated = Signal(int)  # step_id

    def __init__(self, step_id: int, title: str, type_label: str, type_color: str, is_gate: bool):
        super().__init__()
        self._step_id = int(step_id)
        self._status = "pending"

        self.setObjectName("DagNodeCard")
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.strip = QFrame()
        self.strip.setFixedWidth(4)
        root.addWidget(self.strip)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 8)
        content_layout.setSpacing(2)
        root.addWidget(content, stretch=1)

        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.setSpacing(6)

        self.title_label = QLabel(title)
        tf = QFont(self.title_label.font())
        tf.setPointSize(12)
        tf.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(tf)
        self.title_label.setStyleSheet("color:#0F172A;")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top_l.addWidget(self.title_label, stretch=1)

        self.gate_badge = QLabel("Gate" if is_gate else "")
        self.gate_badge.setVisible(bool(is_gate))
        self.gate_badge.setStyleSheet("color:#6B7280; font-size:11px; font-weight:600;")
        top_l.addWidget(self.gate_badge, alignment=Qt.AlignRight | Qt.AlignVCenter)

        content_layout.addWidget(top)

        self.type_label = QLabel(type_label)
        self.type_label.setStyleSheet(f"color:{type_color}; font-size:11px; font-weight:600;")
        content_layout.addWidget(self.type_label)

        self.set_status("pending")

    def set_status(self, status: str):
        status = status if status in STATUS_STYLES else "pending"
        self._status = status
        st = STATUS_STYLES[status]
        self.strip.setStyleSheet(f"background:{st['strip']};")
        self.setStyleSheet(
            f"""
            QFrame#DagNodeCard {{
                background: {st['bg']};
                border-radius: 12px;
            }}
            """
        )

    def mouseDoubleClickEvent(self, event):
        try:
            self.activated.emit(self._step_id)
        finally:
            super().mouseDoubleClickEvent(event)


@dataclass(frozen=True)
class StageLike:
    uid: Optional[str]
    name: str


class DAGViewPanel(QWidget):
    """DAG 可视化面板（泳道=用途阶段列）。"""

    step_activated = Signal(int)  # step_id（用于双击定位步骤）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id: Optional[int] = None
        self._is_collapsed = False
        self._nodes: Dict[int, NodeCard] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.section = CollapsibleSection("DAG 可视化", collapsed=self._is_collapsed, header_height=44, title_font_size=15, title_weight=700)
        self.section.collapsed_changed.connect(lambda c: setattr(self, "_is_collapsed", c))
        body = self.section.body_layout

        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#6B7280; font-size:11px;")
        body.addWidget(self.hint_label)

        # Canvas（白底圆角 12）
        self.canvas = QFrame()
        self.canvas.setObjectName("DagCanvas")
        # 最小高度对齐定稿，实际高度由内容自适配（避免固定高度导致“折叠占地过大/展开看不全”）
        self.canvas.setMinimumHeight(215)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.canvas.setStyleSheet(
            f"""
            QFrame#DagCanvas {{
                background: {COLORS['background']};
                border-radius: 12px;
            }}
            """
        )
        canvas_layout = QVBoxLayout(self.canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        # 你明确希望看到“左右滑块”用于查看后续阶段：水平滚动条常驻
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        canvas_layout.addWidget(self.scroll)

        self.lanes_widget = QWidget()
        self.lanes_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.lanes_layout = QHBoxLayout(self.lanes_widget)
        self.lanes_layout.setContentsMargins(10, 0, 10, 0)
        self.lanes_layout.setSpacing(10)
        self.scroll.setWidget(self.lanes_widget)

        body.addWidget(self.canvas)
        layout.addWidget(self.section)

    def update_dag(self, workflow_id: int):
        self._workflow_id = int(workflow_id) if workflow_id is not None else None
        self._nodes.clear()
        self.hint_label.setVisible(False)
        self.hint_label.setText("")

        # 清空 lanes
        while self.lanes_layout.count():
            item = self.lanes_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._workflow_id:
            return

        steps = get_steps_by_workflow(self._workflow_id)
        if not steps:
            return

        # stages（严格按用途阶段排序）
        stages = list_stages(self._workflow_id)
        stage_ordered: List[StageLike] = [StageLike(uid=s.uid, name=s.name) for s in stages]

        # 未归类兜底
        known = {s.uid for s in stages}
        has_unassigned = any(getattr(s, "stage_uid", None) not in known for s in steps)
        if has_unassigned:
            stage_ordered.append(StageLike(uid=None, name="未归类"))

        # group steps by stage
        stage_uid_to_steps: Dict[Optional[str], List] = {st.uid: [] for st in stage_ordered}
        for s in sorted(steps, key=lambda x: x.order):
            suid = getattr(s, "stage_uid", None)
            if suid not in stage_uid_to_steps:
                suid = None
            stage_uid_to_steps.setdefault(suid, []).append(s)

        # 自适配高度：按“最长阶段”的步骤数量计算画布最小高度
        try:
            max_steps = max((len(v) for v in stage_uid_to_steps.values()), default=0)
        except Exception:
            max_steps = 0
        card_h = 52
        gap = 8
        body_padding = 12 * 2
        hdr_h = 28
        content_h = hdr_h + body_padding + (max_steps * card_h) + (max(0, max_steps - 1) * gap)
        self.canvas.setMinimumHeight(max(215, content_h + 24))

        # no explicit deps hint
        has_deps = any(bool(s.get_depends_on()) for s in steps)
        if not has_deps:
            self.hint_label.setText("无显式依赖：按用途阶段顺序执行")
            self.hint_label.setVisible(True)

        for idx, st in enumerate(stage_ordered, start=1):
            lane = QFrame()
            lane.setFixedWidth(180)
            lane.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            lane.setStyleSheet(f"background:{LANE_BGS[(idx - 1) % len(LANE_BGS)]};")

            lane_layout = QVBoxLayout(lane)
            lane_layout.setContentsMargins(0, 0, 0, 0)
            lane_layout.setSpacing(0)

            hdr = QFrame()
            hdr.setFixedHeight(28)
            hdr.setStyleSheet("background:#F3F4F6;")
            hdr_l = QHBoxLayout(hdr)
            hdr_l.setContentsMargins(12, 0, 12, 0)
            hdr_l.setSpacing(6)
            count = len(stage_uid_to_steps.get(st.uid, []))
            hdr_text = QLabel(f"S{idx} {st.name} · {count}步")
            hdr_text.setStyleSheet("color:#6B7280; font-size:11px; font-weight:600;")
            hdr_l.addWidget(hdr_text)
            lane_layout.addWidget(hdr)

            body_w = QWidget()
            body_l = QVBoxLayout(body_w)
            body_l.setContentsMargins(12, 12, 12, 12)
            body_l.setSpacing(8)
            lane_layout.addWidget(body_w, stretch=1)

            # 垂直居中：步骤较少时上下留白均分（更接近定稿示意）
            body_l.addStretch(1)
            for s in stage_uid_to_steps.get(st.uid, []):
                t = TYPE_COLORS.get(s.step_type, TYPE_COLORS["python"])
                title = f"{s.order + 1}. {s.name}"
                card = NodeCard(s.id, title, t["label"], t["text"], bool(getattr(s, "is_gate", False)))
                card.activated.connect(self.step_activated.emit)
                # tooltip：依赖摘要
                deps = list(s.get_depends_on() or [])
                tip = [title, f"类型: {t['label']}"]
                if deps:
                    tip.append("依赖: " + "、".join(deps[:4]) + ("…" if len(deps) > 4 else ""))
                card.setToolTip("\n".join(tip))
                body_l.addWidget(card)
                self._nodes[s.id] = card

            body_l.addStretch(1)
            self.lanes_layout.addWidget(lane)

        # 确保水平滚动条生效：为 lanes_widget 设置明确的最小宽度（lane 固定宽度 + spacing + margins）
        lane_w = 180
        spacing = 10
        margins_lr = 20  # lanes_layout 左右 10 + 10
        total_w = margins_lr + (len(stage_ordered) * lane_w) + (max(0, len(stage_ordered) - 1) * spacing)
        self.lanes_widget.setMinimumWidth(total_w)

        # 注意：不要 addStretch()，否则内容会被拉伸到 viewport 宽度，水平滚动条不会出现

    def update_step_status(self, step_id: int, status: str):
        node = self._nodes.get(int(step_id)) if step_id else None
        if node:
            node.set_status(status)

    def reset_all_status(self):
        for node in self._nodes.values():
            node.set_status("pending")

    def clear(self):
        self._workflow_id = None
        self._nodes.clear()
        while self.lanes_layout.count():
            item = self.lanes_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
