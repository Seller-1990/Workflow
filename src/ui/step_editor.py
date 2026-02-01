# -*- coding: utf-8 -*-
"""步骤详情编辑器"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QLabel,
)
import json
from PySide6.QtCore import Signal, Slot, Qt

from config import StepType
from database import (
    get_session, update_step, get_steps_by_workflow,
    list_workflows, update_recent_workflow,
    has_cross_workflow_cycle
)
from models import Step


class StepEditorPanel(QWidget):
    """步骤详情编辑器"""
    
    # 信号
    step_saved = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_id = None
        self._single_script_mode = False
        self._workflow_targets = []
        self._current_target_uid = None  # 当前选中的子工作流 UID
        self._current_workflow_id = None  # 当前步骤所属的工作流 ID
        self._edit_enabled = True
        self._parallel_available = True
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        self.group = QGroupBox("步骤详情")
        group_layout = QVBoxLayout(self.group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)

        form_widget = QWidget()
        grid = QGridLayout(form_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        
        # 步骤名称
        self.edit_name = QLineEdit()
        row = 0
        grid.addWidget(QLabel("步骤名称"), row, 0)
        grid.addWidget(self.edit_name, row, 1)
        
        # 步骤类型
        self.combo_type = QComboBox()
        for value, display in StepType.choices():
            self.combo_type.addItem(display, value)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        grid.addWidget(QLabel("步骤类型"), row, 2)
        grid.addWidget(self.combo_type, row, 3)
        row += 1
        
        # 脚本路径行（非子工作流类型使用）
        self.script_label = QLabel("脚本/文件")
        script_layout = QHBoxLayout()
        script_layout.setContentsMargins(0, 0, 0, 0)
        self.edit_script = QLineEdit()
        script_layout.addWidget(self.edit_script)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.setFixedWidth(60)
        self.btn_browse.clicked.connect(self._browse_script)
        script_layout.addWidget(self.btn_browse)
        self.script_row = QWidget()
        self.script_row.setLayout(script_layout)
        grid.addWidget(self.script_label, row, 0)
        grid.addWidget(self.script_row, row, 1)

        # 子工作流选择行（子工作流类型使用，与脚本行同位置）
        self.sub_workflow_label = QLabel("目标工作流")
        self.combo_target_workflow = QComboBox()
        self.combo_target_workflow.currentIndexChanged.connect(self._on_target_changed)
        # 初始隐藏
        self.sub_workflow_label.setVisible(False)
        self.combo_target_workflow.setVisible(False)
        grid.addWidget(self.sub_workflow_label, row, 0)
        grid.addWidget(self.combo_target_workflow, row, 1)

        # 工作目录
        cwd_layout = QHBoxLayout()
        cwd_layout.setContentsMargins(0, 0, 0, 0)
        self.edit_cwd = QLineEdit()
        self.edit_cwd.setPlaceholderText("留空使用脚本所在目录")
        cwd_layout.addWidget(self.edit_cwd)
        self.btn_browse_cwd = QPushButton("浏览...")
        self.btn_browse_cwd.setFixedWidth(60)
        self.btn_browse_cwd.clicked.connect(self._browse_cwd)
        cwd_layout.addWidget(self.btn_browse_cwd)
        self.cwd_row = QWidget()
        self.cwd_row.setLayout(cwd_layout)
        self.cwd_label = QLabel("工作目录")
        grid.addWidget(self.cwd_label, row, 2)
        grid.addWidget(self.cwd_row, row, 3)
        row += 1

        # 子工作流搜索过滤行（仅子工作流类型显示）
        self.sub_workflow_filter_widget = QWidget()
        sub_filter_layout = QHBoxLayout(self.sub_workflow_filter_widget)
        sub_filter_layout.setContentsMargins(0, 0, 0, 0)
        sub_filter_layout.setSpacing(10)
        
        sub_filter_layout.addWidget(QLabel("搜索:"))
        self.edit_target_search = QLineEdit()
        self.edit_target_search.setPlaceholderText("输入关键词过滤...")
        self.edit_target_search.textChanged.connect(lambda t: self._refresh_target_options(t))
        self.edit_target_search.setMaximumWidth(200)
        sub_filter_layout.addWidget(self.edit_target_search)
        
        sub_filter_layout.addWidget(QLabel("范围:"))
        self.combo_target_scope = QComboBox()
        self.combo_target_scope.addItem("全部", "all")
        self.combo_target_scope.addItem("最近使用", "recent")
        self.combo_target_scope.currentIndexChanged.connect(lambda: self._refresh_target_options(self.edit_target_search.text()))
        self.combo_target_scope.setMaximumWidth(120)
        sub_filter_layout.addWidget(self.combo_target_scope)
        sub_filter_layout.addStretch()
        
        self.sub_workflow_filter_widget.setVisible(False)
        grid.addWidget(self.sub_workflow_filter_widget, row, 0, 1, 4)
        # 注意：这行在非子工作流时不占用空间，因为 setVisible(False)
        
        
        # 参数（JSON 格式）
        self.edit_args = QLineEdit()
        self.edit_args.setPlaceholderText('例如: ["--output", "result.txt"]')
        grid.addWidget(QLabel("参数(JSON)"), row, 0)
        grid.addWidget(self.edit_args, row, 1, 1, 3)
        row += 1
        
        # 图表主题
        self.edit_theme = QLineEdit()
        self.edit_theme.setPlaceholderText("留空使用工作流默认主题")
        grid.addWidget(QLabel("图表主题"), row, 0)
        grid.addWidget(self.edit_theme, row, 1)
        
        # 超时时间
        self.edit_timeout = QLineEdit()
        self.edit_timeout.setPlaceholderText("秒数，留空不限制")
        grid.addWidget(QLabel("超时时间(秒)"), row, 2)
        grid.addWidget(self.edit_timeout, row, 3)
        row += 1
        
        # 重试次数
        self.edit_retry = QLineEdit()
        self.edit_retry.setPlaceholderText("默认 0")
        grid.addWidget(QLabel("重试次数"), row, 0)
        grid.addWidget(self.edit_retry, row, 1)
        
        # 是否前置
        self.check_gate = QCheckBox("启用（阻塞后续并行步骤）")
        self.check_gate.stateChanged.connect(self._on_gate_state_changed)
        grid.addWidget(QLabel("前置步骤"), row, 2)
        grid.addWidget(self.check_gate, row, 3)
        row += 1
        
        # 是否并行
        self.check_parallel = QCheckBox("启用（可与其他非前置步骤并行）")
        grid.addWidget(QLabel("并行执行"), row, 0)
        grid.addWidget(self.check_parallel, row, 1, 1, 3)
        row += 1

        # 依赖步骤
        self.dep_list = QListWidget()
        self.dep_list.setMaximumHeight(120)
        grid.addWidget(QLabel("依赖步骤"), row, 0)
        grid.addWidget(self.dep_list, row, 1, 1, 3)
        
        group_layout.addWidget(form_widget)
        layout.addWidget(self.group)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_save = QPushButton("保存")
        self.btn_save.setFixedWidth(80)
        self.btn_save.clicked.connect(self.save_step)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_reset = QPushButton("重置")
        self.btn_reset.setFixedWidth(80)
        self.btn_reset.clicked.connect(self._reset)
        btn_layout.addWidget(self.btn_reset)
        
        layout.addLayout(btn_layout)

    def set_single_script_mode(self, enabled: bool):
        """设置单脚本模式"""
        self._single_script_mode = enabled
        self._apply_enabled_state()

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        self.group.setEnabled(can_edit)
        self.btn_save.setEnabled(can_edit)
        self.btn_reset.setEnabled(can_edit)
        self._apply_parallel_enabled_state()

    def _apply_parallel_enabled_state(self):
        if self._single_script_mode:
            self.check_parallel.setEnabled(False)
            return
        if not self._parallel_available:
            self.check_parallel.setChecked(False)
            self.check_parallel.setEnabled(False)
            self.check_parallel.setToolTip("需要先在“基础配置”中启用并行。")
            return
        if self.check_gate.isChecked():
            self.check_parallel.setChecked(False)
            self.check_parallel.setEnabled(False)
            self.check_parallel.setToolTip("前置步骤不能并行。")
            return
        self.check_parallel.setEnabled(self._edit_enabled)
        self.check_parallel.setToolTip("并行：仅在基础配置启用并行后生效。")

    def _on_gate_state_changed(self, _state: int):
        self._apply_parallel_enabled_state()
    
    def load_step(self, step_id: int):
        """加载步骤"""
        self._step_id = step_id
        
        with get_session() as session:
            step = session.query(Step).filter(Step.id == step_id).first()
            if not step:
                self.clear()
                return
            
            # 保存当前工作流 ID（用于排除自引用）
            self._current_workflow_id = step.workflow_id
            
            self.edit_name.setText(step.name)
            
            # 设置步骤类型
            index = self.combo_type.findData(step.step_type)
            if index >= 0:
                self.combo_type.setCurrentIndex(index)
            
            self.edit_script.setText(step.script_path or "")
            self.edit_args.setText(step.args or "")
            self.edit_cwd.setText(step.cwd or "")
            self.edit_theme.setText(step.chart_theme or "")
            self.edit_timeout.setText(str(step.timeout_seconds) if step.timeout_seconds else "")
            self.edit_retry.setText(str(step.retry_count) if step.retry_count else "")
            self.check_gate.setChecked(step.is_gate)
            self.check_parallel.setChecked(step.is_parallel)

            # 依赖步骤列表
            self._load_dependencies(step)
            self._load_workflow_targets(step.script_path)
            self._on_type_changed()
            self._apply_enabled_state()

    def _load_dependencies(self, step: Step):
        """加载依赖步骤列表"""
        self.dep_list.clear()
        steps = get_steps_by_workflow(step.workflow_id)
        selected = set(step.get_depends_on())
        for s in steps:
            if s.id == step.id:
                continue
            item = QListWidgetItem(f"{s.order + 1}. {s.name}")
            item.setData(Qt.UserRole, s.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if s.uid in selected else Qt.Unchecked)
            self.dep_list.addItem(item)
    
    def clear(self):
        """清空表单"""
        self._step_id = None
        self.edit_name.clear()
        self.combo_type.setCurrentIndex(0)
        self._on_type_changed()
        self.edit_script.clear()
        self.edit_args.clear()
        self.edit_cwd.clear()
        self.edit_theme.clear()
        self.edit_timeout.clear()
        self.edit_retry.clear()
        self.check_gate.setChecked(False)
        self.check_parallel.setChecked(False)
        self.dep_list.clear()
        self.combo_target_workflow.clear()
        self.edit_target_search.clear()
        self.combo_target_scope.setCurrentIndex(0)
        self._apply_enabled_state()
    
    @Slot()
    def save_step(self):
        """保存步骤"""
        if not self._step_id:
            return
        
        # 验证参数格式
        args_text = self.edit_args.text().strip()
        if args_text:
            import json
            try:
                args = json.loads(args_text)
                if not isinstance(args, list):
                    raise ValueError("参数必须是数组")
            except (json.JSONDecodeError, ValueError) as e:
                QMessageBox.warning(self, "参数格式错误", f"参数必须是有效的 JSON 数组\n{e}")
                return
        
        # 验证超时时间
        timeout = None
        timeout_text = self.edit_timeout.text().strip()
        if timeout_text:
            try:
                timeout = int(timeout_text)
                if timeout <= 0:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "输入错误", "超时时间必须是正整数")
                return
        
        # 验证重试次数
        retry = 0
        retry_text = self.edit_retry.text().strip()
        if retry_text:
            try:
                retry = int(retry_text)
                if retry < 0:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "输入错误", "重试次数必须是非负整数")
                return
        
        # 更新步骤
        step_type = self.combo_type.currentData()
        script_path = self.edit_script.text().strip()
        if step_type == "sub_workflow":
            uid = self.combo_target_workflow.currentData()
            if not uid:
                QMessageBox.warning(self, "输入错误", "请选择目标工作流")
                return
            if not self._validate_sub_workflow_cycle(uid):
                return
            script_path = uid

        deps = []
        for i in range(self.dep_list.count()):
            item = self.dep_list.item(i)
            if item.checkState() == Qt.Checked:
                deps.append(item.data(Qt.UserRole))

        update_step(
            self._step_id,
            name=self.edit_name.text().strip(),
            step_type=step_type,
            script_path=script_path,
            args=args_text if args_text else None,
            cwd=self.edit_cwd.text().strip() or None,
            chart_theme=self.edit_theme.text().strip() or None,
            timeout_seconds=timeout,
            retry_count=retry,
            is_gate=self.check_gate.isChecked(),
            is_parallel=self.check_parallel.isChecked(),
            depends_on=json.dumps(deps, ensure_ascii=False) if deps else None
        )
        if step_type == "sub_workflow" and script_path:
            update_recent_workflow(script_path)
        
        self.step_saved.emit()
    
    def _reset(self):
        """重置表单"""
        if self._step_id:
            self.load_step(self._step_id)
    
    def _browse_script(self):
        """浏览脚本文件"""
        step_type = self.combo_type.currentData()
        if step_type == "sub_workflow":
            return
        
        if step_type == "python":
            filter_str = "Python Files (*.py);;All Files (*)"
        elif step_type == "excel_powerquery":
            filter_str = "Excel Files (*.xlsx *.xlsm *.xlsb);;All Files (*)"
        elif step_type == "powerbi_refresh":
            filter_str = "Power BI Files (*.pbix);;All Files (*)"
        else:
            filter_str = "All Files (*)"
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", filter_str
        )
        
        if file_path:
            self.edit_script.setText(file_path)
    
    def _browse_cwd(self):
        """浏览工作目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择工作目录"
        )
        
        if dir_path:
            self.edit_cwd.setText(dir_path)

    def _load_workflow_targets(self, current_uid: str = None):
        """加载可选的子工作流列表"""
        workflows = list_workflows()
        # 排除当前步骤所属的工作流（避免自引用）
        self._workflow_targets = [
            (wf.name, wf.uid) for wf in workflows 
            if self._current_workflow_id is None or wf.id != self._current_workflow_id
        ]
        self._current_target_uid = current_uid  # 保存当前选中的 UID
        self._refresh_target_options()

    def _refresh_target_options(self, text: str = ""):
        """刷新目标工作流下拉选项"""
        keyword = (text or "").strip().lower()
        scope = self.combo_target_scope.currentData()
        recent_uids = set()
        if scope == "recent":
            from database import list_recent_workflows
            recent_uids = set(list_recent_workflows())
        
        self.combo_target_workflow.blockSignals(True)  # 防止触发信号
        self.combo_target_workflow.clear()
        
        for name, uid in self._workflow_targets:
            if scope == "recent" and uid not in recent_uids:
                continue
            if keyword and keyword not in name.lower():
                continue
            self.combo_target_workflow.addItem(name, uid)
        
        # 恢复选中状态
        if self._current_target_uid:
            idx = self.combo_target_workflow.findData(self._current_target_uid)
            if idx >= 0:
                self.combo_target_workflow.setCurrentIndex(idx)
        
        self.combo_target_workflow.blockSignals(False)

    def _on_type_changed(self):
        """步骤类型变更时更新 UI"""
        step_type = self.combo_type.currentData()
        is_sub = step_type == "sub_workflow"
        
        # 切换脚本行和子工作流选择行的可见性
        self.script_label.setVisible(not is_sub)
        self.script_row.setVisible(not is_sub)
        self.sub_workflow_label.setVisible(is_sub)
        self.combo_target_workflow.setVisible(is_sub)
        self.sub_workflow_filter_widget.setVisible(is_sub)
        
        # 子工作流类型时隐藏工作目录（子工作流不需要）
        self.cwd_label.setVisible(not is_sub)
        self.cwd_row.setVisible(not is_sub)
        
        if is_sub:
            # 确保工作流列表已加载
            if not self._workflow_targets:
                self._load_workflow_targets(self._current_target_uid)

    def _on_target_changed(self):
        """目标工作流变更时更新"""
        # 不再需要更新 edit_script，因为子工作流类型时使用下拉框
        pass

    def _validate_sub_workflow_cycle(self, target_uid: str) -> bool:
        with get_session() as session:
            step = session.query(Step).filter(Step.id == self._step_id).first()
            if not step:
                return False
            parent_id = step.workflow_id
        if has_cross_workflow_cycle(parent_id, target_uid):
            QMessageBox.warning(self, "循环依赖", "检测到跨工作流循环依赖，请选择其他工作流")
            return False
        return True
