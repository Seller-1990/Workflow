# -*- coding: utf-8 -*-
"""R1: 导入风险路径确认机制 —— 纯函数核心（无数据库/UI 依赖）。

安全语义:只保护「从外部 JSON 导入并含风险路径的工作流」;风险路径 = 活动步骤的
绝对 script_path/cwd + ``..`` 逃逸路径;退役字段（single_script/watch）不参与。

本模块供导入判定 / GUI 展示 / CLI 输出 / 确认摘要 / 引擎校验共用。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Iterable, List, NamedTuple, Optional, Tuple


class RiskRecord(NamedTuple):
    """单条风险路径记录：步骤 UID + 字段名 + 规范化后的路径。"""

    step_uid: str
    field_name: str
    path: str


@dataclass(frozen=True)
class RunPlan:
    """同一数据库快照生成的不可变运行计划（R1 校验输入）。

    - risk_records 来自生成时的步骤快照;执行消费同一快照。
    - revision + confirmed_digest 用于校验「既有确认是否仍然有效」。
    """

    workflow_id: int
    review_required: bool
    revision: int
    confirmed_digest: Optional[str]
    risk_records: Tuple[RiskRecord, ...]

    @property
    def has_risk_records(self) -> bool:
        return bool(self.risk_records)


# 风险字段（活动步骤）;dict 形态的导入 JSON 用 dict_key，ORM 步骤用 attr_name
_RISK_FIELDS = (
    ("script_path", "script_path", "script"),
    ("cwd", "cwd", "cwd"),
)

_FIELD_LABELS = {"script_path": "脚本路径", "cwd": "工作目录"}


def normalize_path(path: object, *, fold_case: Optional[bool] = None) -> str:
    """规范化路径字符串（统一分隔符 / 大小写 / 空白 / ``.`` ``..`` 折叠）。

    - 仅 Windows 平台折叠大小写（POSIX 保留）;``fold_case`` 可显式注入覆盖平台推断。
    - UNC 路径（``//`` 前缀）与根路径不碰撞：``//server/share`` 不会被折叠成 ``/``;
      ``..`` 无法越过 UNC 服务器名或盘符根。
    - 非字符串 / 空白 → 返回 ``""``。
    """
    if not isinstance(path, str):
        return ""
    raw = path.strip()
    if not raw:
        return ""
    if fold_case is None:
        fold_case = sys.platform.startswith("win")

    s = raw.replace("\\", "/")
    if fold_case:
        s = s.lower()

    drive = ""
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        drive = s[:2]
        s = s[2:]

    is_unc = s.startswith("//")
    absolute = is_unc or s.startswith("/")

    segments: list[str] = []
    for part in s.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if segments and segments[-1] != "..":
                if is_unc and absolute and len(segments) == 1:
                    # 不能越过 UNC 服务器名
                    continue
                segments.pop()
            elif absolute and not segments:
                # 已在根，不能越界
                continue
            else:
                segments.append("..")
            continue
        segments.append(part)

    body = "/".join(segments)
    if drive:
        return f"{drive}/{body}" if absolute else f"{drive}{body}"
    if is_unc:
        return f"//{body}"
    if absolute:
        return f"/{body}"
    return body


def looks_risky_path(value: object) -> bool:
    """绝对路径或包含 ``..`` 逃逸路径片段 → True（风险路径）。

    退役字段（single_script/watch）不参与;非字符串 / 空白 → False。
    """
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    s = raw.replace("\\", "/")
    if s.startswith("/"):
        return True
    if len(s) >= 3 and s[1] == ":" and s[0].isalpha() and s[2] == "/":
        return True
    return ".." in s.split("/")


def _step_field(step, attr_name: str, dict_key: str):
    """步骤对象（ORM Step / SimpleNamespace）或导入 dict 的统一取值。"""
    if isinstance(step, dict):
        return step.get(dict_key)
    return getattr(step, attr_name, None)


def _step_uid(step) -> str:
    uid = _step_field(step, "uid", "id")
    return str(uid) if uid is not None else ""


def collect_risk_paths(steps) -> List[RiskRecord]:
    """收集活动步骤中的风险路径记录（规范化后）。

    供导入判定（导入 dict）/ GUI 展示 / CLI 输出 / 确认摘要 / 引擎校验（ORM 步骤）
    共用;字段名统一为 ``script_path`` / ``cwd``，保证 digest 与展示一致。
    """
    records: List[RiskRecord] = []
    for step in steps or []:
        uid = _step_uid(step)
        for field_name, attr_name, dict_key in _RISK_FIELDS:
            value = _step_field(step, attr_name, dict_key)
            if looks_risky_path(value):
                records.append(
                    RiskRecord(
                        step_uid=uid,
                        field_name=field_name,
                        path=normalize_path(value),
                    )
                )
    return records


def compute_digest(revision: object, records: Iterable[RiskRecord]) -> str:
    """records 排序后序列化，连同 revision 一起哈希（SHA-256）。

    确定性：排序 + ``sort_keys`` + 固定分隔符，保证同输入跨进程/跨版本稳定；
    用于确认时快照与运行前重算比对（revision 递增保证「删除后恢复同路径」
    等结构变化必然失配）。
    """
    sorted_records = sorted(
        (str(record.step_uid), str(record.field_name), str(record.path))
        for record in records
    )
    payload = json.dumps(
        {"revision": int(revision or 0), "records": sorted_records},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_run_plan(workflow, steps) -> RunPlan:
    """由同一数据库快照（workflow + steps）生成不可变 RunPlan。"""
    return RunPlan(
        workflow_id=int(getattr(workflow, "id", 0) or 0),
        review_required=bool(getattr(workflow, "risky_paths_review_required", False)),
        revision=int(getattr(workflow, "risky_paths_revision", 0) or 0),
        confirmed_digest=getattr(workflow, "risky_paths_confirmed_digest", None),
        risk_records=tuple(collect_risk_paths(steps)),
    )


def evaluate_run_plan(plan: RunPlan) -> Optional[str]:
    """运行前校验：返回 None 放行，否则返回阻断原因（中文）。

    判定规则（与安全语义一致）：
    - 记录为空 → 放行;
    - review_required=1 且有风险路径 → 阻断（需用户确认）;
    - review_required=0 且 digest 空 → 非导入 / 旧记录 → 放行;
    - 重算摘要失配（revision 或路径记录变化）→ 阻断（确认已失效）。
    """
    if not plan.risk_records:
        return None
    if plan.review_required:
        return (
            "此工作流包含未经确认的导入风险路径（绝对路径或上级目录引用），"
            "请先确认脚本和工作目录来源可信后再运行"
        )
    if not plan.confirmed_digest:
        return None
    current_digest = compute_digest(plan.revision, plan.risk_records)
    if current_digest != plan.confirmed_digest:
        return (
            "此工作流的风险路径自上次确认后已发生变化，原确认已失效，"
            "请重新确认路径安全后再运行"
        )
    return None


def format_risk_records(records: Iterable[RiskRecord]) -> str:
    """人类可读的风险路径明细（GUI 弹窗 / CLI 输出 / 确认摘要共用）。"""
    lines = []
    for record in records:
        label = _FIELD_LABELS.get(record.field_name, record.field_name)
        lines.append(f"  - 步骤「{record.step_uid or '?'}」{label}: {record.path}")
    return "\n".join(lines)
