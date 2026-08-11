# -*- coding: utf-8 -*-
"""工作流 JSON 导入导出。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session, selectinload

from database_import_validation import (
    EXPORT_SCHEMA_VERSION,
    mark_risky_import_paths,
    validate_import_payload,
)
from import_export_security import assert_no_plain_webhook_secrets
from models import Step, WebhookConfig, Workflow, WorkflowStage
from webhook_url_policy import (
    is_masked_webhook_url,
    is_valid_dingtalk_webhook_url,
    mask_webhook_url_for_log,
)

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """JSON 导入结果。

    Attributes:
        imported_count: 实际新建的工作流数量。
        warnings: 面向用户的中文告警明细（脱敏 webhook 跳过创建、
            通知已启用但未绑定可用机器人、工作流 UID 重复跳过等），
            供 CLI / UI 展示，避免导入问题只留在日志里被静默吞掉。
    """

    imported_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _workflow_import_uid(wf_data: dict, generate_uid: Callable[[], str]) -> str:
    uid = (wf_data.get("id") or "").strip()
    return uid or generate_uid()


def import_from_json_impl(
    json_path: Path,
    *,
    get_session: Callable[[], object],
    generate_uid: Callable[[], str],
    ensure_default_stage: Callable[[Session, int], WorkflowStage],
    masked_webhook_url: str,
) -> ImportResult:
    """从 JSON 文件导入工作流，返回导入数量与告警明细。"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = validate_import_payload(json.load(f))

    webhooks_data = data.get("webhooks", [])
    workflows_data = data.get("workflows", [])
    result = ImportResult()

    with get_session() as session:
        webhook_name_to_id, masked_skipped_names = _import_webhooks(
            session,
            webhooks_data,
            masked_webhook_url=masked_webhook_url,
            warnings=result.warnings,
        )

        existing_uids = {
            uid for (uid,) in session.query(Workflow.uid).all()
        }

        for wf_data in workflows_data:
            workflow_uid = _workflow_import_uid(wf_data, generate_uid)
            if workflow_uid in existing_uids:
                logger.warning("导入工作流 UID 已存在，跳过: uid=%r", workflow_uid)
                result.warnings.append(
                    f"工作流「{wf_data.get('name') or workflow_uid}」UID 已存在（{workflow_uid}），已跳过导入"
                )
                continue

            workflow = _build_workflow(wf_data, workflow_uid)
            mark_risky_import_paths(workflow, wf_data)
            _apply_notify_config(
                session,
                workflow,
                wf_data,
                webhook_name_to_id,
                masked_skipped_names=masked_skipped_names,
                warnings=result.warnings,
            )

            session.add(workflow)
            session.flush()

            stage_uid_set, stage_uid_map = _import_stages(
                session,
                workflow.id,
                wf_data.get("stages", []),
                generate_uid,
                ensure_default_stage,
            )
            default_stage = ensure_default_stage(session, workflow.id)
            stage_uid_set.add(default_stage.uid)
            _import_steps(
                session,
                workflow.id,
                wf_data.get("steps", []),
                stage_uid_set,
                stage_uid_map,
                default_stage.uid,
                generate_uid,
            )
            result.imported_count += 1
            existing_uids.add(workflow_uid)

        session.commit()

    return result


