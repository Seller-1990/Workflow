# -*- coding: utf-8 -*-
"""DAG 可视化面板（按用途阶段分列，iOS 极简定稿对齐）

Pencil SSOT: `designs/ios_minimal_focus.pen` 的 DAG Card（QNGnx）
- 列 = 用途阶段（S1/S2…）
- 卡片 = 紧凑节点（高度 52，圆角 12，左侧状态色条 4px）
- 默认不画「依赖连线」（设计稿未展示），依赖信息放在 tooltip
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
from duration_utils import format_duration_short
from executors import get_type_label
from ui.collapsible_section import CollapsibleSection
from ui.theme import COLORS, get_colors, get_status_tokens, get_type_tokens, get_duration_tokens


# V9.2：lane 背景色从 stage_band_palette 取（原硬编码 #F5F3FF/#2C2C2E/#3A3A3C/#2A2430）
LANE_BGS = list(COLORS["stage_band_palette"])
DARK_LANE_BGS = list(get_colors(True)["stage_band_palette"])


class NodeCard(QFrame):
    """一个步骤节点卡片（与 Pencil 定稿一致的紧凑外观）。"""

    activated = Signal(int)  # step_id

    def __init__(self, step_id: int, title: str, step_type: str, type_color: str, is_gate: bool, dep_count: int = 0, dep_names: list = None, stage_name: str = "", dark: bool = False):
        super().__init__()
        self._step_id = int(step_id)
        self._step_type = step_type
        self._status = "pending"
        self._dark = dark
        self._is_gate = bool(is_gate)
        self._type_color = type_color
        self._duration_seconds: Optional[float] = None

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

        colors = get_colors(dark)
        self.title_label = QLabel(title)
        tf = QFont(self.title_label.font())
        tf.setPointSize(12)
        tf.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(tf)
        self.title_label.setStyleSheet(f"color:{colors['text_primary']};")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top_l.addWidget(self.title_label, stretch=1)

        self.duration_badge = QLabel("")
        self.duration_badge.setVisible(False)
        top_l.addWidget(self.duration_badge, alignment=Qt.AlignRight | Qt.AlignVCenter)

        content_layout.addWidget(top)

        type_label_text = get_type_label(step_type)
        self._type_label_text = type_label_text
        self._dep_count = dep_count
        self.type_label = QLabel("")
        content_layout.addWidget(self.type_label)

        dep_names = dep_names or []
        tip_lines = [title, f"类型: {type_label_text}"]
        if stage_name:
            tip_lines.append(f"阶段: {stage_name}")
        if dep_names:
            dep_text = "、".join(dep_names[:6])
            if len(dep_names) > 6:
                dep_text += f"… 等{len(dep_names)}项"
            tip_lines.append(f"依赖: {dep_text}")
        self.setToolTip("\n".join(tip_lines))

        self._refresh_type_label()
        self._refresh_duration_badge()
        self.set_status("pending")

    def set_status(self, status: str):
        tokens = get_status_tokens(self._dark)
        status = status if status in tokens else "pending"
        self._status = status
        st = tokens[status]
        self.strip.setStyleSheet(f"background:{st['strip']};")
        self.setStyleSheet(
            f"""
            QFrame#DagNodeCard {{
                background: {st['bg']};
                border-radius: 12px;
            }}
            """
        )

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.title_label.setStyleSheet(f"color:{colors['text_primary']};")
        type_tokens = get_type_tokens(dark)
        t = type_tokens.get(self._step_type, next(iter(type_tokens.values())))
        self._type_color = t["fg"]
        self._refresh_type_label()
        self._refresh_duration_badge()
        self.set_status(self._status)

    def set_duration_seconds(self, duration_seconds: Optional[float]):
        self._duration_seconds = duration_seconds
        self._refresh_duration_badge()

    def _refresh_type_label(self):
        parts = [self._type_label_text]
        if self._is_gate:
            parts.append("检查点")
        if self._dep_count > 0:
            parts.append(f"{self._dep_count} 个依赖")
        self.type_label.setText(" · ".join(parts))
        self.type_label.setStyleSheet(f"color:{self._type_color}; font-size:11px; font-weight:600;")

    def _refresh_duration_badge(self):
        colors = get_colors(self._dark)
        duration_text = format_duration_short(self._duration_seconds)
        visible = bool(duration_text)
        self.duration_badge.setVisible(visible)
        if not visible:
            self.duration_badge.setText("")
            return

        duration_tokens = get_duration_tokens(self._dark)
        ds = max(0.0, float(self._duration_seconds or 0.0))
        if ds < 30:
            fg = duration_tokens["fast"]
        elif ds < 300:
            fg = duration_tokens["medium"]
        else:
            fg = duration_tokens["slow"]
        self.duration_badge.setText(duration_text)
        self.duration_badge.setStyleSheet(
            f"color:{fg}; background:{colors['surface_card']}; font-size:11px; font-weight:700; padding:0 4px; border-radius:6px;"
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
        self._dark = False
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
        # V9.2：hint_label 从主题模板取色（原硬编码 #6B7280）
        self.hint_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        body.addWidget(self.hint_label)

        self.canvas = QFrame()
        self.canvas.setObjectName("DagCanvas")
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

        # R2-#9: 大工作流时禁用绘制更新，重建完成后再统一刷新，避免逐 widget 重绘
        try:
            self.lanes_widget.setUpdatesEnabled(False)
        except Exception:
            pass

        while self.lanes_layout.count():
            item = self.lanes_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._workflow_id:
            self.hint_label.setText("请选择一个工作流")
            self.hint_label.setVisible(True)
            try:
                self.lanes_widget.setUpdatesEnabled(True)
            except Exception:
                pass
            return

        steps = get_steps_by_workflow(self._workflow_id)
        if not steps:
            self.hint_label.setText("暂无步骤，请在下方步骤列表中添加")
            self.hint_label.setVisible(True)
            try:
                self.lanes_widget.setUpdatesEnabled(True)
            except Exception:
                pass
            return

        stages = list_stages(self._workflow_id)
        stage_ordered: List[StageLike] = [StageLike(uid=s.uid, name=s.name) for s in stages]

        known = {s.uid for s in stages}
        has_unassigned = any(getattr(s, "stage_uid", None) not in known for s in steps)
        if has_unassigned:
            stage_ordered.append(StageLike(uid=None, name="未归类"))

        stage_uid_to_steps: Dict[Optional[str], List] = {st.uid: [] for st in stage_ordered}
        for s in sorted(steps, key=lambda x: x.order):
            suid = getattr(s, "stage_uid", None)
            if suid not in stage_uid_to_steps:
                suid = None
            stage_uid_to_steps.setdefault(suid, []).append(s)

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

        has_deps = any(bool(s.get_depends_on()) for s in steps)
        if not has_deps:
            self.hint_label.setText("无显式依赖：按用途阶段顺序执行")
            self.hint_label.setVisible(True)

        uid_to_name = {s.uid: s.name for s in steps}

        # U-P3-8: 自适应阶段宽度——视口宽度足够容纳全部阶段时按可用宽度等分，
        # 否则降为最小 160px 以减少水平滚动。最大维持 200px 保留视觉留白。
        spacing = 10
        margins_lr = 20
        min_lane_w = 160
        max_lane_w = 200
        try:
            viewport_w = max(0, int(self.canvas.parent().width()) if self.canvas.parent() else 0)
        except Exception:
            viewport_w = 0
        n = max(1, len(stage_ordered))
        usable = max(0, viewport_w - margins_lr - (n - 1) * spacing)
        lane_w = max(min_lane_w, min(max_lane_w, usable // n if usable else min_lane_w))

        # R2-#9: 预计算循环不变量，避免每个 lane / card 重复查找
        # V9.2：hdr_bg/hdr_text_color 从主题模板取（原硬编码 #2C2C2E/#F3F4F6/#AEAEB2/#6B7280）
        _c = get_colors(self._dark)
        lane_bgs = DARK_LANE_BGS if self._dark else LANE_BGS
        lane_bg_count = len(lane_bgs)
        hdr_bg = _c["surface_header"]
        hdr_text_color = _c["text_secondary"]
        hdr_text_style = f"color:{hdr_text_color}; font-size:11px; font-weight:600;"
        type_colors_map = get_type_tokens(self._dark)
        default_type = type_colors_map["python"]

        for idx, st in enumerate(stage_ordered, start=1):
            lane = QFrame()
            lane.setFixedWidth(lane_w)
            lane.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            lane.setStyleSheet(f"background:{lane_bgs[(idx - 1) % lane_bg_count]};")

            lane_layout = QVBoxLayout(lane)
            lane_layout.setContentsMargins(0, 0, 0, 0)
            lane_layout.setSpacing(0)

            hdr = QFrame()
            hdr.setFixedHeight(28)
            hdr.setStyleSheet(f"background:{hdr_bg};")
            hdr_l = QHBoxLayout(hdr)
            hdr_l.setContentsMargins(12, 0, 12, 0)
            hdr_l.setSpacing(6)
            stage_steps = stage_uid_to_steps.get(st.uid, [])
            count = len(stage_steps)
            hdr_text = QLabel(f"S{idx} {st.name} · {count}步")
            hdr_text.setStyleSheet(hdr_text_style)
            hdr_l.addWidget(hdr_text)
            lane_layout.addWidget(hdr)

            body_w = QWidget()
            body_l = QVBoxLayout(body_w)
            body_l.setContentsMargins(12, 12, 12, 12)
            body_l.setSpacing(8)
            lane_layout.addWidget(body_w, stretch=1)

            body_l.addStretch(1)
            for s in stage_steps:
                t = type_colors_map.get(s.step_type, default_type)
                title = f"{s.order + 1}. {s.name}"
                deps = list(s.get_depends_on() or [])
                dep_names = [uid_to_name.get(uid, uid) for uid in deps]
                card = NodeCard(
                    s.id, title, s.step_type, t["fg"],
                    bool(getattr(s, "is_gate", False)),
                    dep_count=len(deps),
                    dep_names=dep_names,
                    stage_name=st.name,
                    dark=self._dark,
                )
                card.activated.connect(self.step_activated.emit)
                body_l.addWidget(card)
                self._nodes[s.id] = card

            body_l.addStretch(1)
            self.lanes_layout.addWidget(lane)

        # U-P3-8: 重新计算总宽度（lane_w 已自适应）
        total_w = margins_lr + (len(stage_ordered) * lane_w) + (max(0, len(stage_ordered) - 1) * spacing)
        self.lanes_widget.setMinimumWidth(total_w)

        # R2-#9: 恢复绘制更新
        try:
            self.lanes_widget.setUpdatesEnabled(True)
        except Exception:
            pass

    def update_step_status(self, step_id: int, status: str, duration_seconds: Optional[float] = None):
        if step_id is None:
            return
        try:
            sid = int(step_id)
        except (ValueError, TypeError):
            return
        node = self._nodes.get(sid)
        if node:
            node.set_status(status)
            if duration_seconds is not None or status == "running":
                node.set_duration_seconds(None if status == "running" else duration_seconds)

    def reset_all_status(self):
        for node in self._nodes.values():
            node.set_status("pending")
            node.set_duration_seconds(None)

    def clear(self):
        self._workflow_id = None
        self._nodes.clear()
        while self.lanes_layout.count():
            item = self.lanes_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # R2-#7: 清空后保留空状态提示
        self.hint_label.setText("请选择一个工作流")
        self.hint_label.setVisible(True)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.section.refresh_theme(dark)
        self.hint_label.setStyleSheet(f"color:{colors['text_secondary']}; font-size:11px;")
        self.canvas.setStyleSheet(
            f"""
            QFrame#DagCanvas {{
                background: {colors['background']};
                border-radius: 12px;
            }}
            """
        )
        for node in self._nodes.values():
            node.set_dark_mode(dark)
        if self._workflow_id is not None:
            self.update_dag(self._workflow_id)
