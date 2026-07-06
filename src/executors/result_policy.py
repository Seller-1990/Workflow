# -*- coding: utf-8 -*-
"""执行器结果策略常量与辅助方法。"""

from typing import Any, Mapping


class ResultPolicyKeys:
    """ExecutorResult.extra 中与调度策略相关的键。"""

    CANCELLED = "cancelled"
    NON_RETRYABLE = "non_retryable"
    MANUAL_REQUIRED = "manual_required"
    BACKGROUND_RISK = "background_risk"
    ORPHAN_RISK = "orphan_risk"
    NOTE = "note"
    PROOF_REASON = "proof_reason"
    CHILD_EXIT_GRACE_SECONDS = "child_exit_grace_seconds"


NON_RETRYABLE_POLICY_KEYS = (
    ResultPolicyKeys.NON_RETRYABLE,
    ResultPolicyKeys.MANUAL_REQUIRED,
    ResultPolicyKeys.BACKGROUND_RISK,
    ResultPolicyKeys.ORPHAN_RISK,
)


def has_non_retryable_policy(extra: Mapping[str, Any] | None) -> bool:
    """是否命中了不应自动重试的执行器策略。"""
    if not extra:
        return False
    return any(bool(extra.get(flag)) for flag in NON_RETRYABLE_POLICY_KEYS)


def build_policy_extra(
    *,
    cancelled: bool | None = None,
    manual_required: bool | None = None,
    background_risk: bool | None = None,
    orphan_risk: bool | None = None,
    non_retryable: bool | None = None,
    note: str | None = None,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 ExecutorResult.extra，统一策略键名来源。"""
    extra: dict[str, Any] = {}

    if cancelled is not None:
        extra[ResultPolicyKeys.CANCELLED] = cancelled
    if manual_required is not None:
        extra[ResultPolicyKeys.MANUAL_REQUIRED] = manual_required
    if background_risk is not None:
        extra[ResultPolicyKeys.BACKGROUND_RISK] = background_risk
    if orphan_risk is not None:
        extra[ResultPolicyKeys.ORPHAN_RISK] = orphan_risk
    if non_retryable is not None:
        extra[ResultPolicyKeys.NON_RETRYABLE] = non_retryable
    if note is not None:
        extra[ResultPolicyKeys.NOTE] = note
    if extra_fields:
        extra.update(dict(extra_fields))
    return extra


def build_cancelled_extra(note: str = "用户取消") -> dict[str, Any]:
    """构造用户取消结果的统一策略标记。"""
    return build_policy_extra(
        cancelled=True,
        non_retryable=True,
        note=note,
    )
