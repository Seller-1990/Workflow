# -*- coding: utf-8 -*-
"""工作流列表面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QMenu, QGroupBox
)
from PySide6.QtCore import Qt, Signal, Slot

from database import (
    list_workflows, create_workflow, delete_workflow, 
    copy_workflow, update_workflow
)


class WorkflowListPanel(QWidget):
    """工作流列表面板"""
    
    # 信号
    workflow_selected = Signal(int)  # workflow_id
    workflow_deleted = Signal(int)   # workflow_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit_enabled = True
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        group = QGroupBox("工作流列表")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        group_layout.addWidget(self.list_widget)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        
        self.btn_new = QPushButton("新建")
        self.btn_new.clicked.connect(self._on_new_clicked)
        btn_layout.addWidget(self.btn_new)
        
        self.btn_copy = QPushButton("复制")
        self.btn_copy.clicked.connect(self._on_copy_clicked)
        btn_layout.addWidget(self.btn_copy)
        
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self.btn_delete)
        
        group_layout.addLayout(btn_layout)
        
        layout.addWidget(group)

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self.btn_new.setToolTip("" if enabled else "请先开启左侧“编辑”开关")
        self.btn_copy.setToolTip("" if enabled else "请先开启左侧“编辑”开关")
        self.btn_delete.setToolTip("" if enabled else "请先开启左侧“编辑”开关")

    def _require_edit_enabled(self, action_name: str) -> bool:
        if self._edit_enabled:
            return True
        QMessageBox.information(self, "需要开启编辑", f"{action_name} 前请先开启左侧“编辑”开关。")
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
    
    def load_workflows(self):
        """加载工作流列表"""
        self.list_widget.clear()
        
        workflows = list_workflows()
        for workflow in workflows:
            item = QListWidgetItem(workflow.name)
            item.setData(Qt.UserRole, workflow.id)
            item.setToolTip(f"ID: {workflow.uid}\n创建时间: {workflow.created_at}")
            self.list_widget.addItem(item)
        
        # 选中第一个
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
    
    @Slot()
    def create_workflow(self):
        """新建工作流"""
        if not self._require_edit_enabled("新建工作流"):
            return
        name, ok = QInputDialog.getText(
            self, "新建工作流", "工作流名称:",
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
        """复制工作流"""
        if not self._require_edit_enabled("复制工作流"):
            return
        current = self.list_widget.currentItem()
        if not current:
            return
        
        workflow_id = current.data(Qt.UserRole)
        old_name = current.text()
        
        new_name, ok = QInputDialog.getText(
            self, "复制工作流", "新工作流名称:",
            text=f"{old_name} (副本)"
        )
        
        if ok and new_name.strip():
            copy_workflow(workflow_id, new_name.strip())
            self.load_workflows()
    
    def _delete_workflow(self):
        """删除工作流"""
        if not self._require_edit_enabled("删除工作流"):
            return
        current = self.list_widget.currentItem()
        if not current:
            return
        
        workflow_id = current.data(Qt.UserRole)
        name = current.text()
        
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除工作流 '{name}' 吗？\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
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
        
        new_name, ok = QInputDialog.getText(
            self, "重命名工作流", "新名称:",
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

        action_rename = menu.addAction("重命名")
        action_rename.setEnabled(True)
        action_rename.triggered.connect(self._rename_workflow)

        action_copy = menu.addAction("复制")
        action_copy.setEnabled(True)
        action_copy.triggered.connect(self._copy_workflow)

        menu.addSeparator()

        action_delete = menu.addAction("删除")
        action_delete.setEnabled(True)
        action_delete.triggered.connect(self._delete_workflow)
        
        menu.exec_(self.list_widget.mapToGlobal(pos))
    
    @Slot(int)
    def _on_selection_changed(self, row: int):
        """选择变化"""
        if row < 0:
            return
        
        item = self.list_widget.item(row)
        if item:
            workflow_id = item.data(Qt.UserRole)
            self.workflow_selected.emit(workflow_id)
