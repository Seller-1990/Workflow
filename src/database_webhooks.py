# -*- coding: utf-8 -*-
"""拆自 database.py（L1 巨型文件治理），会话仍由 database.get_session 提供。

Webhook 配置 CRUD 与钉钉 Webhook URL 校验/脱敏判断；
通过 database.py 门面再导出，调用方无需感知此拆分。
"""

from datetime import datetime
from typing import Optional, List

from database_field_guards import (
    WEBHOOK_UPDATE_FIELDS,
    validate_update_fields as _validate_update_fields,
)
from models import WebhookConfig
from webhook_url_policy import (
    is_masked_webhook_url as _is_masked_webhook_url,
    is_valid_dingtalk_webhook_url,
)


def is_masked_webhook_url(value: str | None) -> bool:
    """判断导入值是否为脱敏占位符。"""
    from database import MASKED_WEBHOOK_URL
    return _is_masked_webhook_url(value, MASKED_WEBHOOK_URL)


def validate_webhook_url(webhook_url: str) -> str:
    """校验并规范化钉钉机器人 Webhook URL。"""
    url = (webhook_url or "").strip()
    if not is_valid_dingtalk_webhook_url(url):
        raise ValueError("Webhook URL 必须是钉钉机器人 HTTPS 地址")
    return url


# ============== Webhook CRUD ==============

def list_webhooks() -> List[WebhookConfig]:
    """获取所有 Webhook 配置

    M8: 返回前 expunge，确保对象在 session 之外的属性访问不会触发刷新。
    """
    from database import get_session
    with get_session() as session:
        rows = session.query(WebhookConfig).order_by(WebhookConfig.name).all()
        for row in rows:
            session.expunge(row)
        return rows


def get_webhook_by_id(webhook_id: int) -> Optional[WebhookConfig]:
    """根据 ID 获取 Webhook

    M8: 返回前 expunge，确保对象在 session 之外的属性访问不会触发刷新。
    """
    from database import get_session
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            session.expunge(webhook)
        return webhook


def create_webhook(
    name: str,
    webhook_url: str,
    keyword: str = "",
    description: str = ""
) -> WebhookConfig:
    """创建 Webhook 配置"""
    name = (name or "").strip()
    if not name:
        raise ValueError("Webhook 名称不能为空")
    webhook_url = validate_webhook_url(webhook_url)
    from database import get_session
    with get_session() as session:
        existing = session.query(WebhookConfig).filter(WebhookConfig.name == name).first()
        if existing:
            raise ValueError(f"Webhook 名称已存在: {name}")
        webhook = WebhookConfig(
            name=name,
            webhook_url=webhook_url,
            keyword=keyword,
            description=description
        )
        session.add(webhook)
        session.commit()
        session.refresh(webhook)
        session.expunge(webhook)
        return webhook


def update_webhook(webhook_id: int, **kwargs) -> Optional[WebhookConfig]:
    """更新 Webhook 配置"""
    _validate_update_fields("WebhookConfig", kwargs, WEBHOOK_UPDATE_FIELDS)
    if "name" in kwargs:
        kwargs["name"] = (kwargs["name"] or "").strip()
        if not kwargs["name"]:
            raise ValueError("Webhook 名称不能为空")
    if "webhook_url" in kwargs:
        kwargs["webhook_url"] = validate_webhook_url(kwargs["webhook_url"])
    from database import get_session
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            if "name" in kwargs:
                duplicate = (
                    session.query(WebhookConfig)
                    .filter(WebhookConfig.name == kwargs["name"], WebhookConfig.id != webhook_id)
                    .first()
                )
                if duplicate:
                    raise ValueError(f"Webhook 名称已存在: {kwargs['name']}")
            for key, value in kwargs.items():
                setattr(webhook, key, value)
            webhook.updated_at = datetime.now()
            session.commit()
            session.refresh(webhook)
            session.expunge(webhook)
        return webhook


def delete_webhook(webhook_id: int) -> bool:
    """删除 Webhook 配置"""
    from database import get_session
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            session.delete(webhook)
            session.commit()
            return True
        return False


def get_webhooks_by_ids(webhook_ids: List[int]) -> List[WebhookConfig]:
    """根据 ID 列表获取多个 Webhook"""
    if not webhook_ids:
        return []
    from database import get_session
    with get_session() as session:
        return session.query(WebhookConfig).filter(WebhookConfig.id.in_(webhook_ids)).all()
