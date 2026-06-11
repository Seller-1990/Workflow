# -*- coding: utf-8 -*-
"""StepTablePanel 的步骤/阶段操作与事件处理（自 panel.py 纯移动提取，行为不变）。

每个函数的首个参数 ``panel`` 即 StepTablePanel 实例；跨方法调用一律走
``panel._xxx`` 委托方法，保持原有动态分发语义。

注意：依赖错误定位相关方法（``_show_dependency_mutation_error`` /
``_find_step_id_referenced_by_dependency_error``）保留在 panel.py，
因测试通过 ``ui.step_table.panel`` 命名空间打补丁。
"""

import json

from PySide6.QtWidgets import QMenu, QMessageBox
from PySide6.QtCore import Qt, QTimer

from database import (
    get_steps_by_workflow,
    create_step,
    delete_step as db_delete_step,
    update_step,
    copy_step as db_copy_step,
    create_stage,
    update_stage,
    delete_stage,
)
from exceptions import DependencyError, WorkflowError
from stage_mutation_service import (
    apply_orders_and_stage_updates as apply_stage_order_updates,
    migrate_stage_steps as migrate_stage_steps_service,
    move_stage_order as move_stage_order_service,
    move_step_to_stage as move_step_to_stage_service,
)
from ui.theme import (
    get_menu_stylesheet,
    msg_information,
    msg_warning,
    msg_critical,
    msg_question,
    input_get_text,
    input_get_item,
)


def toggle_stage_collapse(panel, stage_uid: str):
    is_collapsed = panel._stage_collapsed.get(stage_uid, False)
    new_collapsed = not is_collapsed
    panel._stage_collapsed[stage_uid] = new_collapsed

    for r, m in enumerate(panel._row_meta):
        if m.get("kind") == "step" and m.get("stage_uid") == stage_uid:
            panel.table.setRowHidden(r, new_collapsed)

    header_row = panel._stage_header_rows.get(stage_uid)
    if header_row is not None:
        stage_idx = panel._stage_uid_to_index.get(stage_uid, 0)
        stage_info = next((st for st in panel._stages if st["uid"] == stage_uid), None) or {"name": "阶段"}
        steps_in_stage = [m for m in panel._row_meta if m.get("kind") == "step" and m.get("stage_uid") == stage_uid]
        panel._render_stage_header_row(header_row, stage_uid, stage_idx, stage_info.get("name", "阶段"), len(steps_in_stage))

    panel._update_table_height()


def add_step(panel):
    """添加步骤"""
    if not panel._workflow_id:
        return

    target_stage_uid = panel._selected_stage_uid or ""
    if panel._selected_step_id:
        for meta in panel._row_meta:
            if meta.get("kind") == "step" and meta.get("step_id") == panel._selected_step_id:
                target_stage_uid = meta.get("stage_uid", "")
                break

    if not target_stage_uid and panel._stages:
        target_stage_uid = panel._stages[0]["uid"]

    steps = get_steps_by_workflow(panel._workflow_id)
    max_order = max((s.order for s in steps), default=-1)

    try:
        step = create_step(
            workflow_id=panel._workflow_id,
            name=f"新步骤 {len(steps) + 1}",
            step_type="python",
            order=max_order + 1,
            stage_uid=target_stage_uid,
        )
    except Exception as e:
        msg_critical(panel, panel._dark, "添加步骤失败", str(e))
        return

    if not step:
        msg_warning(panel, panel._dark, "添加步骤失败", "创建步骤返回空值，请检查数据库。")
        return

    panel.load_steps(panel._workflow_id)
    panel.steps_changed.emit()
    QTimer.singleShot(0, lambda sid=step.id: panel.select_step(sid))


