# -*- coding: utf-8 -*-
"""Pure validation helpers for workflow JSON imports."""

from __future__ import annotations

import json
import logging

from models import Workflow

import risk_path_review

logger = logging.getLogger(__name__)

EXPORT_SCHEMA_VERSION = 1
_EXECUTABLE_TYPES = {"python", "bat", "sub_workflow"}
_NOTIFY_SCHEMA_FIELDS = {
    "enabled",
    "webhook_id",
    "webhook_name",
    "message_template",
}


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
    """R1: 导入含风险路径的工作流强制 review_required=1、digest 空。

    - 风险路径 = 活动步骤的绝对 script_path/cwd + `..` 逃逸路径（退役字段不参与）。
    - 忽略 JSON 中同名内部字段（risky_paths_* 永不采信导入值）。
    - 不再向 description 追加旧文本标记（旧文本已不参与运行判定）。
    """
    records = risk_path_review.collect_risk_paths(wf_data.get("steps", []))
    if not records:
        return
    workflow.risky_paths_review_required = 1
    workflow.risky_paths_confirmed_digest = None
    logger.warning(
        "导入工作流包含需复核的脚本路径或工作目录: uid=%r, name=%r",
        workflow.uid,
        workflow.name,
    )


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
    _expect_bool_if_present(parallel, "enabled", f"{wf_path}.parallel")
    _expect_int_if_present(parallel, "max_workers", f"{wf_path}.parallel")
    # 退役字段(watch / single_script):旧 JSON 允许存在但明确忽略,
    # 不做形状强校验、不重新导出、其路径不参与风险路径计算。
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