def export_to_json_impl(
    json_path: Path,
    workflow_ids: Optional[list[int]] = None,
    include_secrets: bool = False,
    *,
    get_session: Callable[[], object],
    masked_webhook_url: str,
) -> None:
    """导出工作流到 JSON 文件。"""
    data = {
        "version": EXPORT_SCHEMA_VERSION,
        "secrets_included": bool(include_secrets),
        "webhooks": [],
        "workflows": [],
    }

    with get_session() as session:
        workflow_query = session.query(Workflow).options(
            selectinload(Workflow.stages),
            selectinload(Workflow.steps),
        )
        if workflow_ids:
            workflow_query = workflow_query.filter(Workflow.id.in_(list(workflow_ids)))
        workflows = workflow_query.order_by(Workflow.created_at.desc()).all()

        webhook_ids = _collect_referenced_webhook_ids(workflows)
        webhook_query = session.query(WebhookConfig).order_by(WebhookConfig.name)
        if workflow_ids:
            webhooks = webhook_query.filter(WebhookConfig.id.in_(webhook_ids)).all() if webhook_ids else []
        else:
            webhooks = webhook_query.all()
        data["webhooks"] = [
            {
                "name": wh.name,
                "webhook_url": wh.webhook_url if include_secrets else masked_webhook_url,
                "webhook_url_masked": not include_secrets,
                "keyword": wh.keyword or "",
                "description": wh.description or "",
            }
            for wh in webhooks
        ]
        webhook_map = {wh.id: wh.name for wh in webhooks}

        for workflow in workflows:
            data["workflows"].append(_export_workflow(workflow, webhook_map))

    if not include_secrets:
        assert_no_plain_webhook_secrets(data)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _collect_referenced_webhook_ids(workflows: list[Workflow]) -> set[int]:
    webhook_ids: set[int] = set()
    for workflow in workflows:
        notify = workflow.get_notify_config()
        if not isinstance(notify, dict):
            continue
        webhook_id = notify.get("webhook_id")
        if isinstance(webhook_id, int):
            webhook_ids.add(webhook_id)
        elif isinstance(webhook_id, str) and webhook_id.isdigit():
            webhook_ids.add(int(webhook_id))
    return webhook_ids


def _import_webhooks(
    session: Session,
    webhooks_data,
    *,
    masked_webhook_url: str,
    warnings: list[str],
) -> tuple[dict[str, int], set[str]]:
    """导入 webhook 列表。

    Returns:
        (名称 -> 本机 webhook id 映射, 因脱敏且本机无同名配置而被跳过创建的名称集合)
    """
    webhook_name_to_id: dict[str, int] = {}
    masked_skipped_names: set[str] = set()
    if not isinstance(webhooks_data, list) or not webhooks_data:
        return webhook_name_to_id, masked_skipped_names

    for wh in webhooks_data:
        if not isinstance(wh, dict):
            continue
        name = (wh.get("name") or "").strip()
        url = (wh.get("webhook_url") or "").strip()
        url_masked = bool(wh.get("webhook_url_masked")) or is_masked_webhook_url(url, masked_webhook_url)
        if not name:
            continue
        keyword = (wh.get("keyword") or "").strip()
        desc = (wh.get("description") or "").strip()
        existing_matches = session.query(WebhookConfig).filter(WebhookConfig.name == name).all()
        if len(existing_matches) > 1:
            raise ValueError(f"Webhook 名称重复，无法确定绑定: {name}")
        existing = existing_matches[0] if existing_matches else None

        if url_masked:
            if existing:
                _update_existing_masked_webhook(session, existing, keyword, desc)
                webhook_name_to_id[name] = existing.id
            else:
                logger.info("导入 webhook 已脱敏且本机无同名配置，跳过创建: name=%r", name)
                masked_skipped_names.add(name)
                warnings.append(
                    f"webhook「{name}」的 URL 已脱敏且本机无同名配置，已跳过创建；"
                    "如需通知请在本机重新配置同名机器人"
                )
            continue

        if not url:
            continue
        if not is_valid_dingtalk_webhook_url(url):
            raise ValueError(f"Webhook URL 必须是钉钉机器人地址: {name}")
        if existing:
            _update_existing_webhook(session, existing, name, url, keyword, desc)
            webhook_name_to_id[name] = existing.id
        else:
            item = WebhookConfig(
                name=name,
                webhook_url=url,
                keyword=keyword or None,
                description=desc or None,
            )
            session.add(item)
            session.flush()
            webhook_name_to_id[name] = item.id

    return webhook_name_to_id, masked_skipped_names


def _update_existing_masked_webhook(
    session: Session,
    existing: WebhookConfig,
    keyword: str,
    desc: str,
) -> None:
    overrides = []
    if (existing.keyword or None) != (keyword or None):
        overrides.append("keyword")
    if (existing.description or None) != (desc or None):
        overrides.append("description")
    if overrides:
        logger.info(
            "导入脱敏 webhook，保留本机 URL: name=%r, 覆盖字段=%s",
            existing.name,
            ",".join(overrides),
        )
    existing.keyword = keyword or None
    existing.description = desc or None
    session.flush()