def delete_step(panel, step_id: int):
    """删除步骤"""
    reply = msg_question(panel, panel._dark, "确认删除", "确定要删除这个步骤吗？\n此操作不可撤销，相关未保存编辑会丢失。")
    if reply == QMessageBox.Yes:
        db_delete_step(step_id)
        panel.load_steps(panel._workflow_id)
        panel.step_deleted.emit(step_id)
        panel.steps_changed.emit()


def copy_step(panel, step_id: int):
    """复制步骤"""
    if not panel._workflow_id:
        return
    new_step = db_copy_step(step_id)
    if not new_step:
        msg_warning(panel, panel._dark, "复制失败", "未找到要复制的步骤。")
        return
    panel.load_steps(panel._workflow_id)
    # 选中新步骤
    for row in range(panel.table.rowCount()):
        item = panel.table.item(row, 0)
        if item and item.data(Qt.UserRole) == new_step.id:
            panel.table.setCurrentCell(row, 0)
            break
    panel.steps_changed.emit()


def swap_steps(panel, row1: int, row2: int):
    """交换两个步骤的顺序"""
    item1 = panel.table.item(row1, 0)
    item2 = panel.table.item(row2, 0)

    if not item1 or not item2:
        return

    step_id1 = item1.data(Qt.UserRole)
    step_id2 = item2.data(Qt.UserRole)

    step_ids = panel._get_step_ids_in_visual_order()
    try:
        idx1 = step_ids.index(step_id1)
        idx2 = step_ids.index(step_id2)
    except ValueError:
        return
    step_ids[idx1], step_ids[idx2] = step_ids[idx2], step_ids[idx1]
    if not panel._apply_orders_and_stage_updates({}, step_ids):
        return

    panel.load_steps(panel._workflow_id)
    panel.table.setCurrentCell(row2, 0)
    panel.steps_changed.emit()


def on_gate_changed(panel, step_id: int, state: int):
    """检查点开关变化"""
    is_gate = state == Qt.Checked
    if is_gate:
        update_step(step_id, is_gate=True)
    else:
        update_step(step_id, is_gate=False)
    panel.steps_changed.emit()


def on_depends_prev_changed(panel, step_id: int, prev_step, state: int):
    """依赖上一步（快捷）"""
    if not prev_step:
        return
    from database import get_session
    from models import Step
    with get_session() as session:
        step = session.query(Step).filter(Step.id == step_id).first()
        current = step.get_depends_on() if step else []
    if state == Qt.Checked:
        new_deps = list(dict.fromkeys([*current, prev_step.uid]))
    else:
        new_deps = [d for d in current if d != prev_step.uid]
    update_step(step_id, depends_on=json.dumps(new_deps, ensure_ascii=False) if new_deps else None)
    panel.steps_changed.emit()


def on_selection_changed(panel, row: int, col: int, prev_row: int, prev_col: int):
    """选择变化"""
    if row < 0:
        panel._selected_step_id = None
        panel._last_emitted_selection = None
        return

    meta = panel._row_meta[row] if row < len(panel._row_meta) else {}
    if meta.get("kind") == "stage_header":
        panel._selected_step_id = None
        panel._last_emitted_selection = None
        panel._set_stage_context(meta.get("stage_uid"))
        return

    item = panel.table.item(row, 0)
    if item:
        step_id = item.data(Qt.UserRole)
        if step_id:
            panel._selected_step_id = step_id
            panel._set_stage_context(meta.get("stage_uid"))
            panel._emit_step_selected_once(step_id, row)
        else:
            panel._selected_step_id = None
            panel._last_emitted_selection = None


