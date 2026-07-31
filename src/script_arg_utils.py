# -*- coding: utf-8 -*-
"""命令行临时参数解析、合并与脱敏（纯函数，无 Qt 依赖）。"""

from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Iterable, Mapping, Sequence


class CliArgsParseError(ValueError):
    """用户输入的临时参数无法解析。"""


_SENSITIVE_NAME_RE = re.compile(r"(token|secret|password)", re.IGNORECASE)
_SENSITIVE_VALUE_RE = re.compile(r"(access_token=)", re.IGNORECASE)
_KEY_EQ_VALUE_RE = re.compile(r"^(?P<prefix>--?[^=\s]+)=(?P<value>.*)$")


def parse_cli_args_text(text: str | None) -> list[str]:
    """将用户输入解析为参数数组。

    支持：
    - 空字符串 -> []
    - JSON 数组字符串 -> list[str]
    - shell-like 命令行文本（含引号）

    Windows 上使用 posix=False，避免 ``C:\\Data\\2025`` 被反斜杠转义吞掉。
    """
    if text is None:
        return []
    raw = str(text).strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliArgsParseError(f"JSON 参数解析失败: {exc.msg}") from exc
        if not isinstance(data, list):
            raise CliArgsParseError("JSON 参数必须是数组")
        result: list[str] = []
        for item in data:
            if item is None:
                raise CliArgsParseError("JSON 参数项不能为 null")
            if isinstance(item, (dict, list)):
                raise CliArgsParseError("JSON 参数项必须是字符串或简单标量")
            s = str(item)
            if "\x00" in s:
                raise CliArgsParseError("参数不能包含空字符")
            result.append(s)
        return result

    try:
        # Windows 桌面端：posix=False 保留反斜杠路径；其它平台保持 posix 语义
        posix = sys.platform != "win32"
        parts = shlex.split(raw, posix=posix)
    except ValueError as exc:
        raise CliArgsParseError(f"命令行参数解析失败: {exc}") from exc

    # posix=False 时 shlex 可能保留外层引号，剥掉成对引号
    if not posix:
        cleaned: list[str] = []
        for part in parts:
            if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}:
                cleaned.append(part[1:-1])
            else:
                cleaned.append(part)
        parts = cleaned

    for part in parts:
        if "\x00" in part:
            raise CliArgsParseError("参数不能包含空字符")
    return parts


def merge_step_args(
    fixed_args: Sequence[str] | None,
    temporary_args: Sequence[str] | None,
) -> list[str]:
    """固定参数在前，临时参数在后。不修改入参。"""
    fixed = [str(x) for x in (fixed_args or [])]
    temporary = [str(x) for x in (temporary_args or [])]
    return fixed + temporary


def resolve_effective_args(
    step_uid: str | None,
    fixed_args: Sequence[str] | None,
    run_arg_overrides: Mapping[str, Sequence[str]] | None,
    *,
    saved_run_args: Sequence[str] | None = None,
) -> list[str]:
    """合并固定参数与运行参数层；本次覆盖按 UID 替换已保存层。"""
    overrides = run_arg_overrides or {}
    runtime_args: Sequence[str] | None = saved_run_args
    if step_uid and step_uid in overrides:
        runtime_args = overrides[step_uid] or []
    return merge_step_args(fixed_args, runtime_args)


def redact_cli_args(args: Iterable[str] | None) -> list[str]:
    """对明显敏感参数做日志脱敏。

    覆盖：
    - ``--token abc`` / ``--password abc``
    - ``--token=abc`` / ``--password=abc``
    - 含 ``access_token=`` 的值
    """
    items = [str(x) for x in (args or [])]
    redacted: list[str] = []
    i = 0
    while i < len(items):
        token = items[i]

        # 整段值含 access_token=
        if _SENSITIVE_VALUE_RE.search(token):
            m = _KEY_EQ_VALUE_RE.match(token)
            if m and _SENSITIVE_NAME_RE.search(m.group("prefix")):
                redacted.append(f"{m.group('prefix')}=****")
            else:
                redacted.append("****")
            i += 1
            continue

        # --token=abc / --password=secret
        m = _KEY_EQ_VALUE_RE.match(token)
        if m and token.startswith("-") and _SENSITIVE_NAME_RE.search(m.group("prefix")):
            redacted.append(f"{m.group('prefix')}=****")
            i += 1
            continue

        # --token abc
        if token.startswith("-") and _SENSITIVE_NAME_RE.search(token):
            redacted.append(token)
            if i + 1 < len(items) and not str(items[i + 1]).startswith("-"):
                redacted.append("****")
                i += 2
            else:
                i += 1
            continue

        redacted.append(token)
        i += 1
    return redacted


def format_cli_args_for_log(args: Iterable[str] | None) -> str:
    """生成可展示的参数摘要（已脱敏）。"""
    redacted = redact_cli_args(args)
    if not redacted:
        return "(无)"
    # 日志展示统一用 posix quote，避免 Windows 风格混杂
    return " ".join(shlex.quote(x) for x in redacted)


def normalize_run_arg_overrides(
    overrides: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    """规范化为 dict[str, list[str]] 的只读拷贝。"""
    if not overrides:
        return {}
    result: dict[str, list[str]] = {}
    for key, values in overrides.items():
        if key is None:
            continue
        uid = str(key)
        if not uid:
            continue
        result[uid] = [str(v) for v in (values or [])]
    return result
