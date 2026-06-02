# -*- coding: utf-8 -*-
"""工作流列表面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QMenu, QLabel, QLineEdit
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont

from database import (
    list_workflows, create_workflow, delete_workflow,
    update_workflow, clone_workflow
)
from ui.theme import COLORS, get_colors, get_menu_stylesheet, msg_information, msg_warning, msg_question, input_get_text


class WorkflowListPanel(QWidget):
    """工作流列表面板"""
    
    # 信号
    workflow_selected = Signal(int)  # workflow_id
    workflow_deleted = Signal(int)   # workflow_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._edit_enabled = False
        self._all_items = []
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        # 按 Pencil：Left Panel 宽 260，List 区域宽约 252（≈ 4px 内边距）
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        header = QLabel("工作流列表")
        f = QFont(header.font())
        f.setPointSize(15)
        f.setWeight(QFont.Weight.Bold)
        header.setFont(f)
        layout.addWidget(header)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索工作流...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS["surface_secondary"]};
                color: {COLORS["text_primary"]};
                border: 1px solid {COLORS["divider_strong"]};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS["primary"]};
            }}
        """)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._filter_workflows)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        layout.addWidget(self.search_input)

        # 列表（行高 36，圆角 10，选中蓝底 + 蓝字）
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("工作流列表")
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background: transparent;
                border: none;
            }}
            QListWidget::item {{
                height: 36px;
                padding: 0px 10px;
                border-radius: 10px;
                color: {COLORS["text_primary"]};
            }}
            QListWidget::item:selected {{
                background: {COLORS["selected_bg"]};
                color: {COLORS["selected_text"]};
                font-weight: 600;
            }}
            """
        )
        layout.addWidget(self.list_widget, stretch=1)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)
        
        self.btn_new = QPushButton("新建")
        self.btn_new.clicked.connect(self._on_new_clicked)
        self.btn_new.setFixedHeight(32)
        self.btn_new.setObjectName("wfPill")
        self.btn_new.setToolTip("新建一个工作流")
        self.btn_new.setAccessibleName("新建工作流")
        btn_layout.addWidget(self.btn_new)
        
        self.btn_copy = QPushButton("克隆")
        self.btn_copy.clicked.connect(self._on_copy_clicked)
        self.btn_copy.setFixedHeight(32)
        self.btn_copy.setObjectName("wfPill")
        self.btn_copy.setToolTip("克隆当前选中的工作流")
        self.btn_copy.setAccessibleName("克隆工作流")
        btn_layout.addWidget(self.btn_copy)
        
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        self.btn_delete.setFixedHeight(32)
        self.btn_delete.setObjectName("wfDangerPill")
        self.btn_delete.setToolTip("删除当前选中的工作流")
        self.btn_delete.setAccessibleName("删除工作流")
        btn_layout.addWidget(self.btn_delete)
        
        layout.addLayout(btn_layout)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {colors["surface_secondary"]};
                color: {colors["text_primary"]};
                border: 1px solid {colors["divider_strong"]};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {colors["primary"]};
            }}
        """)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background: transparent;
                border: none;
            }}
            QListWidget::item {{
                height: 36px;
                padding: 0px 10px;
                border-radius: 10px;
                color: {colors["text_primary"]};
            }}
            QListWidget::item:selected {{
                background: {colors["selected_bg"]};
                color: {colors["selected_text"]};
                font-weight: 600;
            }}
            """
        )

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self.btn_new.setEnabled(enabled)
        self.btn_copy.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)
        self.btn_new.setToolTip("新建一个工作流" if enabled else "新建工作流（需要先开启左侧「编辑」开关）")
        self.btn_copy.setToolTip("克隆当前选中的工作流" if enabled else "克隆工作流（需要先开启左侧「编辑」开关）")
        self.btn_delete.setToolTip("删除当前选中的工作流" if enabled else "删除工作流（需要先开启左侧「编辑」开关）")

    def _require_edit_enabled(self, action_name: str) -> bool:
        if self._edit_enabled:
            return True
        msg_information(self, self._dark, "需要开启编辑", f"{action_name} 前请先开启左侧「编辑」开关。")
        return False

    def _on_new_clicked(self):
        if not self._require_edit_enabled("新建工作流"):
            return
        self.create_workflow()

    def _on_copy_clicked(self):
        if not self._require_edit_enabled("复制工作流"):
            return
        self._copy_workflow()

    def _on_delete_clicked(self):
        if not self._require_edit_enabled("删除工作流"):
            return
        self._delete_workflow()
    
    def load_workflows(self, selected_workflow_id=None):
        """加载工作流列表"""
        self.list_widget.clear()
        self._all_items.clear()

        workflows = list_workflows()
        selected_row = -1
        for workflow in workflows:
            item = QListWidgetItem(workflow.name)
            item.setData(Qt.UserRole, workflow.id)
            item.setToolTip(f"ID: {workflow.uid}\n创建时间: {workflow.created_at}")
            self._all_items.append(item)

            if selected_workflow_id is not None and workflow.id == selected_workflow_id:
                selected_row = len(self._all_items) - 1

        self._filter_workflows()

        if selected_row >= 0:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.data(Qt.UserRole) == selected_workflow_id:
                    self.list_widget.setCurrentRow(i)
                    break
        elif self.list_widget.count() > 0:
            # R2-#7: 找第一个真实 item（跳过 placeholder）
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                if it and it.data(Qt.UserRole) is not None:
                    self.list_widget.setCurrentRow(i)
                    break

    def _filter_workflows(self):
        """根据搜索框内容过滤工作流列表"""
        filter_text = self.search_input.text().strip().lower()
        self.list_widget.clear()
        for item in self._all_items:
            if not filter_text or filter_text in item.text().lower():
                new_item = QListWidgetItem(item)
                new_item.setToolTip(item.toolTip())
                self.list_widget.addItem(new_item)
        # R2-#7: 空状态占位提示
        if self.list_widget.count() == 0:
            if filter_text:
                placeholder = QListWidgetItem(f"未匹配到「{filter_text}」")
            elif not self._all_items:
                placeholder = QListWidgetItem("暂无工作流，点击「新建」按钮开始")
            else:
                placeholder = QListWidgetItem("(空)")
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setForeground(get_colors(self._dark)["text_tertiary"])
            placeholder.setData(Qt.UserRole, None)
            self.list_widget.addItem(placeholder)

    @Slot()
    def create_workflow(self):
        """新建工作流"""
        if not self._require_edit_enabled("新建工作流"):
            return
        name, ok = input_get_text(
            self, self._dark, "新建工作流", "工作流名称:",
            text="新工作流"
        )
        
        if ok and name.strip():
            workflow = create_workflow(name.strip())
            self.load_workflows()
            
            # 选中新建的工作流
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.data(Qt.UserRole) == workflow.id:
                    self.list_widget.setCurrentRow(i)
                    break
    
    def _copy_workflow(self):
        """克隆工作流（含阶段和步骤）"""
        if not self._require_edit_enabled("克隆工作流"):
            return
        current = self.list_widget.currentItem()
        if not current:
            return

        workflow_id = current.data(Qt.UserRole)
        old_name = current.text()

        new_name, ok = input_get_text(
            self, self._dark, "克隆工作流", "新工作流名称:",
            text=f"{old_name} 副本"
        )

        if ok and new_name.strip():
            cloned = clone_workflow(workflow_id, new_name.strip())
            if cloned:
                self.load_workflows(selected_workflow_id=cloned.id)
            else:
                msg_warning(self, self._dark, "克隆失败", "工作流克隆失败，请重试。")
    
    def _delete_workflow(self):
        """删除工作流"""
        if not self._require_edit_enabled("删除工作流"):
            return
        current = self.list_widget.currentItem()
        if not current:
            return
        
        workflow_id = current.data(Qt.UserRole)
        name = current.text()
        
        reply = msg_question(
            self, self._dark, "确认删除",
            f"确定要删除工作流 '{name}' 吗？\n此操作不可恢复！",
        )
        
        if reply == QMessageBox.Yes:
            delete_workflow(workflow_id)
            self.workflow_deleted.emit(workflow_id)
            self.load_workflows()
    
    def _rename_workflow(self):
        """重命名工作流"""
        if not self._require_edit_enabled("重命名工作流"):
            return
        current = self.list_widget.currentItem()
        if not current:
            return
        
        workflow_id = current.data(Qt.UserRole)
        old_name = current.text()
        
        new_name, ok = input_get_text(
            self, self._dark, "重命名工作流", "新名称:",
            text=old_name
        )
        
        if ok and new_name.strip():
            update_workflow(workflow_id, name=new_name.strip())
            self.load_workflows()
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))

        action_rename = menu.addAction("重命名")
        action_rename.setEnabled(self._edit_enabled)
        if not self._edit_enabled:
            action_rename.setToolTip("请先开启编辑模式")

        action_copy = menu.addAction("复制")
        action_copy.setEnabled(self._edit_enabled)
        if not self._edit_enabled:
            action_copy.setToolTip("请先开启编辑模式")

        menu.addSeparator()

        action_delete = menu.addAction("删除")
        action_delete.setEnabled(self._edit_enabled)
        if not self._edit_enabled:
            action_delete.setToolTip("请先开启编辑模式")

        # 连接信号
        action_rename.triggered.connect(self._rename_workflow)
        action_copy.triggered.connect(self._copy_workflow)
        action_delete.triggered.connect(self._delete_workflow)

        menu.exec_(self.list_widget.mapToGlobal(pos))
    
    @Slot(int)
    def _on_selection_changed(self, row: int):
        """选择变化"""
        if row < 0:
            return
        
        item = self.list_widget.item(row)
        if item is None:
            return
        workflow_id = item.data(Qt.UserRole)
        if workflow_id is None:
            return
        self.workflow_selected.emit(workflow_id)