def on_selection_changed_by_selection(panel):
    """兜底：当点击 cellWidget 导致 currentCellChanged 不触发时，用 selectionChanged 补发 step_selected"""
    row = panel.table.currentRow()
    if row < 0:
        panel._selected_step_id = None
        panel._last_emitted_selection = None
        return
    meta = panel._row_meta[row] if row < len(panel._row_meta) else {}
    if meta.get("kind") == "stage_header":
        panel._selected_step_id = None
        panel._last_emitted_selection = None
        panel._set_stage_context(meta.get("stage_uid"))
        return
    item = panel.table.item(row, 0)
    if not item:
        panel._selected_step_id = None
        panel._last_emitted_selection = None
        return
    step_id = item.data(Qt.UserRole)
    if step_id:
        panel._selected_step_id = step_id
        panel._set_stage_context(meta.get("stage_uid"))
        panel._emit_step_selected_once(step_id, row)
    else:
        panel._selected_step_id = None
        panel._last_emitted_selection = None


def show_context_menu(panel, pos):
    """显示右键菜单"""
    index = panel.table.indexAt(pos)
    if not index.isValid():
        return
    row = index.row()
    step_item = panel.table.item(row, 0)
    if not step_item:
        return
    step_id = step_item.data(Qt.UserRole)
    if not step_id:
        # 阶段标题条：请使用行内"⋯"按钮
        return

    can_edit = panel._edit_enabled and (not panel._single_script_mode)
    menu = QMenu(panel)
    menu.setStyleSheet(get_menu_stylesheet(panel._dark))

    # 执行阶段：移动
    current_stage_uid = ""
    try:
        if 0 <= row < len(panel._row_meta):
            current_stage_uid = panel._row_meta[row].get("stage_uid") or ""
    except Exception:
        current_stage_uid = ""
    current_stage_index = int(panel._stage_uid_to_index.get(current_stage_uid, 0) or 0)

    action_move_prev = menu.addAction("移动到上一阶段")
    action_move_prev.setEnabled(can_edit and current_stage_index > 0)
    if not can_edit:
        action_move_prev.setToolTip('需要先开启左侧"编辑"。')
    elif current_stage_index <= 0:
        action_move_prev.setToolTip("已在第一个阶段。")
    if current_stage_index > 0:
        prev_stage_uid = panel._stages[current_stage_index - 1]["uid"]
        action_move_prev.triggered.connect(lambda: panel._move_step_to_stage(step_id, prev_stage_uid))

    move_menu = menu.addMenu("移动到指定阶段")
    move_menu.setStyleSheet(get_menu_stylesheet(panel._dark))
    if not panel._stages:
        move_menu.setEnabled(False)
    else:
        for st in panel._stages:
            act = move_menu.addAction(st["name"])
            act.setEnabled(can_edit)
            if not can_edit:
                act.setToolTip('需要先开启左侧"编辑"。')
            act.triggered.connect(lambda _, su=st["uid"]: panel._move_step_to_stage(step_id, su))

    action_new_stage = menu.addAction("新建阶段（插入到当前阶段之后）")
    action_new_stage.setEnabled(can_edit)
    action_new_stage.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_new_stage.triggered.connect(lambda: panel._insert_stage_after(current_stage_uid))

    menu.addSeparator()

    # 复制 / 删除
    action_copy = menu.addAction("复制步骤")
    action_copy.setEnabled(can_edit)
    action_copy.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_copy.triggered.connect(lambda: panel._copy_step(step_id))

    action_delete = menu.addAction("删除步骤")
    action_delete.setEnabled(can_edit)
    action_delete.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_delete.triggered.connect(lambda: panel._delete_step(step_id))

    menu.exec_(panel.table.mapToGlobal(pos))


