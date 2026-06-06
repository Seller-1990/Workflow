# -*- coding: utf-8 -*-
"""工作流 JSON 导入导出。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session, selectinload

from models import Step, WebhookConfig, Workflow, WorkflowStage

logger = logging.getLogger(__name__)


def is_masked_webhook_url(value: str | None, masked_value: str) -> bool:
    """判断导入值是否为脱敏占位符。"""
    text = (value or "").strip()
    if not text:
        return False
    return text == masked_value or text.lower() in {"<masked>", "masked", "***"}


def import_from_json_impl(
    json_path: Path,
    *,
    get_session: Callable[[], object],
    generate_uid: Callable[[], str],
    ensure_default_stage: Callable[[Session, int], WorkflowStage],
    masked_webhook_url: str,
) -> int:
    """从 JSON 文件导入工作流。"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    webhooks_data = data.get("webhooks", [])
    workflows_data = data.get("workflows", [])
    imported_count = 0

    with get_session() as session:
        webhook_name_to_id = _import_webhooks(
            session,
            webhooks_data,
            masked_webhook_url=masked_webhook_url,
        )

        for wf_data in workflows_data:
            workflow = _build_workflow(wf_data, generate_uid)
            _apply_notify_config(session, workflow, wf_data, webhook_name_to_id)
            if "watch" in wf_data:
                folders = wf_data.get("watch", {}).get("folders", [])
                if folders:
                    workflow.set_watch_folders(folders)

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
            imported_count += 1

        session.commit()

    return imported_count


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
        "version": 1,
        "secrets_included": bool(include_secrets),
        "webhooks": [],
        "workflows": [],
    }

    with get_session() as session:
        webhooks = session.query(WebhookConfig).order_by(WebhookConfig.name).all()
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

        workflow_query = session.query(Workflow).options(
            selectinload(Workflow.stages),
            selectinload(Workflow.steps),
        )
        if workflow_ids:
            workflow_query = workflow_query.filter(Workflow.id.in_(list(workflow_ids)))
        workflows = workflow_query.order_by(Workflow.created_at.desc()).all()

        for workflow in workflows:
            data["workflows"].append(_export_workflow(workflow, webhook_map))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _import_webhooks(
    session: Session,
    webhooks_data,
    *,
    masked_webhook_url: str,
) -> dict[str, int]:
    webhook_name_to_id = {}
    if not isinstance(webhooks_data, list) or not webhooks_data:
        return webhook_name_to_id

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
        existing = session.query(WebhookConfig).filter(WebhookConfig.name == name).first()

        if url_masked:
            if existing:
                _update_existing_masked_webhook(session, existing, keyword, desc)
                webhook_name_to_id[name] = existing.id
            else:
                logger.info("导入 webhook 已脱敏且本机无同名配置，跳过创建: name=%r", name)
            continue

        if not url:
            continue
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

    return webhook_name_to_id


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


def _build_workflow(wf_data: dict, generate_uid: Callable[[], str]) -> Workflow:
    single_args = wf_data.get("single_script", {}).get("args")
    if isinstance(single_args, list):
        single_args = json.dumps(single_args, ensure_ascii=False)
    return Workflow(
        uid=wf_data.get("id", generate_uid()),
        name=wf_data.get("name", "未命名工作流"),
        chart_theme=wf_data.get("chart_theme", "default"),
        parallel_enabled=wf_data.get("parallel", {}).get("enabled", False),
        max_workers=wf_data.get("parallel", {}).get("max_workers", 2),
        watch_enabled=wf_data.get("watch", {}).get("enabled", False),
        watch_mode=wf_data.get("watch", {}).get("mode", "any_change"),
        cooldown_seconds=wf_data.get("watch", {}).get("cooldown_seconds", 8),
        settle_seconds=wf_data.get("watch", {}).get("settle_seconds", 15),
        single_script_enabled=wf_data.get("single_script", {}).get("enabled", False),
        single_script_type=wf_data.get("single_script", {}).get("type", "python"),
        single_script_path=wf_data.get("single_script", {}).get("path"),
        single_script_args=single_args,
        single_script_cwd=wf_data.get("single_script", {}).get("cwd"),
    )


def _apply_notify_config(
    session: Session,
    workflow: Workflow,
    wf_data: dict,
    webhook_name_to_id: dict[str, int],
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
    else:
        wh_id = notify.get("webhook_id")
        if wh_id:
            exists = session.query(WebhookConfig).filter(WebhookConfig.id == wh_id).first()
            if not exists:
                notify["webhook_id"] = None
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
        deps = step_data.get("depends_on", [])
        if deps:
            step.set_depends_on(deps)
        session.add(step)


def _export_workflow(workflow: Workflow, webhook_map: dict[int, str]) -> dict:
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
        "chart_theme": workflow.chart_theme,
        "parallel": {
            "enabled": workflow.parallel_enabled,
            "max_workers": workflow.max_workers,
        },
        "notify": notify,
        "watch": {
            "enabled": workflow.watch_enabled,
            "mode": workflow.watch_mode,
            "folders": workflow.get_watch_folders(),
            "cooldown_seconds": workflow.cooldown_seconds,
            "settle_seconds": workflow.settle_seconds,
        },
        "single_script": {
            "enabled": workflow.single_script_enabled,
            "type": workflow.single_script_type,
            "path": workflow.single_script_path,
            "args": workflow.single_script_args,
            "cwd": workflow.single_script_cwd,
        },
        "stages": _export_stages(workflow),
        "steps": _export_steps(workflow),
    }


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
            "cwd": step.cwd or "",
            "is_gate": step.is_gate,
            "is_parallel": step.is_parallel,
            "depends_on": step.get_depends_on(),
            "chart_theme": step.chart_theme or "",
            "timeout_seconds": step.timeout_seconds,
            "retry_count": step.retry_count,
            "skip_on_success": step.skip_on_success,
        }
        for step in sorted(workflow.steps, key=lambda s: s.order)
    ]
