# -*- coding: utf-8 -*-
"""主窗口"""

import logging

from PySide6.QtWidgets import QMainWindow, QMessageBox, QToolTip
from PySide6.QtCore import Qt, Slot, QSettings, QTimer, QPoint

logger = logging.getLogger(__name__)

from config import APP_NAME
from database import (
    init_db,
    get_workflow_by_id,
    delete_step,
    get_step_by_id,
    get_steps_by_workflow,
    list_stages,
    create_step,
    create_stage,
)
from engine import WorkflowEngine
from ui.theme import msg_information, msg_warning, msg_critical, msg_question
from ui.webhook_manager import WebhookManagerDialog
from ui.json_actions import export_json_action, import_json_action
from ui import dirty_guard, main_window_setup, main_window_steps, panel_controller, run_dispatch, run_lifecycle_controller


class MainWindow(QMainWindow):
    """主窗口
    
    布局结构：
    - 左侧（可折叠）：工作流列表 + 运行控制
    - 中区：
        - 顶部：当前工作流与运行/停止主操作
        - 编排：阶段看板 + 步骤列表
        - 运行/配置：历史日志与工作流配置
    - 右侧（可折叠）：Inspector + 步骤详情编辑器
    """
    
    def __init__(self):
        super().__init__()
        
        init_db()
        
        self.engine = WorkflowEngine(self)

        self._current_workflow_id = None
        self._running_workflow_id = None  # R5-#1: 正在运行的工作流（与显示分离）
        self._running_workflow_name = None  # R6-#1: 缓存的运行工作流名，避免重复查 DB
        self._pending_retry_cb = None  # R8-#1: F5「停止并运行新的」的待重试回调
        self._edit_mode = False

        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        # 任务7：恢复暗色模式——读取用户保存的偏好，默认浅色
        self._dark_mode = bool(settings.value("dark_mode", False, type=bool))
        
        main_window_setup.setup_ui(self)
        main_window_setup.setup_toolbar(self)
        main_window_setup.setup_statusbar(self)
        main_window_setup.connect_signals(self)

        self._apply_theme()

        self._set_edit_mode(False)
        # V9.3：_set_edit_mode 对初值短路，这里显式初始化保存按钮置灰（与切换编辑开关后的表现一致）
        self.btn_save.setEnabled(False)

        # 任务2：首次启动弹一次性引导气泡，指向 command bar 的编辑开关
        if not settings.value("edit_mode_guide_shown", False, type=bool):
            QTimer.singleShot(500, self._show_edit_mode_guide)

        self.workflow_list.load_workflows()
    
    def _update_border_widget_positions(self):
        """更新浮动折叠按钮位置（实现在 ui.panel_controller）。"""
        panel_controller.update_border_widget_positions(self)

    def _refresh_border_fold_buttons(self):
        """刷新边框折叠按钮样式（实现在 ui.main_window_setup）。"""
        main_window_setup.refresh_border_fold_buttons(self)

    def _create_plan_switch(self):
        """编排视图切换按钮组（实现在 ui.main_window_setup；测试直接调用此方法）。"""
        return main_window_setup.create_plan_switch(self)

    def _set_plan_view(self, index: int):
        self.plan_stack.setCurrentIndex(index)
        for btn, stack_index in getattr(self, "_view_buttons", []):
            btn.setObjectName("ViewSwitchActive" if stack_index == index else "ViewSwitch")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 0 and hasattr(self, "workbench_board"):
            self.workbench_board.refresh_after_view_shown()
        # V9：持久化编排视图索引（启动时 _restore_ui_state 调用也会走这里，重复写无害）
        try:
            from ui.ui_state import save_plan_view_current
            save_plan_view_current(index)
        except Exception:
            pass

    def _on_run_splitter_moved(self, *_args):
        """运行页分栏被用户拖动（实现在 ui.panel_controller）。"""
        panel_controller.on_run_splitter_moved(self, *_args)

    def _apply_run_splitter_profile(self, profile: str, *, force: bool = False):
        """按运行状态应用运行页分栏尺寸（实现在 ui.panel_controller）。"""
        panel_controller.apply_run_splitter_profile(self, profile, force=force)

    def _ensure_run_log_visible(self):
        """确保运行页日志区可见（实现在 ui.panel_controller）。"""
        panel_controller.ensure_run_log_visible(self)

    def _toggle_dark_mode(self, checked):
        # 任务7：恢复暗色模式切换——批次1已完成统一调色板与 token 化，暗色路径完整
        self._dark_mode = bool(checked)
        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        settings.setValue("dark_mode", self._dark_mode)
        self._apply_theme()

    def _apply_theme(self):
        """应用主题样式（实现在 ui.main_window_setup）。"""
        main_window_setup.apply_theme(self)

    def _set_edit_mode(self, enabled: bool):
        enabled = bool(enabled)
        if self._edit_mode == enabled:
            return
        self._edit_mode = enabled
        self.workflow_list.set_edit_enabled(self._edit_mode)
        self.workflow_config.set_edit_enabled(self._edit_mode)
        self.step_table.set_edit_enabled(self._edit_mode)
        self.workbench_board.set_edit_enabled(self._edit_mode)
        self.step_editor.set_edit_enabled(self._edit_mode)

        self.statusbar.showMessage("编辑模式：开启" if self._edit_mode else "编辑模式：关闭（防误操作）", 5000)
        self.btn_save.setEnabled(self._edit_mode)

    def _show_edit_mode_guide(self):
        """任务2：首次启动引导气泡，指向编辑开关"""
        if not hasattr(self, "check_edit_mode"):
            return
        QToolTip.showText(
            self.check_edit_mode.mapToGlobal(QPoint(0, -40)),
            "编辑模式默认关闭以防误操作。\n点击此处开关可开启编辑工作流、阶段和步骤。",
            self.check_edit_mode,
            self.check_edit_mode.rect(),
            8000,
        )
        QSettings(APP_NAME, "ui").setValue("edit_mode_guide_shown", True)

    def _require_edit_mode(self, action_name: str) -> bool:
        if self._edit_mode:
            return True
        self.statusbar.showMessage(f"{action_name}：请先开启左侧「编辑」开关", 5000)
        msg_information(self, self._dark_mode, "需要开启编辑", f"{action_name} 前请先开启左侧「编辑」开关。")
        return False

    def is_edit_mode(self) -> bool:
        """返回当前编辑模式状态"""
        return self._edit_mode

    def _action_new_workflow(self):
        if not self._require_edit_mode("新建工作流"):
            return
        self.workflow_list.create_workflow()

    def _action_save(self):
        if not self._require_edit_mode("保存"):
            return
        self._save_current()

    def _action_import_json(self):
        if not self._require_edit_mode("导入 JSON"):
            return
        self._import_json()

    def _action_export_json(self):
        if not self._require_edit_mode("导出 JSON"):
            return
        self._export_json()
    
    # ===== 槽函数 =====
    
    @Slot(int)
    def _on_workflow_selected(self, workflow_id: int):
        """工作流被选中"""
        # R4-#2: 短路——同 id 重复触发（如 _on_workflow_updated 间接重入）时直接返回，
        # 避免清空 step_editor / 重做 4-5 个 DB 查询；首次进入仍走完整路径
        if workflow_id == self._current_workflow_id and workflow_id is not None:
            return
        # R4-#3 / R5-#4: 运行中切换前确认；不立刻执行 engine.cancel()，
        # 等下一个未保存确认弹窗也通过后再 commit，避免用户在第二弹窗
        # 选「留在当前」后旧运行已被不可逆停止。
        pending_stop_running = False
        if self._current_workflow_id is not None and self._current_workflow_id != workflow_id \
                and getattr(self.engine, "is_running", False):
            choice = self._confirm_switch_while_running(target=workflow_id)
            if choice == "cancel":
                self._restore_selection_silently("switch_workflow")
                return
            pending_stop_running = (choice == "stop")
        # #5: 切换工作流前，如步骤编辑器有未保存改动，弹三选项确认
        if not self._confirm_discard_unsaved(reason="switch_workflow", new_target=workflow_id):
            return
        # R5-#4: 两个弹窗都已确认，现在才真正发起停止
        if pending_stop_running:
            try:
                self.engine.cancel()
                # R6-#3: 标记一个"正在停止中"窗口，让 _refresh_run_lock_panels 暂时不显示
                # 「↻ 后台运行」标签——用户感知就是"已请求停止"而不是"还在后台运行"
                self._stopping_in_progress = True
                try:
                    main_window_setup.set_header_run_button_state(self, "stopping")
                except (AttributeError, RuntimeError):
                    pass
                self.statusbar.showMessage("已请求停止当前运行...", 3000)
            except Exception as e:
                logger.warning("请求停止失败: %s", e)
        self._current_workflow_id = workflow_id
        # R5-#1: 切换显示后立刻按 running 状态刷新面板锁
        self._refresh_run_lock_panels()

        # P-4: 先把"用户立即关注"的内容加载完（workflow_config + 编排视图配置开关），
        # 然后把更重的运行历史推到下一轮事件循环异步加载。
        self.workflow_config.load_workflow(workflow_id)

        # P1-B: 一次读取 workflow/steps/stages，下发给 step_table / workbench_board /
        # header 三个组件，替代各自重复 SELECT（get_steps_by_workflow 3×→1×）。
        workflow = get_workflow_by_id(workflow_id)
        steps = get_steps_by_workflow(workflow_id)
        stages = list_stages(workflow_id)

        parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
        self.step_table.set_parallel_available(parallel_enabled)
        self.step_editor.set_parallel_available(parallel_enabled)

        self.step_table.load_steps(workflow_id, steps=steps, stages=stages, workflow=workflow)
        self.workbench_board.load_workflow(workflow_id, steps=steps, stages=stages, workflow=workflow)
        self._refresh_workbench_header(workflow_id, steps=steps, stages=stages, workflow=workflow)

        # P-4: 异步推迟相对重的运行历史；先让 UI 把已加载内容渲染出来
        QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_history(wid))

        self.log_panel.set_context(workflow_id=workflow_id, step_id=None)

        self.step_editor.clear()

        if workflow:
            self.statusbar.showMessage(f"当前工作流: {workflow.name}", 5000)
            self.lbl_inspector_kind.setText("Inspector")
            self.lbl_inspector_title.setText("选择步骤或阶段")
            # 任务4：选中工作流后填充 Inspector 空白状态
            self.step_editor.show_empty_state(workflow_id)

    def _async_load_history(self, workflow_id: int) -> None:
        if workflow_id != self._current_workflow_id:
            return
        try:
            # P1-C: DB 查询下放后台线程，主线程只渲染——避免完成回调瞬间卡顿。
            self.run_history.load_history_async(workflow_id)
        except Exception as e:
            logger.warning("异步加载历史失败: %s", e)

    # ==================== #5 未保存改动确认 ====================
    def _confirm_switch_while_running(self, target) -> str:
        """R4-#3 / R5-#4: 运行中切换工作流弹窗（实现在 ui.run_lifecycle_controller）。"""
        return run_lifecycle_controller.confirm_switch_while_running(self, target)

    def _confirm_discard_unsaved(self, *, reason: str, new_target) -> bool:
        """#5: 脏改动"保存 / 不保存 / 取消"三选项确认（实现在 ui.dirty_guard）。"""
        return dirty_guard.confirm_discard_unsaved(self, reason=reason, new_target=new_target)

    def _should_check_workflow_config_dirty(self, reason: str) -> bool:
        """是否需要检查工作流配置脏状态（实现在 ui.dirty_guard）。"""
        return dirty_guard.should_check_workflow_config_dirty(self, reason)

    def _is_panel_dirty(self, panel, panel_name: str) -> bool:
        """面板脏状态检查（实现在 ui.dirty_guard）。"""
        return dirty_guard.is_panel_dirty(self, panel, panel_name)

    def _build_dirty_message(self, reason: str, *, config_dirty: bool, step_dirty: bool) -> str:
        """构造未保存提示文案（实现在 ui.dirty_guard）。"""
        return dirty_guard.build_dirty_message(self, reason, config_dirty=config_dirty, step_dirty=step_dirty)

    def _save_dirty_panels(self, *, config_dirty: bool, step_dirty: bool) -> bool:
        """保存脏面板并复查（实现在 ui.dirty_guard）。"""
        return dirty_guard.save_dirty_panels(self, config_dirty=config_dirty, step_dirty=step_dirty)

    def _discard_dirty_panels(self, *, config_dirty: bool, step_dirty: bool) -> bool:
        """丢弃脏面板修改（实现在 ui.dirty_guard）。"""
        return dirty_guard.discard_dirty_panels(self, config_dirty=config_dirty, step_dirty=step_dirty)

    def _discard_panel_changes(self, panel, panel_name: str) -> bool:
        """丢弃单个面板修改（实现在 ui.dirty_guard）。"""
        return dirty_guard.discard_panel_changes(self, panel, panel_name)

    def _reset_panel_dirty_state(self, panel, panel_name: str) -> bool:
        """重置单个面板脏状态（实现在 ui.dirty_guard）。"""
        return dirty_guard.reset_panel_dirty_state(self, panel, panel_name)

    def _restore_selection_silently(self, reason: str) -> bool:
        """R2-#3 / R4-#7: 静默回滚 UI 选中状态，避免引发新一轮选中信号。

        支持 reason: switch_workflow / switch_step
        """
        if reason == "switch_workflow":
            return self._restore_workflow_selection_silently()
        elif reason in {"switch_step", "switch_stage"}:
            return self._restore_step_selection_silently()
        return True

    def _restore_step_selection_silently(self) -> bool:
        """R4-#7: switch_step 取消路径——把 step_table 行选回当前编辑器的 step_id。"""
        try:
            target_step_id = getattr(self.step_editor, "_step_id", None) or getattr(
                self.step_editor, "current_step_id", None
            )
            if not target_step_id:
                return True
            target_step_id = int(target_step_id)
            try:
                self.step_table.select_step(target_step_id, emit_signal=False)
                selection = self.step_table.get_selection_snapshot()
            except Exception as exc:
                logger.warning("回滚步骤表选中失败: step_id=%s, error=%s", target_step_id, exc, exc_info=True)
                return False
            if selection.get("step_id") != target_step_id:
                logger.warning("回滚步骤表选中后状态不一致: expected=%s, actual=%s", target_step_id, selection)
                return False
            try:
                self.workbench_board.select_step(target_step_id, emit_signal=False)
            except Exception as exc:
                logger.warning("回滚看板步骤选中失败: step_id=%s, error=%s", target_step_id, exc, exc_info=True)
                return False
            return True
        except Exception as e:
            logger.warning("回滚步骤选中失败: %s", e)
            return False

    def _restore_workflow_selection_silently(self) -> bool:
        """R2-#3 / R3-#1 / R4-#7: switch_workflow 取消路径的原逻辑提取。"""
        if self._current_workflow_id is None:
            return True
        try:
            # 直接定位 QListWidget 并 blockSignals
            lw = getattr(self.workflow_list, "list_widget", None)
            if lw is None:
                return True
            blocker_active = lw.signalsBlocked()
            lw.blockSignals(True)
            try:
                matched = False
                for i in range(lw.count()):
                    item = lw.item(i)
                    if item and item.data(Qt.UserRole) == self._current_workflow_id:
                        lw.setCurrentItem(item)
                        matched = True
                        break
                # R3-#1: 过滤态下找不到匹配（旧工作流被搜索过滤掉了）：
                # 只清空列表选中，不改当前工作流上下文；中间面板仍显示旧工作流。
                if not matched:
                    lw.setCurrentRow(-1)
            finally:
                lw.blockSignals(blocker_active)
            return True
        except Exception as e:
            logger.warning("回滚选中失败: %s", e)
            return False

    def _refresh_bg_running_label_theme(self) -> None:
        """R7-#2 / R8-#2: 后台运行标签主题刷新（实现在 ui.run_lifecycle_controller）。"""
        run_lifecycle_controller.refresh_bg_running_label_theme(self)

    def _refresh_run_lock_panels(self) -> None:
        """R5-#1 / R6-#1: 运行锁面板守卫与后台运行指示器（实现在 ui.run_lifecycle_controller）。"""
        run_lifecycle_controller.refresh_run_lock_panels(self)

    def _on_bg_running_label_clicked(self, _event) -> None:
        """R6-#1: 点击「后台运行」标签切回运行中的工作流（实现在 ui.run_lifecycle_controller）。"""
        run_lifecycle_controller.on_bg_running_label_clicked(self, _event)
    
    @Slot(int)
    def _on_workflow_deleted(self, workflow_id: int):
        """工作流被删除"""
        if self._current_workflow_id == workflow_id:
            self._current_workflow_id = None
            self.workflow_config.clear()
            self.step_table.clear()
            self.workbench_board.clear()
            self.step_editor.clear()
            self.run_history.clear()
            self.log_panel.set_context(workflow_id=None, step_id=None)
            self._refresh_workbench_header(None)

    def _refresh_workbench_header(
        self, workflow_id: int | None, *, steps=None, stages=None, workflow=None
    ):
        if not workflow_id:
            self.lbl_workflow_title.setText("请选择工作流")
            self.lbl_workflow_meta.setText("0 阶段 · 0 步 · 未运行")
            return
        # P1-B: 切换工作流路径已由 _switch_workflow 预加载并传入，其余调用点回退自查。
        workflow = get_workflow_by_id(workflow_id) if workflow is None else workflow
        stages = list_stages(workflow_id) if stages is None else stages
        steps = get_steps_by_workflow(workflow_id) if steps is None else steps
        self.lbl_workflow_title.setText(workflow.name if workflow else f"工作流 #{workflow_id}")
        parallel = "自动并行" if (workflow and workflow.parallel_enabled) else "串行"
        self.lbl_workflow_meta.setText(f"{len(stages)} 阶段 · {len(steps)} 步 · {parallel}")

    @Slot(str)
    def _on_stage_selected(self, stage_uid: str):
        if not stage_uid:
            return
        current_step_id = getattr(self.step_editor, "_step_id", None)
        selected_stage_uid = None
        step_table_selection = {}
        try:
            step_table_selection = self.step_table.get_selection_snapshot()
        except Exception:
            step_table_selection = {}
        try:
            selected_stage_uid = self.workbench_board.selected_stage_uid()
        except Exception:
            selected_stage_uid = step_table_selection.get("stage_uid")
        if not current_step_id and selected_stage_uid == stage_uid:
            return
        if not self._confirm_discard_unsaved(reason="switch_stage", new_target=stage_uid):
            return
        stage_label = stage_uid
        try:
            stages = list_stages(self._current_workflow_id)
            for idx, stage in enumerate(stages, start=1):
                if stage.uid == stage_uid:
                    stage_label = f"S{idx} {stage.name}"
                    break
        except Exception:
            pass
        try:
            self.workbench_board.select_stage(stage_uid, emit_signal=False)
        except Exception as exc:
            logger.warning("同步看板阶段选中失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
            return
        try:
            self.step_table.set_selected_stage_context(stage_uid, clear_step_selection=True)
        except Exception as exc:
            logger.warning("同步步骤表阶段上下文失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
            return
        self.lbl_inspector_kind.setText("选中阶段")
        self.lbl_inspector_title.setText(stage_label)
        self.step_editor.clear()
        self.run_control.set_selected_step(None, stage_uid)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=None)

    @Slot(str)
    def _on_add_step_requested(self, stage_uid: str):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("添加步骤"):
            return
        try:
            steps = get_steps_by_workflow(self._current_workflow_id)
            next_order = max([int(s.order or 0) for s in steps], default=-1) + 1
            stage_uid = stage_uid or self.workbench_board.selected_stage_uid()
            step = create_step(
                self._current_workflow_id,
                name="新步骤",
                step_type="python",
                script_path="",
                order=next_order,
                stage_uid=stage_uid,
            )
        except Exception as e:
            msg_critical(self, self._dark_mode, "添加失败", str(e))
            return
        self._reload_workflow_surfaces(select_step_id=step.id if step else None)
        self.statusbar.showMessage("已添加步骤", 5000)

    @Slot(str)
    def _on_add_stage_requested(self, stage_uid: str):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("新增阶段"):
            return
        try:
            stages = list_stages(self._current_workflow_id)
            order_by_uid = {stage.uid: int(stage.order or 0) for stage in stages}
            base_order = order_by_uid.get(stage_uid, max(order_by_uid.values(), default=0))
            stage = create_stage(self._current_workflow_id, name="新阶段", order=base_order + 1)
        except Exception as e:
            msg_critical(self, self._dark_mode, "新增阶段失败", str(e))
            return
        self._reload_workflow_surfaces(select_stage_uid=stage.uid if stage else None)
        self.statusbar.showMessage("已新增阶段", 5000)

    @Slot(int, str, list)
    def _on_board_reorder_requested(self, step_id: int, target_stage_uid: str, ordered_step_ids: list):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("拖拽调整步骤"):
            return
        ok = self.step_table.apply_orders_and_stage_updates(
            {int(step_id): target_stage_uid},
            [int(sid) for sid in ordered_step_ids],
        )
        if not ok:
            self.workbench_board.load_workflow(self._current_workflow_id)
            return
        self._reload_workflow_surfaces(select_step_id=int(step_id))
        self.statusbar.showMessage("已更新步骤阶段和顺序", 5000)

    # ── 任务14：快捷键补全 ──
    @Slot()
    def _on_shortcut_new_step(self):
        if not self._current_workflow_id:
            return
        stage_uid = ""
        try:
            stage_uid = self.workbench_board.selected_stage_uid() or ""
        except Exception:
            stage_uid = ""
        self._on_add_step_requested(stage_uid)

    @Slot()
    def _on_shortcut_new_stage(self):
        if not self._current_workflow_id:
            return
        stage_uid = ""
        try:
            stage_uid = self.workbench_board.selected_stage_uid() or ""
        except Exception:
            stage_uid = ""
        self._on_add_stage_requested(stage_uid)

    @Slot()
    def _on_shortcut_delete_step(self):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("删除步骤"):
            return
        step_id = self._current_selected_step_id_for_shortcut()
        if not step_id:
            return
        self.step_table._delete_step(int(step_id))

    @Slot()
    def _on_shortcut_copy_step(self):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("复制步骤"):
            return
        step_id = self._current_selected_step_id_for_shortcut()
        if not step_id:
            return
        self.step_table._copy_step(int(step_id))

    def _current_selected_step_id_for_shortcut(self):
        # 优先 step_editor 当前编辑的 step_id
        sid = getattr(self.step_editor, "_step_id", None)
        if sid:
            return int(sid)
        # 退化到 step_table 选中项
        try:
            snap = self.step_table.get_selection_snapshot() or {}
            sid = snap.get("step_id")
            if sid:
                return int(sid)
        except Exception:
            pass
        return None

    def _reload_workflow_surfaces(self, *, select_step_id: int | None = None, select_stage_uid: str | None = None):
        if not self._current_workflow_id:
            return
        wid = self._current_workflow_id
        self.step_table.load_steps(wid)
        self.workbench_board.load_workflow(wid)
        self._refresh_workbench_header(wid)
        if select_step_id:
            self.step_table.select_step(select_step_id)
            self.workbench_board.select_step(select_step_id, emit_signal=False)
            self._on_step_selected(select_step_id)
        elif select_stage_uid:
            self.workbench_board.select_stage(select_stage_uid, emit_signal=False)
            self._on_stage_selected(select_stage_uid)
    
    @Slot(int)
    def _on_step_selected(self, step_id: int):
        """步骤被选中"""
        try:
            if int(getattr(self.step_editor, "_step_id", 0) or 0) == int(step_id):
                return
        except (TypeError, ValueError):
            pass
        # #5: 切换步骤前，如编辑器有未保存改动，弹三选项确认
        if not self._confirm_discard_unsaved(reason="switch_step", new_target=step_id):
            return
        try:
            self.step_table.select_step(step_id, emit_signal=False)
        except Exception:
            pass
        self.step_editor.load_step(step_id)
        try:
            self.workbench_board.select_step(step_id, emit_signal=False)
        except Exception:
            pass
        try:
            step = get_step_by_id(step_id)
            if step:
                self.lbl_inspector_kind.setText("选中步骤")
                self.lbl_inspector_title.setText(step.name)
        except Exception:
            pass
        stage_uid = None
        if step_id:
            # R3-#10: 优先用 step_table 已缓存的 row_meta；缺失再回退 DB（兼容旧入口）
            stage_uid = self.step_table.get_stage_uid_for_step(step_id)
            if stage_uid is None:
                try:
                    step = get_step_by_id(step_id)
                    if step:
                        stage_uid = step.stage_uid
                except Exception as e:
                    logger.warning("回退查询 step.stage_uid 失败: %s", e)
        self.run_control.set_selected_step(step_id, stage_uid)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=step_id)

    @Slot(int)
    def _on_step_delete_requested(self, step_id: int):
        """从步骤编辑器发起删除。"""
        if not step_id:
            return
        if not self._require_edit_mode("删除步骤"):
            return

        step = get_step_by_id(step_id)
        if not step:
            msg_warning(self, self._dark_mode, "删除失败", "步骤不存在，可能已被删除。")
            if self._current_workflow_id:
                self.step_table.load_steps(self._current_workflow_id)
            self._on_step_deleted(step_id)
            return

        reply = msg_question(
            self,
            self._dark_mode,
            "确认删除步骤",
            f"确定要删除步骤「{step.name}」吗？\n此操作不可撤销，未保存修改也会丢失。",
        )
        if reply != QMessageBox.Yes:
            return

        try:
            ok = delete_step(step_id)
        except Exception as e:
            msg_critical(self, self._dark_mode, "删除失败", str(e))
            return
        if not ok:
            msg_warning(self, self._dark_mode, "删除失败", "步骤不存在或删除失败。")
            return

        if self._current_workflow_id:
            wid = self._current_workflow_id
            self.step_table.load_steps(wid)
        self._on_step_deleted(step_id)
        self.statusbar.showMessage("已删除步骤", 5000)

    @Slot(str, int)
    def _on_step_run_requested(self, mode: str, step_id: int):
        """从 Inspector 发起单步运行。"""
        if mode not in ("only_step", "from_step"):
            return
        self._on_run_requested(mode, step_id)

    @Slot(int)
    def _on_step_deleted(self, step_id: int):
        """步骤被删除后，清理仍指向该步骤的上下文。"""
        current_step_id = getattr(self.step_editor, "_step_id", None)
        if current_step_id != step_id:
            if self._current_workflow_id:
                self.workbench_board.load_workflow(self._current_workflow_id)
            return
        self.step_editor.clear()
        if self._current_workflow_id:
            self.workbench_board.load_workflow(self._current_workflow_id)
            self._refresh_workbench_header(self._current_workflow_id)
        self.run_control.set_selected_step(None, None)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=None)
        self.lbl_inspector_kind.setText("Inspector")
        self.lbl_inspector_title.setText("选择步骤或阶段")

    @Slot(int)
    def _on_dag_step_activated(self, step_id: int):
        """定位到步骤列表并打开编辑器（保留给编辑器/失败弹窗复用）。"""
        if not step_id:
            return
        self.step_table.select_step(step_id)
        self._on_step_selected(step_id)
    
    @Slot()
    def _on_steps_changed(self):
        """步骤发生变化"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            selection = {}
            try:
                selection = self.step_table.get_selection_snapshot()
            except Exception:
                selection = {}
            current_step_id = getattr(self.step_editor, "_step_id", None) or selection.get("step_id")
            current_stage_uid = None
            if current_step_id:
                try:
                    current_stage_uid = self.step_table.get_stage_uid_for_step(current_step_id)
                except Exception:
                    current_stage_uid = None
            if not current_stage_uid:
                current_stage_uid = selection.get("stage_uid") or self.workbench_board.selected_stage_uid()
            self._reload_steps_views(wid, restore_step_id=current_step_id, restore_stage_uid=current_stage_uid, reload_editor=True)
    
    @Slot()
    def _on_step_saved(self):
        """步骤保存"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            current_step_id = getattr(self.step_editor, "_step_id", None)
            current_stage_uid = None
            if current_step_id:
                try:
                    current_stage_uid = self.step_table.get_stage_uid_for_step(current_step_id)
                except Exception:
                    current_stage_uid = None
            self._reload_steps_views(wid, restore_step_id=current_step_id, restore_stage_uid=current_stage_uid)

    def _reload_steps_views(
        self,
        workflow_id: int,
        *,
        restore_step_id: int | None = None,
        restore_stage_uid: str | None = None,
        reload_editor: bool = False,
    ) -> None:
        main_window_steps.reload_steps_views(
            self,
            workflow_id,
            restore_step_id=restore_step_id,
            restore_stage_uid=restore_stage_uid,
            reload_editor=reload_editor,
            get_step_by_id_func=get_step_by_id,
            list_stages_func=list_stages,
        )

    @Slot()
    def _on_workflow_updated(self):
        """工作流配置更新"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            self.workflow_list.load_workflows(selected_workflow_id=wid)
            workflow = get_workflow_by_id(wid)
            parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
            self.step_table.set_parallel_available(parallel_enabled)
            self.step_editor.set_parallel_available(parallel_enabled)
            self.step_table.load_steps(wid)
            self.workbench_board.load_workflow(wid)
            self._refresh_workbench_header(wid)
            # R3-#9 / #15: 把较重的 history 异步刷新，避免一次性触发 DB 查询阻塞主线程
            QTimer.singleShot(0, lambda w=wid: self._async_load_history(w))

    @Slot(bool)
    def _on_run_requested(self, mode: str, param):
        """运行请求（实现在 ui.run_dispatch：含运行中三选弹窗与停止重试链）"""
        run_dispatch.on_run_requested(self, mode, param)

    @Slot(int, str)
    def _on_workflow_started(self, workflow_id: int, run_id: str):
        """工作流开始（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_workflow_started(self, workflow_id, run_id)

    @Slot(int, str, str)
    def _on_workflow_finished(self, workflow_id: int, run_id: str, status: str):
        """工作流结束（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_workflow_finished(self, workflow_id, run_id, status)

    @Slot(int, str)
    def _on_step_started(self, step_id: int, step_name: str):
        """步骤开始（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_step_started(self, step_id, step_name)

    @Slot(int, str, str, object)
    def _on_step_finished(self, step_id: int, step_name: str, status: str, duration_seconds=None):
        """步骤结束（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_step_finished(self, step_id, step_name, status, duration_seconds)

    @Slot(int, int)
    def _on_progress_updated(self, current: int, total: int):
        """进度更新（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_progress_updated(self, current, total)
        # V9：同步更新全局进度条
        if hasattr(self, "global_progress"):
            self.global_progress.set_value(current, total)

    @Slot(list)
    def _on_error_details(self, error_list: list):
        """失败汇总：日志内联 + 弹窗（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_error_details(self, error_list)

    @Slot(int)
    def _focus_step(self, step_id: int):
        """定位到步骤（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.focus_step(self, step_id)

    def _open_step_log_for_step(self, step_id: int):
        """打开指定步骤最新运行日志（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.open_step_log_for_step(self, step_id)

    @Slot(int)
    def _open_failures_for_history(self, history_id: int):
        """从运行历史打开失败步骤汇总（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.open_failures_for_history(self, history_id)

    def _on_dry_run(self):
        """预演模式（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_dry_run(self)
    
    # ===== 工具栏操作 =====
    
    def _save_current(self):
        """保存当前"""
        config_ok = bool(self.workflow_config.save_config())
        step_ok = True
        has_step = bool(getattr(self.step_editor, "_step_id", None))
        try:
            step_dirty = bool(self.step_editor.is_dirty())
        except Exception:
            step_dirty = False
        if has_step or step_dirty:
            step_ok = bool(self.step_editor.save_step())
        if config_ok and step_ok:
            self.statusbar.showMessage("已保存", 5000)
            return True
        self.statusbar.showMessage("保存未完成，请检查输入后重试", 5000)
        return False
    
    def _run_workflow(self):
        """运行工作流"""
        self._on_run_requested("full", None)

    def _on_header_run_clicked(self):
        """顶部主按钮：空闲时运行，运行中切换为停止。"""
        if getattr(self.engine, "is_running", False):
            self._stopping_in_progress = True
            try:
                main_window_setup.set_header_run_button_state(self, "stopping")
            except (AttributeError, RuntimeError):
                pass
            self._stop_workflow()
            return
        self._run_workflow()
    
    def _stop_workflow(self):
        """停止工作流（实现在 ui.run_dispatch）"""
        run_dispatch.stop_workflow(self)
    
    @Slot(int)
    def _on_force_stop_run(self, run_history_id: int):
        """强制停止运行历史中的任务（实现在 ui.run_lifecycle_controller）"""
        run_lifecycle_controller.on_force_stop_run(self, run_history_id)
    
    def _import_json(self):
        """导入 JSON"""
        import_json_action(
            parent=self,
            dark_mode=self._dark_mode,
            reload_workflows=self.workflow_list.load_workflows,
        )
    
    def _export_json(self):
        """导出 JSON"""
        export_json_action(
            parent=self,
            dark_mode=self._dark_mode,
        )

    def _open_webhook_manager(self):
        """打开 Webhook 管理对话框"""
        dialog = WebhookManagerDialog(self)
        dialog.exec_()
        if hasattr(self, "workflow_config") and hasattr(self.workflow_config, "refresh_webhooks"):
            self.workflow_config.refresh_webhooks()

    def _toggle_left_panel(self, silent: bool = False):
        """折叠/展开左侧面板（实现在 ui.panel_controller）。"""
        panel_controller.toggle_left_panel(self, silent=silent)

    def _toggle_right_panel(self, silent: bool = False):
        """折叠/展开右侧面板（实现在 ui.panel_controller）。"""
        panel_controller.toggle_right_panel(self, silent=silent)

    def resizeEvent(self, event):
        """窗口大小变化时更新边框折叠按钮位置"""
        super().resizeEvent(event)
        self._update_border_widget_positions()

    def showEvent(self, event):
        """窗口首次显示时初始化边框折叠按钮位置"""
        super().showEvent(event)
        self._update_border_widget_positions()

    def closeEvent(self, event):
        """关闭事件"""
        if self.engine.is_running:
            reply = msg_question(
                self, self._dark_mode, "确认退出",
                "工作流正在运行，确定要退出吗？",
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        if not self._confirm_discard_unsaved(reason="close", new_target=None):
            event.ignore()
            return
        if self.engine.is_running:
            self.engine.cancel()
            shutdown_wait = self.engine.wait_for_completion(timeout=10.0)
            if hasattr(self, '_run_thread') and self._run_thread.is_alive():
                self._run_thread.join(timeout=5)
                shutdown_wait = shutdown_wait and (not self._run_thread.is_alive())
        else:
            shutdown_wait = True
        
        try:
            self.engine.workflow_started.disconnect(self._on_workflow_started)
            self.engine.workflow_finished.disconnect(self._on_workflow_finished)
            self.engine.step_started.disconnect(self._on_step_started)
            self.engine.step_finished.disconnect(self._on_step_finished)
            self.engine.log_output.disconnect(self.log_panel.append_log)
            self.engine.progress_updated.disconnect(self._on_progress_updated)
            self.engine.error_details.disconnect(self._on_error_details)
        except (RuntimeError, TypeError):
            pass
        
        try:
            self.engine.shutdown(wait=shutdown_wait)
        except Exception:
            logger.exception("关闭工作流引擎失败: shutdown_wait=%s", shutdown_wait)
        
        event.accept()
