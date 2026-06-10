# -*- coding: utf-8 -*-
"""数据库 update_* API 的字段白名单。"""

from __future__ import annotations

WORKFLOW_UPDATE_FIELDS = {
    "name",
    "description",
    "chart_theme",
    "parallel_enabled",
    "max_workers",
    "watch_enabled",
    "watch_mode",
    "watch_folders",
    "cooldown_seconds",
    "settle_seconds",
    "log_retention_days",
    "single_script_enabled",
    "single_script_type",
    "single_script_path",
    "single_script_args",
    "single_script_cwd",
    "notify_config",
}
STAGE_UPDATE_FIELDS = {"name", "order", "color"}
STEP_UPDATE_FIELDS = {
    "order",
    "name",
    "stage_uid",
    "step_type",
    "script_path",
    "args",
    "cwd",
    "is_gate",
    "is_parallel",
    "depends_on",
    "chart_theme",
    "timeout_seconds",
    "retry_count",
    "skip_on_success",
    "output_paths",
}
RUN_HISTORY_UPDATE_FIELDS = {
    "status",
    "reason",
    "start_time",
    "end_time",
    "log_dir",
    "run_mode",
    "run_mode_param",
    "trace_id",
    "parent_run_id",
    "notify_status",
}
STEP_LOG_UPDATE_FIELDS = {
    "order",
    "status",
    "exit_code",
    "error_message",
    "start_time",
    "end_time",
    "stdout_path",
    "stderr_path",
}
WEBHOOK_UPDATE_FIELDS = {"name", "webhook_url", "keyword", "description"}


def validate_update_fields(model_name: str, kwargs: dict, allowed_fields: set[str]) -> None:
    unknown = sorted(set(kwargs) - allowed_fields)
    if unknown:
        raise ValueError(f"{model_name} 不支持更新字段: {', '.join(unknown)}")
