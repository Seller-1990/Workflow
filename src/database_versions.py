# -*- coding: utf-8 -*-
"""工作流配置版本快照。"""

from __future__ import annotations

import json
from typing import Callable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from database_import_export import WORKFLOW_PAYLOAD_SCHEMA_VERSION, serialize_workflow_payload
from models import WebhookConfig, Workflow, WorkflowVersion

MAX_VERSION_SAVE_ATTEMPTS = 5
SNAPSHOT_SCHEMA_VERSION = WORKFLOW_PAYLOAD_SCHEMA_VERSION


def save_workflow_version_impl(
    workflow_id: int,
    *,
    reason: str | None = None,
    session_factory: Callable,
) -> Optional[int]:
    """保存工作流当前配置的快照版本。"""
    for attempt in range(MAX_VERSION_SAVE_ATTEMPTS):
        with session_factory() as session:
            workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                return None

            latest = (
                session.query(WorkflowVersion)
                .filter(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.version.desc())
                .first()
            )
            next_version = (latest.version + 1) if latest else 1

            version = WorkflowVersion(
                workflow_id=workflow_id,
                version=next_version,
                snapshot=build_workflow_snapshot(workflow),
                change_reason=reason,
            )
            session.add(version)
            try:
                session.commit()
                return next_version
            except IntegrityError:
                session.rollback()
                if attempt == MAX_VERSION_SAVE_ATTEMPTS - 1:
                    raise

    raise RuntimeError("保存工作流版本失败：超过并发重试次数")


def get_workflow_versions_impl(
    workflow_id: int,
    *,
    limit: int = 20,
    session_factory: Callable,
) -> list[WorkflowVersion]:
    """获取工作流的版本历史。"""
    with session_factory() as session:
        return (
            session.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(limit)
            .all()
        )


def get_workflow_version_impl(version_id: int, *, session_factory: Callable) -> Optional[WorkflowVersion]:
    """获取指定版本。"""
    with session_factory() as session:
        return session.query(WorkflowVersion).filter(WorkflowVersion.id == version_id).first()


def build_workflow_snapshot(workflow: Workflow) -> str:
    snapshot = serialize_workflow_payload(workflow, _snapshot_webhook_map(workflow))
    snapshot["snapshot_schema_version"] = SNAPSHOT_SCHEMA_VERSION
    return json.dumps(
        snapshot,
        ensure_ascii=False,
    )


def _snapshot_webhook_map(workflow: Workflow) -> dict[int, str]:
    notify = workflow.get_notify_config()
    if not isinstance(notify, dict):
        return {}

    webhook_id = notify.get("webhook_id")
    if isinstance(webhook_id, str):
        if not webhook_id.isdigit():
            return {}
        webhook_id = int(webhook_id)
    if not isinstance(webhook_id, int):
        return {}

    session = object_session(workflow)
    if session is None:
        return {}

    webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        return {}
    return {webhook.id: webhook.name}