def show_stage_menu(panel, stage_uid: str, global_pos):
    """阶段标题条的"⋯"菜单"""
    if not panel._workflow_id or panel._single_script_mode:
        return
    can_edit = panel._edit_enabled

    stage = next((s for s in panel._stages if s["uid"] == stage_uid), None)
    if not stage:
        return

    menu = QMenu(panel)
    menu.setStyleSheet(get_menu_stylesheet(panel._dark))
    menu.addSection(f"阶段：{stage['name']}")

    action_rename = menu.addAction("重命名阶段")
    action_rename.setEnabled(can_edit)
    action_rename.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')

    def _do_rename():
        text, ok = input_get_text(panel, panel._dark, "重命名阶段", "阶段名称：", text=stage["name"])
        if ok:
            update_stage(stage_uid, name=text.strip() or stage["name"])
            panel.load_steps(panel._workflow_id)
            panel.steps_changed.emit()

    action_rename.triggered.connect(_do_rename)

    action_insert = menu.addAction("在此后插入新阶段")
    action_insert.setEnabled(can_edit)
    action_insert.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_insert.triggered.connect(lambda: panel._insert_stage_after(stage_uid))

    action_insert_before = menu.addAction("在此前插入新阶段")
    action_insert_before.setEnabled(can_edit)
    action_insert_before.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_insert_before.triggered.connect(lambda: panel._insert_stage_before(stage_uid))

    menu.addSeparator()
    action_up = menu.addAction("上移阶段")
    action_down = menu.addAction("下移阶段")
    stage_idx = next((i for i, s in enumerate(panel._stages) if s["uid"] == stage_uid), 0)
    action_up.setEnabled(can_edit and stage_idx > 0)
    action_down.setEnabled(can_edit and stage_idx < len(panel._stages) - 1)
    action_up.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_down.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')
    action_up.triggered.connect(lambda: panel._move_stage_order(stage_uid, -1))
    action_down.triggered.connect(lambda: panel._move_stage_order(stage_uid, +1))

    action_delete = menu.addAction("删除阶段（仅允许空阶段）")
    action_delete.setEnabled(can_edit)
    action_delete.setToolTip("" if can_edit else '需要先开启左侧"编辑"。')

    def _do_delete():
        if not can_edit:
            return
        steps = get_steps_by_workflow(panel._workflow_id)
        used = [s for s in steps if getattr(s, "stage_uid", None) == stage_uid]
        if used:
            # 迁移向导：把该阶段的所有步骤移动到目标阶段后删除
            other_stages = [s for s in panel._stages if s.get("uid") != stage_uid]
            if not other_stages:
                msg_information(panel, panel._dark, "无法删除", "至少需要保留一个执行阶段。")
                return
            names = [s.get("name", "阶段") for s in other_stages]
            default_idx = 0
            # 默认迁移到上一阶段（如果存在）
            cur_idx = next((i for i, s in enumerate(panel._stages) if s.get("uid") == stage_uid), 0)
            if cur_idx > 0:
                prev_uid = panel._stages[cur_idx - 1].get("uid")
                default_idx = next((i for i, s in enumerate(other_stages) if s.get("uid") == prev_uid), 0)
            choice, ok = input_get_item(
                panel, panel._dark,
                "删除阶段",
                "该阶段下仍有步骤。\n请选择迁移目标阶段（会把该阶段所有步骤移动过去，然后删除该阶段）：",
                names,
                current=default_idx,
                editable=False,
            )
            if not ok:
                return
            target = next((s for s in other_stages if s.get("name") == choice), None)
            if not target:
                return
            target_uid = target.get("uid")
            if not panel._migrate_stage_steps(stage_uid, target_uid):
                return
        if not delete_stage(stage_uid):
            msg_information(panel, panel._dark, "无法删除", "该阶段不可删除（可能是默认阶段或删除失败）。")
            return
        panel.load_steps(panel._workflow_id)
        panel.steps_changed.emit()
        panel._notify_status("已删除阶段。")

    action_delete.triggered.connect(_do_delete)

    menu.exec_(global_pos)


def run_stage_mutation(panel, action, dependency_title: str, dependency_detail: str, unknown_message: str) -> bool:
    try:
        return bool(action())
    except DependencyError as e:
        panel._show_dependency_mutation_error(dependency_title, e, dependency_detail)
        return False
    except WorkflowError as e:
        msg_warning(panel, panel._dark, "保存失败", str(e))
        return False
    except Exception as e:
        msg_critical(panel, panel._dark, "保存失败", f"{unknown_message}：{e}")
        return False


