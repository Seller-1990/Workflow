# -*- coding: utf-8 -*-
"""任务10：依赖可视化 mini DAG——自上而下列示的迷你依赖图

第一行上游依赖 | 第二行当前步骤 | 第三行下游引用
双击节点发射 step_activated 信号，主窗口定位到该步骤。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QFrame,
)

from ui.theme import get_colors, get_type_tokens


class MiniDagWidget(QWidget):
    """迷你依赖图：展示当前步骤的上下游（垂直三行布局）"""

    step_activated = Signal(int)  # 双击节点跳转

    def __init__(self, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self.setObjectName("MiniDag")
        # 垂直三行，每行需要标题+列表，适当放大高度
        self.setFixedHeight(220)
        self._setup_ui()
        self.refresh_theme(dark)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 第一行：上游依赖
        self.row_upstream = self._build_row("上游依赖", "upstream")
        layout.addWidget(self.row_upstream, stretch=1)

        # 第二行：当前步骤
        self.row_current = self._build_row("当前", "current")
        layout.addWidget(self.row_current, stretch=1)

        # 第三行：下游引用
        self.row_downstream = self._build_row("下游引用", "downstream")
        layout.addWidget(self.row_downstream, stretch=1)

    def _build_row(self, title: str, name: str) -> QWidget:
        """每一行：左侧标题标签 + 右侧列表（横向排列，标题固定宽度避免挤压列表）"""
        row = QWidget()
        row.setObjectName(f"MiniDagRow_{name}")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 0, 2, 0)
        row_layout.setSpacing(6)

        lbl = QLabel(title)
        lbl.setObjectName("MiniDagRowTitle")
        lbl.setFixedWidth(64)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        row_layout.addWidget(lbl)

        lst = QListWidget()
        lst.setObjectName(f"MiniDagList_{name}")
        lst.setFixedHeight(56)
        lst.setMouseTracking(True)
        lst.setMovement(QListWidget.Static)  # 静态布局，避免横向滚动
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lst.itemDoubleClicked.connect(self._on_item_double_clicked)
        row_layout.addWidget(lst, stretch=1)
        return row

    def _on_item_double_clicked(self, item):
        step_id = item.data(Qt.UserRole)
        if step_id:
            self.step_activated.emit(int(step_id))

    def set_data(self, current_step, upstream_steps, downstream_steps):
        """填充数据

        Args:
            current_step: Step 对象或 None
            upstream_steps: Step 列表
            downstream_steps: Step 列表
        """
        self.row_upstream.findChild(QListWidget).clear()
        self.row_current.findChild(QListWidget).clear()
        self.row_downstream.findChild(QListWidget).clear()

        if current_step is None:
            placeholder = QListWidgetItem("（未选中步骤）")
            placeholder.setFlags(Qt.NoItemFlags)
            self.row_current.findChild(QListWidget).addItem(placeholder)
            return

        # 当前步骤
        cur_item = self._make_item(current_step, is_current=True)
        self.row_current.findChild(QListWidget).addItem(cur_item)

        # 上游依赖
        up_list = self.row_upstream.findChild(QListWidget)
        if not upstream_steps:
            it = QListWidgetItem("（无上游依赖）")
            it.setFlags(Qt.NoItemFlags)
            up_list.addItem(it)
        else:
            for s in sorted(upstream_steps, key=lambda x: x.order):
                up_list.addItem(self._make_item(s, is_current=False))

        # 下游引用
        down_list = self.row_downstream.findChild(QListWidget)
        if not downstream_steps:
            it = QListWidgetItem("（无下游引用）")
            it.setFlags(Qt.NoItemFlags)
            down_list.addItem(it)
        else:
            for s in sorted(downstream_steps, key=lambda x: x.order):
                down_list.addItem(self._make_item(s, is_current=False))

    def _make_item(self, step, is_current: bool) -> QListWidgetItem:
        """创建节点 item：显示顺序+名称，左侧色条用样式区分"""
        name = getattr(step, "name", "?")
        order = getattr(step, "order", 0)
        step_id = getattr(step, "id", None)
        step_type = getattr(step, "step_type", "python")
        text = f"{order + 1}. {name}"
        if is_current:
            text = f"▶ {text}"
        it = QListWidgetItem(text)
        if step_id:
            it.setData(Qt.UserRole, step_id)
        # 类型色条用 background 区分；type_key 存入 UserRole+1 供 refresh_theme 重涂
        tokens = get_type_tokens(self._dark)
        type_key = step_type if step_type in tokens else "python"
        it.setData(Qt.UserRole + 1, type_key)
        bg = tokens.get(type_key, {}).get("bg", get_colors(self._dark)["default_type_bg"])
        it.setBackground(_qcolor_from_hex(bg))
        return it

    def refresh_theme(self, dark: bool):
        """刷新主题"""
        self._dark = dark
        colors = get_colors(dark)
        self.setStyleSheet(
            f"""
            QWidget#MiniDag {{
                background: {colors["surface_primary"]};
                border: 1px solid {colors["border"]};
                border-radius: 8px;
            }}
            QLabel#MiniDagRowTitle {{
                color: {colors["text_secondary"]};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 4px;
            }}
            QListWidget#MiniDagList_upstream,
            QListWidget#MiniDagList_current,
            QListWidget#MiniDagList_downstream {{
                background: {colors["surface_card"]};
                border: 1px solid {colors["border"]};
                border-radius: 6px;
                font-size: 11px;
                padding: 2px;
            }}
            QListWidget::item {{
                padding: 2px 4px;
                border-radius: 3px;
            }}
            QListWidget::item:hover {{
                background: {colors["hover"]};
            }}
            """
        )
        # V9.3：节点背景色在 _make_item 时烘焙，仅刷 QSS 无法更新，按新主题 token 重涂
        tokens = get_type_tokens(dark)
        default_bg = colors["default_type_bg"]
        for list_widget in self.findChildren(QListWidget):
            for row in range(list_widget.count()):
                it = list_widget.item(row)
                type_key = it.data(Qt.UserRole + 1)
                if type_key is None:
                    continue
                bg = tokens.get(type_key, {}).get("bg", default_bg)
                it.setBackground(_qcolor_from_hex(bg))


def _qcolor_from_hex(hex_str: str):
    """安全地把 hex 字符串转成 QColor"""
    from PySide6.QtGui import QColor
    try:
        return QColor(hex_str)
    except Exception:
        # V9.2：fallback 用 default_type_bg（原硬编码 #F8FAFC）
        from ui.theme import COLORS
        return QColor(COLORS["default_type_bg"])