def _update_existing_webhook(
    session: Session,
    existing: WebhookConfig,
    name: str,
    url: str,
    keyword: str,
    desc: str,
) -> None:
    if existing.webhook_url != url:
        logger.warning(
            "导入 webhook 检测到同名不同 URL，保留本机配置并继续绑定: name=%r, local=%r, imported=%r",
            name,
            mask_webhook_url_for_log(existing.webhook_url),
            mask_webhook_url_for_log(url),
        )
        _update_existing_masked_webhook(session, existing, keyword, desc)
        return
    overrides = []
    if existing.webhook_url != url:
        overrides.append("webhook_url")
    if (existing.keyword or None) != (keyword or None):
        overrides.append("keyword")
    if (existing.description or None) != (desc or None):
        overrides.append("description")
    if overrides:
        logger.info("导入 webhook 覆盖现有同名记录: name=%r, 覆盖字段=%s", name, ",".join(overrides))
    existing.webhook_url = url
    existing.keyword = keyword or None
    existing.description = desc or None
    session.flush()


def _build_workflow(wf_data: dict, workflow_uid: str) -> Workflow:
    return Workflow(
        uid=workflow_uid,
        name=wf_data.get("name", "未命名工作流"),
        description=wf_data.get("description") or "",
        chart_theme=wf_data.get("chart_theme", "default"),
        parallel_enabled=wf_data.get("parallel", {}).get("enabled", False),
        max_workers=wf_data.get("parallel", {}).get("max_workers", 2),
    )


def _apply_notify_config(
    session: Session,
    workflow: Workflow,
    wf_data: dict,
    webhook_name_to_id: dict[str, int],
    *,
    masked_skipped_names: set[str],
    warnings: list[str],
) -> None:
    if "notify" not in wf_data:
        return
    notify = wf_data.get("notify") or {}
    if isinstance(notify, str):
        try:
            notify = json.loads(notify)
        except json.JSONDecodeError:
            notify = {}
    if not isinstance(notify, dict):
        notify = {}

    wh_name = (notify.get("webhook_name") or "").strip()
    if wh_name and wh_name in webhook_name_to_id:
        notify["webhook_id"] = webhook_name_to_id[wh_name]
    elif wh_name:
        matches = session.query(WebhookConfig).filter(WebhookConfig.name == wh_name).all()
        if len(matches) > 1:
            raise ValueError(f"Webhook 名称重复，无法确定绑定: {wh_name}")
        notify["webhook_id"] = matches[0].id if matches else None
    else:
        if notify.get("webhook_id"):
            logger.warning(
                "导入通知配置忽略跨环境裸 webhook_id: workflow=%r, webhook_id=%r",
                wf_data.get("name"),
                notify.get("webhook_id"),
            )
        notify["webhook_id"] = None

    if notify.get("enabled") and not notify.get("webhook_id"):
        # M2: 通知启用但没有可用机器人时运行期会静默不发送，必须把原因显式告知用户
        workflow_name = workflow.name or wf_data.get("name") or workflow.uid
        if wh_name and wh_name in masked_skipped_names:
            reason = f"webhook「{wh_name}」被脱敏跳过"
        elif wh_name:
            reason = f"本机不存在名为「{wh_name}」的机器人"
        else:
            reason = "导入数据未提供可用的机器人绑定"
        warnings.append(
            f"工作流「{workflow_name}」通知已启用但未绑定可用机器人（{reason}），通知将不会发送"
        )
    workflow.set_notify_config(notify)


def _import_stages(
    session: Session,
    workflow_id: int,
    stages_data,
    generate_uid: Callable[[], str],
    ensure_default_stage: Callable[[Session, int], WorkflowStage],
) -> tuple[set[str], dict[str, str]]:
    stage_uid_set: set[str] = set()
    stage_uid_map: dict[str, str] = {}
    if isinstance(stages_data, list) and stages_data:
        for idx, st in enumerate(stages_data):
            if not isinstance(st, dict):
                continue
            import_uid = (st.get("uid") or "").strip() or generate_uid()
            st_uid = import_uid
            st_name = (st.get("name") or "").strip() or f"阶段 {idx + 1}"
            st_order = int(st.get("order") if st.get("order") is not None else idx)
            st_color = (st.get("color") or None) or None
            if session.query(WorkflowStage).filter(WorkflowStage.uid == st_uid).first():
                st_uid = generate_uid()
            stage_uid_map[import_uid] = st_uid
            session.add(
                WorkflowStage(
                    uid=st_uid,
                    workflow_id=workflow_id,
                    name=st_name,
                    order=st_order,
                    color=st_color,
                )
            )
            stage_uid_set.add(st_uid)
        session.flush()
    else:
        stage_uid_set.add(ensure_default_stage(session, workflow_id).uid)
    return stage_uid_set, stage_uid_map