def migrate_stage_steps(panel, from_stage_uid: str, to_stage_uid: str) -> bool:
    """把某用途阶段的所有步骤迁移到目标阶段（带预校验与回滚）"""
    if not panel._workflow_id or panel._single_script_mode:
        return False
    ok = panel._run_stage_mutation(
        lambda: migrate_stage_steps_service(panel._workflow_id, from_stage_uid, to_stage_uid),
        "操作无效",
        "建议：检查依赖是否指向未来阶段；或调整执行阶段顺序/归属后再试。",
        "迁移阶段内步骤时发生未知错误",
    )
    if ok:
        panel.load_steps(panel._workflow_id)
        panel.steps_changed.emit()
        panel._notify_status("已迁移阶段内步骤。")
    return ok


def apply_orders_and_stage_updates(panel, stage_overrides: dict[int, str], step_ids_in_order: list[int]) -> bool:
    """通用写库：全量 order + 多步 stage_uid 覆盖（带预校验与回滚）"""
    return panel._run_stage_mutation(
        lambda: apply_stage_order_updates(panel._workflow_id, stage_overrides, step_ids_in_order),
        "操作无效",
        "建议：检查依赖是否指向未来阶段；或调整执行阶段顺序/归属后再试。",
        "保存阶段/顺序时发生未知错误",
    )


def move_stage_order(panel, stage_uid: str, delta: int):
    """调整用途阶段顺序（带预校验与回滚）"""
    if not panel._workflow_id or panel._single_script_mode:
        return
    if not panel._edit_enabled:
        panel._notify_status('需要先开启左侧"编辑"开关。')
        return
    if delta not in (-1, 1):
        return

    ok = panel._run_stage_mutation(
        lambda: move_stage_order_service(panel._workflow_id, stage_uid, delta),
        "无法调整阶段顺序",
        '说明：调整执行阶段顺序会影响"禁止依赖未来阶段"的校验。\n建议：先调整步骤依赖或步骤归类后再试。',
        "调整阶段顺序时发生未知错误",
    )
    if ok:
        panel.load_steps(panel._workflow_id)
        panel.steps_changed.emit()
        panel._notify_status("已调整执行阶段顺序。")


def insert_stage_before(panel, stage_uid: str):
    """在指定阶段之前插入一个新阶段"""
    if not panel._workflow_id or panel._single_script_mode:
        return
    if not panel._edit_enabled:
        panel._notify_status('需要先开启左侧"编辑"开关。')
        return
    stage = next((s for s in panel._stages if s["uid"] == stage_uid), None)
    base_order = int(stage.get("order", 0) if stage else 0)
    new_stage = create_stage(panel._workflow_id, name="新阶段", order=base_order)
    panel.load_steps(panel._workflow_id)
    panel.steps_changed.emit()
    panel._notify_status(f"已新增阶段：{new_stage.name}")


def insert_stage_after(panel, stage_uid: str):
    """在指定阶段后插入一个新阶段（安全模式：不自动改步骤依赖）"""
    if not panel._workflow_id or panel._single_script_mode:
        return
    if not panel._edit_enabled:
        panel._notify_status('需要先开启左侧"编辑"开关。')
        return
    stage = next((s for s in panel._stages if s["uid"] == stage_uid), None)
    base_order = int(stage.get("order", 0) if stage else 0)
    new_stage = create_stage(panel._workflow_id, name="新阶段", order=base_order + 1)
    panel.load_steps(panel._workflow_id)
    panel.steps_changed.emit()
    panel._notify_status(f"已新增阶段：{new_stage.name}")


def apply_orders_and_stage_update(
    panel,
    moved_step_id: int,
    target_stage_uid: str,
    step_ids_in_order: list[int],
) -> bool:
    """拖拽落库：更新 moved 的 stage_uid + 全量 order（带预校验与回滚）"""
    return panel._apply_orders_and_stage_updates({int(moved_step_id): target_stage_uid}, step_ids_in_order)


