# -*- coding: utf-8 -*-
"""Pure validation helpers for workflow JSON imports."""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath, PureWindowsPath

from models import Workflow

logger = logging.getLogger(__name__)

EXPORT_SCHEMA_VERSION = 1
_WATCH_MODES = {"any_change", "all_folders_updated_since_success"}
_EXECUTABLE_TYPES = {"python", "bat", "excel_powerquery", "powerbi_refresh", "sub_workflow"}
_IMPORTED_PATH_WARNING = "[导入提示] 此工作流包含绝对路径或上级目录引用，首次运行前请确认脚本和工作目录来源可信。"
_IMPORTED_PATH_CONFIRMED = "[已确认] 用户已确认导入路径安全。"
_NOTIFY_SCHEMA_FIELDS = {
    "enabled",
    "webhook_id",
    "webhook_name",
    "message_template",
}


def normalize_single_script_args(value) -> list[str]:
    """将单脚本参数统一序列化为字符串数组。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
        if decoded is None:
            return []
        return [str(decoded)]
    return [str(value)]


def validate_import_payload(data) -> dict:
    data = _expect_mapping(data, "$")
    version = data.get("version")
    if version != EXPORT_SCHEMA_VERSION:
        raise _json_error(
            "$.version",
            f"不支持的导入版本: {version!r}，当前仅支持 {EXPORT_SCHEMA_VERSION}",
        )
    webhooks = _expect_optional_list(data, "webhooks", "$")
    workflows = _expect_optional_list(data, "workflows", "$")
    _validate_webhooks(webhooks)
    _validate_workflows(workflows)
    return data


def mark_risky_import_paths(workflow: Workflow, wf_data: dict) -> None:
    if not _workflow_has_risky_import_paths(wf_data):
        return
    workflow.description = _append_import_path_warning(workflow.description or "")
    logger.warning(
        "导入工作流包含需复核的脚本路径或工作目录: uid=%r, name=%r",
        workflow.uid,
        workflow.name,
    )


def workflow_has_unconfirmed_risky_paths(workflow) -> bool:
    """检查工作流是否包含未经用户确认的 risky import path 标记。

    用于运行前安全检查：若 description 包含导入告警但不含确认标记，
    则运行方应弹窗要求用户确认后才允许执行。
    """
    desc = getattr(workflow, "description", None) or ""
    return _IMPORTED_PATH_WARNING in desc and _IMPORTED_PATH_CONFIRMED not in desc


def confirm_risky_paths(workflow: Workflow) -> None:
    """用户确认导入路径安全后调用，追加确认标记到 description。"""
    desc = workflow.description or ""
    if _IMPORTED_PATH_CONFIRMED not in desc:
        workflow.description = f"{desc}\n{_IMPORTED_PATH_CONFIRMED}"


def _json_error(path: str, message: str) -> ValueError:
    return ValueError(f"{path}: {message}")


def _expect_mapping(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise _json_error(path, "必须是对象")
    return value


def _expect_optional_mapping(parent: dict, key: str, path: str) -> dict:
    value = parent.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _json_error(f"{path}.{key}", "必须是对象")
    return value


def _expect_optional_list(parent: dict, key: str, path: str) -> list:
    value = parent.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise _json_error(f"{path}.{key}", "必须是数组")
    return value


def _expect_int_if_present(parent: dict, key: str, path: str, *, allow_none: bool = False) -> None:
    if key not in parent:
        return
    value = parent.get(key)
    if allow_none and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise _json_error(f"{path}.{key}", "必须是整数")


def _expect_bool_if_present(parent: dict, key: str, path: str) -> None:
    if key not in parent:
        return
    if not isinstance(parent.get(key), bool):
        raise _json_error(f"{path}.{key}", "必须是布尔值")


def _expect_str_if_present(parent: dict, key: str, path: str, *, allow_none: bool = True) -> None:
    if key not in parent:
        return
    value = parent.get(key)
    if allow_none and value is None:
        return
    if not isinstance(value, str):
        raise _json_error(f"{path}.{key}", "必须是字符串")


def _expect_str_list_if_present(parent: dict, key: str, path: str) -> None:
    values = _expect_optional_list(parent, key, path)
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise _json_error(f"{path}.{key}[{index}]", "必须是字符串")


def _expect_supported_executable_type_if_present(parent: dict, key: str, path: str) -> None:
    if key not in parent:
        return
    value = parent.get(key)
    if not isinstance(value, str):
        raise _json_error(f"{path}.{key}", "必须是字符串")
    if value not in _EXECUTABLE_TYPES:
        supported = ", ".join(sorted(_EXECUTABLE_TYPES))
        raise _json_error(f"{path}.{key}", f"不支持的执行类型: {value!r}（支持: {supported}）")


def _expect_watch_mode_if_present(parent: dict, key: str, path: str) -> None:
    if key not in parent:
        return
    value = parent.get(key)
    if not isinstance(value, str):
        raise _json_error(f"{path}.{key}", "必须是字符串")
    if value not in _WATCH_MODES:
        raise _json_error(f"{path}.{key}", f"不支持的监听模式: {value!r}")


def _validate_webhooks(webhooks: list) -> None:
    for index, webhook in enumerate(webhooks):
        webhook_path = f"$.webhooks[{index}]"
        webhook = _expect_mapping(webhook, webhook_path)
        _expect_str_if_present(webhook, "name", webhook_path)
        _expect_str_if_present(webhook, "webhook_url", webhook_path)
        _expect_bool_if_present(webhook, "webhook_url_masked", webhook_path)
        _expect_str_if_present(webhook, "keyword", webhook_path)
        _expect_str_if_present(webhook, "description", webhook_path)


def _validate_workflows(workflows: list) -> None:
    for wf_index, workflow in enumerate(workflows):
        wf_path = f"$.workflows[{wf_index}]"
        workflow = _expect_mapping(workflow, wf_path)
        _expect_str_if_present(workflow, "id", wf_path)
        _expect_str_if_present(workflow, "name", wf_path)
        _expect_str_if_present(workflow, "description", wf_path)
        _validate_workflow_config(workflow, wf_path)
        _validate_stages(_expect_optional_list(workflow, "stages", wf_path), wf_path)
        _validate_steps(_expect_optional_list(workflow, "steps", wf_path), wf_path)


def _validate_workflow_config(workflow: dict, wf_path: str) -> None:
    parallel = _expect_optional_mapping(workflow, "parallel", wf_path)
    watch = _expect_optional_mapping(workflow, "watch", wf_path)
    single_script = _expect_optional_mapping(workflow, "single_script", wf_path)
    _expect_bool_if_present(parallel, "enabled", f"{wf_path}.parallel")
    _expect_int_if_present(parallel, "max_workers", f"{wf_path}.parallel")
    _expect_bool_if_present(watch, "enabled", f"{wf_path}.watch")
    _expect_watch_mode_if_present(watch, "mode", f"{wf_path}.watch")
    _expect_int_if_present(watch, "cooldown_seconds", f"{wf_path}.watch")
    _expect_int_if_present(watch, "settle_seconds", f"{wf_path}.watch")
    _expect_str_list_if_present(watch, "folders", f"{wf_path}.watch")
    _expect_bool_if_present(single_script, "enabled", f"{wf_path}.single_script")
    _expect_supported_executable_type_if_present(single_script, "type", f"{wf_path}.single_script")
    _expect_str_if_present(single_script, "path", f"{wf_path}.single_script")
    _expect_str_if_present(single_script, "cwd", f"{wf_path}.single_script")
    if "notify" in workflow:
        _validate_notify_value(workflow.get("notify"), f"{wf_path}.notify")


def _validate_notify_mapping(value: dict, path: str) -> None:
    for key in value:
        if key not in _NOTIFY_SCHEMA_FIELDS:
            raise _json_error(f"{path}.{key}", "未知字段")
    _expect_bool_if_present(value, "enabled", path)
    _expect_str_if_present(value, "webhook_name", path)
    _expect_int_if_present(value, "webhook_id", path, allow_none=True)
    _expect_str_if_present(value, "message_template", path)


def _validate_notify_value(value, path: str) -> None:
    if value is None or isinstance(value, dict):
        if isinstance(value, dict):
            _validate_notify_mapping(value, path)
        return
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _json_error(path, "必须是对象或合法 JSON 对象字符串") from exc
        if isinstance(decoded, dict):
            _validate_notify_mapping(decoded, path)
            return
    raise _json_error(path, "必须是对象")


def _validate_stages(stages: list, wf_path: str) -> None:
    for stage_index, stage in enumerate(stages):
        stage_path = f"{wf_path}.stages[{stage_index}]"
        stage = _expect_mapping(stage, stage_path)
        _expect_int_if_present(stage, "order", stage_path)


def _validate_steps(steps: list, wf_path: str) -> None:
    for step_index, step in enumerate(steps):
        step_path = f"{wf_path}.steps[{step_index}]"
        step = _expect_mapping(step, step_path)
        _expect_str_if_present(step, "id", step_path)
        _expect_str_if_present(step, "name", step_path)
        _expect_str_if_present(step, "stage_uid", step_path)
        _expect_supported_executable_type_if_present(step, "step_type", step_path)
        _expect_str_if_present(step, "script", step_path)
        _expect_str_if_present(step, "cwd", step_path)
        _expect_int_if_present(step, "timeout_seconds", step_path, allow_none=True)
        _expect_int_if_present(step, "retry_count", step_path)
        _expect_bool_if_present(step, "is_gate", step_path)
        _expect_bool_if_present(step, "is_parallel", step_path)
        _expect_bool_if_present(step, "skip_on_success", step_path)
        _expect_optional_list(step, "args", step_path)
        _expect_str_list_if_present(step, "saved_run_args", step_path)
        _expect_optional_list(step, "depends_on", step_path)
        _expect_str_list_if_present(step, "output_paths", step_path)


def _looks_risky_import_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    raw = value.strip()
    try:
        windows_path = PureWindowsPath(raw)
        posix_path = PurePosixPath(raw)
    except (TypeError, ValueError):
        return True
    if windows_path.is_absolute() or posix_path.is_absolute():
        return True
    return ".." in windows_path.parts or ".." in posix_path.parts


def _workflow_has_risky_import_paths(wf_data: dict) -> bool:
    single_script = wf_data.get("single_script", {})
    if _looks_risky_import_path(single_script.get("path")) or _looks_risky_import_path(single_script.get("cwd")):
        return True
    for step_data in wf_data.get("steps", []):
        if _looks_risky_import_path(step_data.get("script")) or _looks_risky_import_path(step_data.get("cwd")):
            return True
    return False


def _append_import_path_warning(description: str) -> str:
    description = description or ""
    if _IMPORTED_PATH_WARNING in description:
        return description
    return f"{description}\n\n{_IMPORTED_PATH_WARNING}" if description else _IMPORTED_PATH_WARNING