def _import_steps(
    session: Session,
    workflow_id: int,
    steps_data,
    stage_uid_set: set[str],
    stage_uid_map: dict[str, str],
    default_stage_uid: str,
    generate_uid: Callable[[], str],
) -> None:
    for idx, step_data in enumerate(steps_data):
        stage_uid_in = (step_data.get("stage_uid") or "").strip()
        stage_uid = stage_uid_map.get(stage_uid_in, stage_uid_in) if stage_uid_in else default_stage_uid
        if stage_uid not in stage_uid_set:
            stage_uid = default_stage_uid
        step = Step(
            workflow_id=workflow_id,
            uid=step_data.get("id", generate_uid()),
            order=idx,
            name=step_data.get("name", f"步骤 {idx + 1}"),
            stage_uid=stage_uid,
            step_type=step_data.get("step_type", "python"),
            script_path=step_data.get("script", ""),
            cwd=step_data.get("cwd", ""),
            is_gate=step_data.get("is_gate", False),
            is_parallel=step_data.get("is_parallel", False),
            chart_theme=step_data.get("chart_theme", ""),
            timeout_seconds=step_data.get("timeout_seconds"),
            retry_count=int(step_data.get("retry_count") or 0),
            skip_on_success=bool(step_data.get("skip_on_success", False)),
        )
        args = step_data.get("args", [])
        if args:
            step.set_args(args)
        saved_run_args = step_data.get("saved_run_args", [])
        if saved_run_args:
            step.set_saved_run_args(saved_run_args)
        deps = step_data.get("depends_on", [])
        if deps:
            step.set_depends_on(deps)
        # ROI-2: 显式输出声明；缺省（旧 JSON）保持 NULL
        output_paths = step_data.get("output_paths", [])
        if output_paths:
            step.set_output_paths(output_paths)
        session.add(step)


def serialize_workflow_payload(workflow: Workflow, webhook_map: Optional[dict[int, str]] = None) -> dict:
    webhook_map = webhook_map or {}
    notify = workflow.get_notify_config()
    if not isinstance(notify, dict):
        notify = {}
    else:
        notify = dict(notify)
    wh_id = notify.get("webhook_id")
    if wh_id and wh_id in webhook_map:
        notify["webhook_name"] = webhook_map[wh_id]

    return {
        "id": workflow.uid,
        "name": workflow.name,
        "description": workflow.description or "",
        "chart_theme": workflow.chart_theme,
        "parallel": {
            "enabled": workflow.parallel_enabled,
            "max_workers": workflow.max_workers,
        },
        "notify": notify,
        "stages": _export_stages(workflow),
        "steps": _export_steps(workflow),
    }


def _export_workflow(workflow: Workflow, webhook_map: dict[int, str]) -> dict:
    return serialize_workflow_payload(workflow, webhook_map)


def _export_stages(workflow: Workflow) -> list[dict]:
    return [
        {
            "uid": st.uid,
            "name": st.name,
            "order": int(st.order or 0),
            "color": st.color or "",
        }
        for st in sorted(workflow.stages, key=lambda s: s.order or 0)
    ]


def _export_steps(workflow: Workflow) -> list[dict]:
    return [
        {
            "id": step.uid,
            "name": step.name,
            "stage_uid": step.stage_uid or "",
            "step_type": step.step_type,
            "script": step.script_path or "",
            "args": step.get_args(),
            "saved_run_args": step.get_saved_run_args(),
            "cwd": step.cwd or "",
            "is_gate": step.is_gate,
            "is_parallel": step.is_parallel,
            "depends_on": step.get_depends_on(),
            "chart_theme": step.chart_theme or "",
            "timeout_seconds": step.timeout_seconds,
            "retry_count": step.retry_count,
            "skip_on_success": step.skip_on_success,
            # ROI-2: 显式输出声明（schema version 不变：可选字段，旧 JSON 缺省合法）
            "output_paths": step.get_output_paths(),
        }
        for step in sorted(workflow.steps, key=lambda s: s.order)
    ]
