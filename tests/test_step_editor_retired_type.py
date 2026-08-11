# -*- coding: utf-8 -*-
"""step_editor 退役类型（历史 excel/powerbi 及未知历史类型）加载/保存安全测试。

H3 覆盖：
1. 加载退役类型步骤 → 禁用占位项展示 + 下拉当前值=步骤真实类型 + 保存类型不变（无迁移提示）；
2. 先 python 后 powerbi 再 python → 下拉不残留上一类型；
3. 未知历史类型 → 加载期动态补禁用占位项兜底；
4. 主动迁移（退役类型 → 可选类型）允许保存且提示迁移，二次保存不重复提示；
5. clear() 复位 _loaded_step_type 与下拉当前值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication

import ui.step_editor as step_editor_mod
import ui.step_editor_io as step_editor_io_mod
from ui.step_editor import StepEditorPanel


def _step(step_id: int = 1, step_type: str = "python", script: str = "C:/a.py"):
    return SimpleNamespace(
        id=step_id,
        workflow_id=7,
        name="历史步骤",
        step_type=step_type,
        script_path=script,
        args="",
        saved_run_args="",
        cwd="",
        chart_theme="",
        timeout_seconds=None,
        retry_count=0,
        is_gate=False,
        skip_on_success=False,
        stage_uid="s1",
        uid=f"step-{step_id}",
        order=0,
        get_output_paths=lambda: [],
        get_depends_on=lambda: [],
    )


def _patch_db(monkeypatch, step) -> None:
    """桩掉 load_step/save_step 涉及的 database 函数（模块级导入按命名空间分别桩）。"""
    for mod in (step_editor_mod, step_editor_io_mod):
        monkeypatch.setattr(mod, "get_step_by_id", lambda _sid: step)
        monkeypatch.setattr(mod, "get_steps_by_workflow", lambda _wid: [])
        monkeypatch.setattr(mod, "list_stages", lambda _wid: [])
        monkeypatch.setattr(mod, "list_workflows", lambda: [])
    # get_stage_order_map 仅 step_editor.py 命名空间导入
    monkeypatch.setattr(step_editor_mod, "get_stage_order_map", lambda _wid: {})


def _make_panel(monkeypatch, step) -> StepEditorPanel:
    QApplication.instance() or QApplication([])
    panel = StepEditorPanel()
    panel._dark = False
    panel._edit_enabled = True
    _patch_db(monkeypatch, step)
    return panel


def _install_save(monkeypatch, panel):
    """桩掉保存链路；返回 (saved_kwargs, notify_messages)。"""
    saved = {}
    messages = []
    monkeypatch.setattr(step_editor_mod, "update_step", lambda _step_id, **kw: saved.update(kw))
    monkeypatch.setattr(os.path, "exists", lambda _path: True)
    panel._notify_status = lambda msg: messages.append(msg)
    return saved, messages


def _assert_retired_placeholder(panel, step_type: str) -> int:
    """断言存在禁用的「已停用」占位项，返回其 index。"""
    idx = panel.combo_type.findData(step_type)
    assert idx >= 0, f"应存在 {step_type} 占位项"
    assert "已停用" in panel.combo_type.itemText(idx), panel.combo_type.itemText(idx)
    assert not panel.combo_type.model().item(idx).isEnabled(), "占位项必须禁用"
    return idx


def test_load_retired_type_step_placeholder_and_save_keeps_type(monkeypatch):
    panel = _make_panel(monkeypatch, _step(step_type="excel_powerquery", script="C:/old.xlsx"))
    try:
        panel.load_step(1)

        # 占位项展示 + 当前值=加载步骤真实类型（不残留其他类型）
        _assert_retired_placeholder(panel, "excel_powerquery")
        assert panel.combo_type.currentData() == "excel_powerquery"
        assert panel._loaded_step_type == "excel_powerquery"

        # 保存：忠实读取 combo，类型不变；加载类型==保存类型 → 不触发迁移提示
        saved, messages = _install_save(monkeypatch, panel)
        assert panel.save_step() is True
        assert saved["step_type"] == "excel_powerquery"
        assert messages == ["已保存步骤配置。"]
    finally:
        panel.close()


def test_python_then_powerbi_then_python_no_residue(monkeypatch):
    panel = _make_panel(monkeypatch, _step(step_id=1, step_type="python"))
    try:
        panel.load_step(1)
        assert panel.combo_type.currentData() == "python"

        # 切到历史 powerbi 步骤
        monkeypatch.setattr(
            step_editor_io_mod, "get_step_by_id",
            lambda _sid: _step(step_id=2, step_type="powerbi_refresh", script="C:/b.pbix"),
        )
        panel.load_step(2)
        assert panel.combo_type.currentData() == "powerbi_refresh"
        assert panel._loaded_step_type == "powerbi_refresh"
        _assert_retired_placeholder(panel, "powerbi_refresh")

        # 再切回 python：当前值跟随新步骤，不残留 powerbi
        monkeypatch.setattr(
            step_editor_io_mod, "get_step_by_id",
            lambda _sid: _step(step_id=1, step_type="python"),
        )
        panel.load_step(1)
        assert panel.combo_type.currentData() == "python"
        assert panel._loaded_step_type == "python"
    finally:
        panel.close()


def test_unknown_historical_type_dynamic_fallback(monkeypatch):
    panel = _make_panel(monkeypatch, _step(step_type="legacy_shell", script="C:/x.sh"))
    try:
        panel.load_step(1)

        # 未知历史类型：构建期没有占位项，加载期动态补禁用的占位项并选中
        _assert_retired_placeholder(panel, "legacy_shell")
        assert "legacy_shell" in panel.combo_type.itemText(panel.combo_type.findData("legacy_shell"))
        assert panel.combo_type.currentData() == "legacy_shell"
        assert panel._loaded_step_type == "legacy_shell"
    finally:
        panel.close()


def test_active_migration_allowed_with_prompt_once(monkeypatch):
    panel = _make_panel(monkeypatch, _step(step_type="excel_powerquery", script="C:/old.xlsx"))
    try:
        panel.load_step(1)
        assert panel.combo_type.currentData() == "excel_powerquery"

        # 主动迁移：改选 Python
        python_idx = panel.combo_type.findData("python")
        assert python_idx >= 0
        panel.combo_type.setCurrentIndex(python_idx)

        saved, messages = _install_save(monkeypatch, panel)
        assert panel.save_step() is True
        assert saved["step_type"] == "python"
        assert messages == ["类型已从已停用类型Excel迁移为Python。"]
        # 保存成功后加载类型同步为保存类型
        assert panel._loaded_step_type == "python"

        # 二次保存：不再重复迁移提示
        assert panel.save_step() is True
        assert messages[1] == "已保存步骤配置。"
    finally:
        panel.close()


def test_clear_resets_loaded_step_type(monkeypatch):
    panel = _make_panel(monkeypatch, _step(step_type="powerbi_refresh", script="C:/b.pbix"))
    try:
        panel.load_step(1)
        assert panel.combo_type.currentData() == "powerbi_refresh"
        assert panel._loaded_step_type == "powerbi_refresh"

        panel.clear()
        assert panel._loaded_step_type is None
        # 下拉回到第一个可选类型（python）；占位项仍在但未被选中
        assert panel.combo_type.currentData() == "python"
        idx = panel.combo_type.findData("powerbi_refresh")
        assert idx >= 0
        assert panel.combo_type.currentIndex() != idx
    finally:
        panel.close()
