# -*- coding: utf-8 -*-
"""工作台式阶段编排面板。"""

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from database import get_stage_order_map, get_steps_by_workflow, get_workflow_by_id, list_stages
from duration_utils import format_duration_short
from engine import WorkflowEngine
from ui.workbench_board_styles import board_tokens, build_board_stylesheet
from ui.workbench_board_constants import (
    COMPLETED_STATUSES,
    MIME_STEP_ID,
    QT_MAX_WIDGET_SIZE,
    RESPONSIVE_WIDTH_BREAKPOINT,
    STAGE_LANE_BORDER_HEIGHT,
    STAGE_LANE_COMPACT_WIDTH,
    STAGE_LANE_GAP,
    STAGE_LANE_MIN_HEIGHT,
    STAGE_LANE_MIN_WIDTH,
    STATUS_LABELS,
    TYPE_CLASSES,
    TYPE_LABELS,
)


class StepCard(QFrame):
    """可点击、可拖拽的步骤卡片。"""

    selected = Signal(int)
    ICON_SIZE_PX = 18

    def __init__(self, step, order_label: str, dep_text: str, parent=None):
        super().__init__(parent)
        self.step_id = int(step.id)
        self.stage_uid = getattr(step, "stage_uid", "") or ""
        self._press_pos = QPoint()
        self._status = "idle"
        self._duration_seconds = None
        self.setObjectName("StepCard")
        self.setProperty("stepStatus", "idle")
        self.setProperty("stepType", TYPE_CLASSES.get(step.step_type, "python"))
        if getattr(step, "is_gate", False):
            self.setProperty("checkpoint", True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        batch_tip = (
            f"{order_label} 是执行批次。\n"
            "批次由阶段顺序、上游依赖和检查点自动计算。\n"
            "同一批次的步骤在依赖满足后可一起执行；启用自动并行时可并行运行。"
        )
        order = QLabel(order_label)
        order.setObjectName("StepOrder")
        order.setFixedWidth(42)
        order.setToolTip(batch_tip)
        order.setAccessibleName(f"执行批次 {order_label}")
        order.setAlignment(Qt.AlignCenter)
        order.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(order)

        # 类型图标 + 检查点盾牌图标（检查点卡片）。文字徽章（TypePill/“检查点”）已精简，
        # 避免 200px 紧凑泳道下顶行溢出截断；类型与检查点全称保留在 tooltip 和 accessibleName。
        # 图标颜色在创建时烘焙，保存引用供 refresh_theme 按当前主题重设
        from ui.icons import type_icon
        self._step_type = step.step_type
        self._is_gate = bool(getattr(step, "is_gate", False))
        self.type_icon_label = QLabel()
        self.type_icon_label.setPixmap(
            type_icon(step.step_type, dark=False).pixmap(self.ICON_SIZE_PX, self.ICON_SIZE_PX)
        )
        self.type_icon_label.setAccessibleName(f"类型：{TYPE_LABELS.get(step.step_type, step.step_type)}")
        self.type_icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(self.type_icon_label)

        if self._is_gate:
            self.gate_icon_label = QLabel()
            self.gate_icon_label.setPixmap(self._gate_pixmap(dark=False))
            self.gate_icon_label.setAccessibleName("检查点")
            self.gate_icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            top.addWidget(self.gate_icon_label)

        top.addStretch()
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("StatusBadge")
        self.status_badge.setProperty("stepStatus", "idle")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setVisible(False)
        self.status_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(self.status_badge)
        layout.addLayout(top)

        title = QLabel(step.name or "未命名步骤")
        title.setObjectName("StepTitle")
        title.setWordWrap(False)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(title)

        subtitle = QLabel(self._subtitle(step, dep_text))
        subtitle.setObjectName("StepSubtitle")
        subtitle.setWordWrap(False)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        subtitle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(subtitle)
        self.subtitle = subtitle
        self._base_subtitle = subtitle.text()

        self.duration_badge = QLabel("")
        self.duration_badge.setObjectName("DurationBadge")
        self.duration_badge.setVisible(False)
        self.duration_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.duration_badge)

        self.setToolTip(
            f"{step.name}\n{batch_tip}\n类型：{TYPE_LABELS.get(step.step_type, step.step_type)}\n"
            f"文件：{getattr(step, 'script_path', '') or '未设置'}\n{dep_text}"
        )
        self.setAccessibleName(f"步骤：{step.name}")
        self.refresh_minimum_height()

    def refresh_minimum_height(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        self.setMinimumHeight(0)
        self.updateGeometry()
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def set_status(self, status: str) -> bool:
        next_status = status or "idle"
        if next_status == self._status:
            return False
        self._status = next_status
        self.setProperty("stepStatus", self._status)
        self.status_badge.setProperty("stepStatus", self._status)
        self.status_badge.setText(STATUS_LABELS.get(self._status, ""))
        self.status_badge.setVisible(self._status in STATUS_LABELS)
        if self._status == "running":
            self.set_duration_seconds(None)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.style().unpolish(self)
        self.style().polish(self)
        self.refresh_minimum_height()
        return True

    def set_duration_seconds(self, duration_seconds) -> bool:
        duration_text = format_duration_short(duration_seconds)
        next_text = f"耗时 {duration_text}" if duration_text else ""
        if duration_seconds == self._duration_seconds and self.duration_badge.text() == next_text:
            return False
        self._duration_seconds = duration_seconds
        self.duration_badge.setText(next_text)
        self.duration_badge.setVisible(bool(duration_text))
        self.refresh_minimum_height()
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.step_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton:
            return
        distance = (event.position().toPoint() - self._press_pos).manhattanLength()
        if distance < 8:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_STEP_ID, str(self.step_id).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def _gate_pixmap(self, dark: bool) -> QPixmap:
        """检查点盾牌图标，按主题取 violet 色（与卡片检查点左侧边框同源）。"""
        from ui.icons import icon
        from ui.theme import get_colors

        return icon("step.gate", color=get_colors(dark)["violet"]).pixmap(
            self.ICON_SIZE_PX, self.ICON_SIZE_PX
        )

    def refresh_theme(self, dark: bool):
        """主题切换后按新主题重设图标颜色（颜色创建时烘焙，无法靠 QSS 更新）。"""
        from ui.icons import type_icon
        self.type_icon_label.setPixmap(
            type_icon(self._step_type, dark=dark).pixmap(self.ICON_SIZE_PX, self.ICON_SIZE_PX)
        )
        if self._is_gate:
            self.gate_icon_label.setPixmap(self._gate_pixmap(dark))

    @staticmethod
    def _subtitle(step, dep_text: str) -> str:
        script = getattr(step, "script_path", "") or "未设置脚本 / 文件"
        name = Path(script).name if script else script
        if getattr(step, "is_gate", False):
            return f"{name} · 检查点"
        return f"{name} · {dep_text}"


class StageLane(QFrame):
    """阶段泳道，接收步骤拖放。"""

    selected = Signal(str)
    step_dropped = Signal(int, str, object)

    def __init__(self, stage, index: int, parent=None):
        super().__init__(parent)
        self.stage_uid = stage.uid
        self.stage_name = stage.name
        self.index = index
        self._cards: list[StepCard] = []
        self.setObjectName("StageLane")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(STAGE_LANE_MIN_WIDTH)
        self.setFixedWidth(STAGE_LANE_MIN_WIDTH)
        self.setMinimumHeight(STAGE_LANE_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        code = QLabel(f"S{index + 1}")
        code.setObjectName("StageCode")
        title_box.addWidget(code)
        title = QLabel(stage.name)
        title.setObjectName("StageTitle")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        title.setToolTip(stage.name)
        title_box.addWidget(title)
        header.addLayout(title_box, stretch=1)

        self.count_label = QLabel("0 步")
        self.count_label.setObjectName("StageCount")
        header.addWidget(self.count_label)
        self.layout.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setObjectName("StageProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setProperty("stageStatus", "idle")
        self.progress.setToolTip("阶段进度：0/0")
        self.progress.setAccessibleName(f"阶段进度：S{index + 1} {stage.name}")
        self.layout.addWidget(self.progress)

        self.cards_box = QVBoxLayout()
        self.cards_box.setContentsMargins(0, 0, 0, 0)
        self.cards_box.setSpacing(10)
        self.layout.addLayout(self.cards_box)

        self.setToolTip(f"S{index + 1} {stage.name}\n点击选中阶段；拖入步骤可变更阶段或顺序")
        self.setAccessibleName(f"阶段：S{index + 1} {stage.name}")

    def add_card(self, card: StepCard) -> None:
        self._cards.append(card)
        self.cards_box.addWidget(card)
        self.count_label.setText(f"{len(self._cards)} 步")
        self.update_progress()
        self.refresh_minimum_height()

    def refresh_minimum_height(self) -> None:
        for card in self._cards:
            card.refresh_minimum_height()
        self.layout.invalidate()
        self.layout.activate()
        self.setMaximumHeight(QT_MAX_WIDGET_SIZE)
        content_height = max(
            STAGE_LANE_MIN_HEIGHT,
            self.layout.minimumSize().height() + STAGE_LANE_BORDER_HEIGHT,
            self.sizeHint().height(),
        )
        self.setFixedHeight(content_height)
        self.updateGeometry()

    def ordered_step_ids(self) -> list[int]:
        return [card.step_id for card in self._cards]

    def set_lane_width(self, width: int) -> None:
        """任务13：响应式——动态调整泳道宽度。"""
        target = max(STAGE_LANE_COMPACT_WIDTH, int(width))
        if target == self.width():
            return
        self.setFixedWidth(target)
        self.setMinimumWidth(target)
        self.refresh_minimum_height()
        self.updateGeometry()

    def update_progress(self) -> bool:
        total = len(self._cards)
        completed = sum(1 for card in self._cards if card._status in COMPLETED_STATUSES)
        value = round((completed / total) * 100) if total else 0
        status = self._progress_status(total)
        tooltip = f"阶段进度：{completed}/{total}"
        if (
            self.progress.value() == value
            and self.progress.property("stageStatus") == status
            and self.progress.toolTip() == tooltip
        ):
            return False
        self.progress.setValue(value)
        self.progress.setProperty("stageStatus", status)
        self.progress.setToolTip(tooltip)
        self.progress.style().unpolish(self.progress)
        self.progress.style().polish(self.progress)
        return True

    def _progress_status(self, total: int) -> str:
        if total == 0:
            return "idle"
        statuses = {card._status for card in self._cards}
        if "failure" in statuses:
            return "failure"
        if "running" in statuses:
            return "running"
        if "cancelled" in statuses:
            return "cancelled"
        if all(status in COMPLETED_STATUSES for status in statuses):
            return "success"
        return "idle"

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.stage_uid)
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_STEP_ID):
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_STEP_ID):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
        if not event.mimeData().hasFormat(MIME_STEP_ID):
            event.ignore()
            return
        try:
            step_id = int(bytes(event.mimeData().data(MIME_STEP_ID)).decode("utf-8"))
        except ValueError:
            event.ignore()
            return
        before_step_id = self._step_before_y(event.position().toPoint().y())
        self.step_dropped.emit(step_id, self.stage_uid, before_step_id)
        event.acceptProposedAction()

    def _step_before_y(self, y: int):
        for card in self._cards:
            center_y = card.y() + card.height() // 2
            if y < center_y:
                return card.step_id
        return None