def move_step_to_stage(panel, step_id: int, target_stage_uid: str):
    """将步骤移动到指定用途阶段（默认放到该阶段末尾）"""
    if not panel._workflow_id or panel._single_script_mode:
        return
    if not panel._edit_enabled:
        panel._notify_status('需要先开启左侧"编辑"开关。')
        return

    ok = panel._run_stage_mutation(
        lambda: move_step_to_stage_service(panel._workflow_id, step_id, target_stage_uid),
        "操作无效",
        "建议：检查依赖是否指向未来阶段；或调整执行阶段顺序/归属后再试。",
        "移动步骤阶段时发生未知错误",
    )
    panel.load_steps(panel._workflow_id)
    if ok:
        panel.steps_changed.emit()
        panel.select_step(step_id)
        panel._notify_status("已移动到目标执行阶段。")


def on_rows_dragged(panel, from_row: int, to_row: int):
    """自定义拖拽：默认只改"用途阶段归类+顺序"，不改依赖"""
    if not panel._workflow_id:
        return
    if not panel._edit_enabled or panel._single_script_mode:
        panel._notify_status('拖拽排序需要先开启左侧"编辑"开关。')
        return
    if from_row < 0 or to_row < 0 or from_row == to_row:
        return
    if from_row >= panel.table.rowCount() or to_row >= panel.table.rowCount():
        return

    moved_item = panel.table.item(from_row, 0)
    if not moved_item:
        return
    moved_step_id = moved_item.data(Qt.UserRole)
    if not moved_step_id:
        return
    try:
        moved_step_id = int(moved_step_id)
    except (ValueError, TypeError):
        return

    target_stage_uid = ""
    try:
        if 0 <= to_row < len(panel._row_meta):
            meta = panel._row_meta[to_row]
            if meta.get("kind") == "stage_header":
                target_stage_uid = meta.get("stage_uid") or ""
            elif meta.get("kind") == "step":
                target_stage_uid = meta.get("stage_uid") or ""
    except Exception:
        target_stage_uid = ""

    if not target_stage_uid and panel._stages:
        target_stage_uid = panel._stages[-1]["uid"]

    step_ids = panel._get_step_ids_in_visual_order()
    if moved_step_id not in step_ids:
        return

    from_idx = step_ids.index(moved_step_id)

    to_idx = len(step_ids)
    if 0 <= to_row < len(panel._row_meta):
        target_meta = panel._row_meta[to_row]
        if target_meta.get("kind") == "stage_header":
            last_step_in_stage = -1
            for r in range(to_row + 1, len(panel._row_meta)):
                if panel._row_meta[r].get("kind") == "stage_header":
                    break
                sid = panel._row_meta[r].get("step_id")
                if sid and sid in step_ids:
                    last_step_in_stage = step_ids.index(sid)
            if last_step_in_stage >= 0:
                to_idx = last_step_in_stage + 1
            else:
                prev_steps = 0
                for r in range(0, to_row):
                    if panel._row_meta[r].get("kind") == "step":
                        prev_steps += 1
                to_idx = prev_steps
        else:
            sid = target_meta.get("step_id")
            if sid and sid in step_ids:
                to_idx = step_ids.index(sid)

    step_ids.pop(from_idx)
    if to_idx > len(step_ids):
        to_idx = len(step_ids)
    step_ids.insert(to_idx, moved_step_id)

    if not panel._apply_orders_and_stage_update(moved_step_id, target_stage_uid, step_ids):
        return

    QTimer.singleShot(0, lambda: panel._refresh_after_drag(moved_step_id))


def refresh_after_drag(panel, moved_step_id: int):
    panel.load_steps(panel._workflow_id)
    panel.steps_changed.emit()
    panel.select_step(moved_step_id)
    panel._notify_status("步骤已移动。")