class WorkbenchBoardPanel(QWidget):
    """按阶段泳道展示和编排步骤。"""

    step_selected = Signal(int)
    stage_selected = Signal(str)
    add_step_requested = Signal(str)
    add_stage_requested = Signal(str)
    reorder_requested = Signal(int, str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._workflow_id = None
        self._selected_stage_uid = ""
        self._selected_step_id = None
        self._edit_enabled = False
        self._lanes: dict[str, StageLane] = {}
        self._cards: dict[int, StepCard] = {}
        self._step_stage: dict[int, str] = {}
        self._ordered_step_ids: list[int] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setFocusPolicy(Qt.StrongFocus)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        toolbar = QFrame()
        toolbar.setObjectName("BoardToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)

        self.selection_hint = QLabel("选择一个工作流后开始编排")
        self.selection_hint.setObjectName("SelectionHint")
        toolbar_layout.addWidget(self.selection_hint, stretch=1)

        self.btn_add_step = QPushButton("+ 添加步骤")
        self.btn_add_step.setObjectName("GhostButton")
        self.btn_add_step.setToolTip("添加步骤到当前选中的阶段")
        self.btn_add_step.setAccessibleName("添加步骤")
        self.btn_add_step.clicked.connect(self._request_add_step)
        toolbar_layout.addWidget(self.btn_add_step)

        self.btn_add_stage = QPushButton("+ 新阶段")
        self.btn_add_stage.setObjectName("GhostButton")
        self.btn_add_stage.setToolTip("在当前阶段之后新增阶段")
        self.btn_add_stage.setAccessibleName("新增阶段")
        self.btn_add_stage.clicked.connect(self._request_add_stage)
        toolbar_layout.addWidget(self.btn_add_stage)
        root.addWidget(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("StageBoardScroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.NoFrame)
        # 任务15：横向滚动条 AsNeeded——内容能放下时不占用空间
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.board_widget = QWidget()
        self.board_widget.setObjectName("StageBoard")
        self.board_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.board_layout = QHBoxLayout(self.board_widget)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setSpacing(STAGE_LANE_GAP)
        self.board_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll.setWidget(self.board_widget)
        root.addWidget(self.scroll, stretch=1)

        self.empty_state = QLabel("暂无步骤。开启编辑后点击“添加步骤”创建第一步。")
        self.empty_state.setObjectName("EmptyState")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setVisible(False)
        root.addWidget(self.empty_state)

        self.refresh_theme(False)

    def showEvent(self, event):
        super().showEvent(event)
        self._queue_board_size_sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_board_size_sync()

    def refresh_after_view_shown(self) -> None:
        self._sync_board_minimum_size()
        self._queue_board_size_sync()
        self._queue_selected_scroll()

    def refresh_theme(self, dark: bool):
        self._dark = bool(dark)
        self.setStyleSheet(build_board_stylesheet(board_tokens(self._dark)))
        for card in self._cards.values():
            card.refresh_theme(self._dark)
        self._refresh_button_state()

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = bool(enabled)
        self._refresh_button_state()

    def load_workflow(self, workflow_id: int, *, steps=None, stages=None, workflow=None):
        # P1-B: 切换工作流时由主窗口预加载 steps/stages/workflow 一次传入，
        # 避免与 step_table / header 各自重复 SELECT 同一批数据。
        self._workflow_id = workflow_id
        self._cards.clear()
        self._lanes.clear()
        self._step_stage.clear()
        self._ordered_step_ids.clear()
        self._clear_layout()

        stages = list_stages(workflow_id) if stages is None else stages
        steps = get_steps_by_workflow(workflow_id) if steps is None else steps
        workflow = get_workflow_by_id(workflow_id) if workflow is None else workflow
        stage_map = get_stage_order_map(workflow_id)

        stage_uids = {stage.uid for stage in stages}
        if self._selected_stage_uid not in stage_uids:
            self._selected_stage_uid = stages[0].uid if stages else ""
        if not self._selected_stage_uid and stages:
            self._selected_stage_uid = stages[0].uid

        batch_map = self._build_batch_map(workflow, steps, stage_map)
        ordered_steps = sorted(
            steps,
            key=lambda s: (int(stage_map.get(getattr(s, "stage_uid", ""), 0) or 0), s.order),
        )
        self._ordered_step_ids = [int(s.id) for s in ordered_steps]

        for idx, stage in enumerate(stages):
            lane = StageLane(stage, idx)
            lane.selected.connect(self._on_lane_selected)
            lane.step_dropped.connect(self._on_step_dropped)
            self._lanes[stage.uid] = lane
            self.board_layout.addWidget(lane, 0, Qt.AlignTop)

            stage_steps = [
                step for step in ordered_steps if (getattr(step, "stage_uid", "") or "") == stage.uid
            ]
            for within_idx, step in enumerate(stage_steps, start=1):
                dep_text = self._dep_summary(step)
                order_label = f"B{batch_map.get(int(step.id), within_idx)}"
                card = StepCard(step, order_label, dep_text)
                card.refresh_theme(self._dark)
                card.selected.connect(self._on_card_selected)
                lane.add_card(card)
                self._cards[int(step.id)] = card
                self._step_stage[int(step.id)] = stage.uid

        self._sync_board_minimum_size()
        self._queue_board_size_sync()
        self.empty_state.setVisible(not steps)
        if self._selected_step_id in self._cards:
            self.select_step(self._selected_step_id, emit_signal=False)
        else:
            self.select_stage(self._selected_stage_uid or (stages[0].uid if stages else ""), emit_signal=False)
        self._refresh_button_state()

    def clear(self):
        self._workflow_id = None
        self._selected_stage_uid = ""
        self._selected_step_id = None
        self._cards.clear()
        self._lanes.clear()
        self._step_stage.clear()
        self._ordered_step_ids.clear()
        self._clear_layout()
        self._sync_board_minimum_size()
        self._queue_board_size_sync()
        self.selection_hint.setText("选择一个工作流后开始编排")
        self.empty_state.setVisible(False)
        self._refresh_button_state()

    def select_stage(self, stage_uid: str, emit_signal: bool = True):
        if not stage_uid:
            return
        self._selected_stage_uid = stage_uid
        self._selected_step_id = None
        for uid, lane in self._lanes.items():
            lane.set_selected(uid == stage_uid)
        for card in self._cards.values():
            card.set_selected(False)
        lane = self._lanes.get(stage_uid)
        if lane:
            self.selection_hint.setText(
                f"已选中 S{lane.index + 1} {lane.stage_name}，新增步骤会加入该阶段"
            )
            self._queue_lane_scroll(stage_uid)
        if emit_signal:
            self.stage_selected.emit(stage_uid)

    def select_step(self, step_id: int, emit_signal: bool = True):
        if step_id not in self._cards:
            return
        self._selected_step_id = int(step_id)
        stage_uid = self._step_stage.get(step_id, "")
        if stage_uid:
            self._selected_stage_uid = stage_uid
        for uid, lane in self._lanes.items():
            lane.set_selected(uid == stage_uid)
        for sid, card in self._cards.items():
            card.set_selected(sid == step_id)
        lane = self._lanes.get(stage_uid)
        if lane:
            self.selection_hint.setText(
                f"已选中 S{lane.index + 1} {lane.stage_name}，新增步骤会加入该阶段"
            )
            self._queue_step_scroll(step_id)
        if emit_signal:
            self.step_selected.emit(step_id)

    def selected_stage_uid(self) -> str:
        return self._selected_stage_uid or ""

    def _on_lane_selected(self, stage_uid: str) -> None:
        self.select_stage(stage_uid)
        self.setFocus(Qt.MouseFocusReason)

    def _on_card_selected(self, step_id: int) -> None:
        self.select_step(step_id)
        self.setFocus(Qt.MouseFocusReason)

    def reset_all_status(self):
        for card in self._cards.values():
            card.set_status("idle")
            card.set_duration_seconds(None)
        self._refresh_stage_progress()
        self._sync_board_minimum_size()

    def highlight_step(self, step_id: int, status: str, duration_seconds=None):
        card = self._cards.get(int(step_id))
        if card:
            changed = card.set_status(status or "idle")
            if status != "running":
                changed = card.set_duration_seconds(duration_seconds) or changed
            stage_uid = self._step_stage.get(int(step_id), "")
            lane = self._lanes.get(stage_uid)
            if lane and changed:
                lane.update_progress()
                lane.refresh_minimum_height()
                self._sync_board_minimum_size()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            if self._select_adjacent_stage(-1):
                event.accept()
                return
        elif event.key() == Qt.Key_Right:
            if self._select_adjacent_stage(1):
                event.accept()
                return
        super().keyPressEvent(event)

    def _request_add_step(self):
        if not self._workflow_id:
            return
        self.add_step_requested.emit(self._selected_stage_uid)

    def _request_add_stage(self):
        if not self._workflow_id:
            return
        self.add_stage_requested.emit(self._selected_stage_uid)

    def _on_step_dropped(self, step_id: int, target_stage_uid: str, before_step_id):
        if not self._workflow_id or step_id not in self._ordered_step_ids:
            return
        next_order = self._order_after_drop(step_id, target_stage_uid, before_step_id)
        self.reorder_requested.emit(step_id, target_stage_uid, next_order)

    def _order_after_drop(self, step_id: int, target_stage_uid: str, before_step_id) -> list[int]:
        stage_blocks: list[tuple[str, list[int]]] = []
        seen = set()
        for uid, lane in self._lanes.items():
            ids = [sid for sid in lane.ordered_step_ids() if sid != step_id]
            if uid == target_stage_uid:
                if before_step_id in ids:
                    ids.insert(ids.index(before_step_id), step_id)
                else:
                    ids.append(step_id)
            stage_blocks.append((uid, ids))
            seen.update(ids)

        missing = [sid for sid in self._ordered_step_ids if sid not in seen and sid != step_id]
        ordered = []
        for _uid, ids in stage_blocks:
            ordered.extend(ids)
        ordered.extend(missing)
        return ordered

    def _clear_layout(self):
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _sync_board_minimum_size(self) -> None:
        stage_count = len(self._lanes)
        if stage_count <= 0:
            self.board_widget.setMinimumSize(0, 0)
            self.board_widget.resize(0, 0)
            self.board_widget.updateGeometry()
            return
        margins = self.board_layout.contentsMargins()
        # 任务13：响应式——窗口宽度 < 1200 时使用 COMPACT_WIDTH，否则 MIN_WIDTH
        lane_width = self._responsive_lane_width()
        for lane in self._lanes.values():
            lane.set_lane_width(lane_width)
            lane.refresh_minimum_height()
        total_width = (
            margins.left()
            + margins.right()
            + stage_count * lane_width
            + max(0, stage_count - 1) * STAGE_LANE_GAP
        )
        total_height = (
            margins.top()
            + margins.bottom()
            + max(lane.minimumHeight() for lane in self._lanes.values())
        )
        self.board_widget.setMinimumSize(total_width, total_height)
        self.board_widget.resize(self.board_widget.minimumSize())
        self.board_widget.updateGeometry()

    def _responsive_lane_width(self) -> int:
        """任务13：根据窗口宽度返回阶段泳道宽度。

        仅当 panel 真正嵌入到 MainWindow 中时才走响应式逻辑；
        否则（测试场景下 panel 自身为 top-level）回退到默认宽度，避免抖动。
        """
        window = self.window()
        if window is None or window is self:
            return STAGE_LANE_MIN_WIDTH
        try:
            win_width = int(window.width())
        except Exception:
            return STAGE_LANE_MIN_WIDTH
        if win_width <= 0:
            return STAGE_LANE_MIN_WIDTH
        return STAGE_LANE_COMPACT_WIDTH if win_width < RESPONSIVE_WIDTH_BREAKPOINT else STAGE_LANE_MIN_WIDTH

    def _queue_lane_scroll(self, stage_uid: str) -> None:
        QTimer.singleShot(0, lambda uid=stage_uid: self._scroll_lane_into_view(uid))

    def _queue_step_scroll(self, step_id: int) -> None:
        QTimer.singleShot(0, lambda sid=int(step_id): self._scroll_step_into_view(sid))

    def _queue_board_size_sync(self) -> None:
        QTimer.singleShot(0, self._sync_board_minimum_size)

    def _queue_selected_scroll(self) -> None:
        if self._selected_step_id in self._cards:
            self._queue_step_scroll(int(self._selected_step_id))
        elif self._selected_stage_uid in self._lanes:
            self._queue_lane_scroll(self._selected_stage_uid)

    def _scroll_lane_into_view(self, stage_uid: str) -> None:
        lane = self._lanes.get(stage_uid)
        if lane:
            self._scroll_widget_into_view(lane, vertical_margin=12)

    def _scroll_step_into_view(self, step_id: int) -> None:
        card = self._cards.get(int(step_id))
        if card:
            self._scroll_widget_into_view(card, vertical_margin=12)

    def _scroll_widget_into_view(self, widget: QWidget, *, vertical_margin: int = 12) -> None:
        hbar = self.scroll.horizontalScrollBar()
        viewport_width = self.scroll.viewport().width()
        if hbar is not None and viewport_width > 0:
            left = widget.mapTo(self.board_widget, QPoint(0, 0)).x()
            right = left + widget.width()
            current = hbar.value()
            margin = 24
            if left < current + margin:
                hbar.setValue(max(hbar.minimum(), left - margin))
            elif right > current + viewport_width - margin:
                hbar.setValue(min(hbar.maximum(), right - viewport_width + margin))
        self.scroll.ensureWidgetVisible(widget, 0, vertical_margin)

    def _select_adjacent_stage(self, offset: int) -> bool:
        stage_uids = list(self._lanes.keys())
        if not stage_uids:
            return False
        current = self._selected_stage_uid if self._selected_stage_uid in self._lanes else stage_uids[0]
        next_index = stage_uids.index(current) + offset
        if next_index < 0 or next_index >= len(stage_uids):
            return False
        self.select_stage(stage_uids[next_index])
        return True

    def _refresh_stage_progress(self) -> None:
        for lane in self._lanes.values():
            lane.update_progress()

    def _refresh_button_state(self):
        enabled = bool(self._workflow_id) and self._edit_enabled
        self.btn_add_step.setEnabled(enabled)
        self.btn_add_stage.setEnabled(enabled)
        suffix = "" if enabled else "（需要先选择工作流并开启编辑模式）"
        self.btn_add_step.setToolTip(f"添加步骤到当前选中的阶段{suffix}")
        self.btn_add_stage.setToolTip(f"在当前阶段之后新增阶段{suffix}")

    def _dep_summary(self, step) -> str:
        deps = step.get_depends_on() if hasattr(step, "get_depends_on") else []
        if deps:
            return f"上游依赖：{len(deps)} 个步骤"
        if getattr(step, "is_gate", False):
            return "本阶段检查点"
        return "无显式上游依赖"

    def _build_batch_map(self, workflow, steps, stage_map: dict) -> dict[int, int]:
        if not workflow or not steps:
            return {}
        try:
            batches = WorkflowEngine.compute_batches(workflow, steps, stage_map)
        except Exception:
            return {}
        batch_map = {}
        for idx, batch in enumerate(batches, start=1):
            for step in batch:
                batch_map[int(step.id)] = idx
        return batch_map
