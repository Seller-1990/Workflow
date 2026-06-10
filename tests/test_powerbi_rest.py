# -*- coding: utf-8 -*-
"""Power BI REST 刷新模式测试（全部使用脚本化假 http 与假时钟，无网络）"""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from constants import POWERBI_REST_POLL_INTERVAL, POWERBI_REST_TIMEOUT
from executors.powerbi_executor import PowerBIExecutor
from executors.powerbi_rest import PowerBIRestError, refresh_dataset

BASE_URL = "https://api.powerbi.com/v1.0/myorg/groups/ws-1/datasets/ds-1/refreshes"


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeHttp:
    """脚本化假 http 客户端：按顺序弹出预设响应并记录全部调用"""

    def __init__(self, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers, json, timeout))
        return self.post_responses.pop(0)

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers, None, timeout))
        return self.get_responses.pop(0)


class FakeClock:
    """假时钟：monotonic 只随 sleep 前进，避免真实等待"""

    def __init__(self, start=0.0):
        self.now = float(start)
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _refresh_payload(status, service_exception=None):
    entry = {"status": status}
    if service_exception is not None:
        entry["serviceExceptionJson"] = service_exception
    return {"value": [entry]}


def _run_refresh(http, clock, *, timeout_seconds=300, poll_interval=15, should_cancel=None, log_cb=None):
    refresh_dataset(
        "ws-1",
        "ds-1",
        "secret-token",
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        http=http,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        should_cancel=should_cancel,
        log_cb=log_cb,
    )


def test_refresh_dataset_polls_until_completed():
    http = FakeHttp(
        post_responses=[FakeResponse(202)],
        get_responses=[
            FakeResponse(200, payload=_refresh_payload("Unknown")),
            FakeResponse(200, payload=_refresh_payload("Completed")),
        ],
    )
    clock = FakeClock()
    logs = []

    _run_refresh(http, clock, log_cb=logs.append)

    assert [(method, url) for method, url, *_ in http.calls] == [
        ("POST", BASE_URL),
        ("GET", BASE_URL + "?$top=1"),
        ("GET", BASE_URL + "?$top=1"),
    ]
    # 两次轮询之间恰好等待一个轮询间隔
    assert clock.sleeps == [15]
    # 触发请求：Bearer 鉴权 + NoNotification + 单请求超时 30 秒
    assert http.calls[0][2] == {"Authorization": "Bearer secret-token"}
    assert http.calls[0][3] == {"notifyOption": "NoNotification"}
    assert all(call[4] == 30 for call in http.calls)
    # 进度日志不得泄漏 token
    assert logs
    assert all("secret-token" not in line for line in logs)


def test_refresh_dataset_failed_status_raises_with_service_exception_excerpt():
    http = FakeHttp(
        post_responses=[FakeResponse(202)],
        get_responses=[
            FakeResponse(
                200,
                payload=_refresh_payload("Failed", service_exception='{"errorCode":"ModelRefreshFailed_CredentialsNotSpecified"}'),
            ),
        ],
    )
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock)

    assert "REST 刷新失败" in str(exc_info.value)
    assert "ModelRefreshFailed_CredentialsNotSpecified" in str(exc_info.value)


def test_refresh_dataset_unauthorized_trigger_reports_permission_problem():
    http = FakeHttp(post_responses=[FakeResponse(401, text="Unauthorized")])
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock)

    assert "访问令牌无效或权限不足" in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)
    # 触发失败后不应进入轮询
    assert [method for method, *_ in http.calls] == ["POST"]


def test_refresh_dataset_conflict_trigger_reports_refresh_in_progress():
    http = FakeHttp(
        post_responses=[
            FakeResponse(400, text='{"error":{"code":"InvalidRequest","message":"Another refresh request is in progress"}}'),
        ],
    )
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock)

    assert str(exc_info.value) == "已有刷新正在进行中，请稍后再试"


def test_refresh_dataset_not_found_trigger_reports_missing_ids():
    http = FakeHttp(post_responses=[FakeResponse(404, text="PowerBIEntityNotFound")])
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock)

    assert "工作区或数据集不存在" in str(exc_info.value)


def test_refresh_dataset_disabled_status_reports_refresh_disabled():
    http = FakeHttp(
        post_responses=[FakeResponse(202)],
        get_responses=[FakeResponse(200, payload=_refresh_payload("Disabled"))],
    )
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock)

    assert "数据集刷新被禁用" in str(exc_info.value)


def test_refresh_dataset_cancelled_before_first_poll():
    http = FakeHttp(post_responses=[FakeResponse(202)])
    clock = FakeClock()

    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock, should_cancel=lambda: True)

    assert str(exc_info.value) == "用户取消"
    # 取消发生在任何状态轮询之前
    assert [method for method, *_ in http.calls] == ["POST"]


def test_refresh_dataset_times_out_when_deadline_exceeded():
    http = FakeHttp(
        post_responses=[FakeResponse(202)],
        get_responses=[FakeResponse(200, payload=_refresh_payload("InProgress"))],
    )
    clock = FakeClock()

    # deadline=10 秒，第一次轮询后 sleep(15) 越过 deadline
    with pytest.raises(PowerBIRestError) as exc_info:
        _run_refresh(http, clock, timeout_seconds=10, poll_interval=15)

    assert str(exc_info.value) == "REST 刷新轮询超时 (10秒)"
    assert [method for method, *_ in http.calls] == ["POST", "GET"]


# ---------------------------------------------------------------------------
# PowerBIExecutor REST 模式接线
# ---------------------------------------------------------------------------


def _forbid_desktop_lookup(monkeypatch):
    monkeypatch.setattr(
        PowerBIExecutor,
        "find_pbidesktop",
        lambda self: pytest.fail("REST 模式不应查找 Power BI Desktop"),
    )


def test_executor_rest_mode_missing_token_reports_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("POWERBI_ACCESS_TOKEN", raising=False)
    _forbid_desktop_lookup(monkeypatch)

    # REST 模式不依赖本地 .pbix：dummy.pbix 并不存在也应先走 REST 分支
    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest", "--workspace-id=ws-1", "--dataset-id=ds-1"],
        log_dir=tmp_path / "logs",
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "POWERBI_ACCESS_TOKEN" in (result.error_message or "")
    assert "缺少必要配置" in (result.error_message or "")


def test_executor_rest_mode_missing_ids_reports_each_argument(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("POWERBI_ACCESS_TOKEN", raising=False)
    _forbid_desktop_lookup(monkeypatch)

    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest"],
        log_dir=tmp_path / "logs",
    )

    assert result.success is False
    assert result.exit_code == 1
    message = result.error_message or ""
    assert "--workspace-id=" in message
    assert "--dataset-id=" in message
    assert "POWERBI_ACCESS_TOKEN" in message


def test_executor_rest_mode_success_uses_default_timeout_and_reports_proof(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POWERBI_ACCESS_TOKEN", "env-token")
    _forbid_desktop_lookup(monkeypatch)
    captured = {}

    def fake_refresh_dataset(
        workspace_id,
        dataset_id,
        access_token,
        *,
        timeout_seconds,
        poll_interval,
        should_cancel=None,
        log_cb=None,
        **kwargs,
    ):
        captured["workspace_id"] = workspace_id
        captured["dataset_id"] = dataset_id
        captured["access_token"] = access_token
        captured["timeout_seconds"] = timeout_seconds
        captured["poll_interval"] = poll_interval
        captured["should_cancel"] = should_cancel
        log_cb("刷新请求已受理 (HTTP 202)")

    monkeypatch.setattr("executors.powerbi_executor.refresh_dataset", fake_refresh_dataset)

    cancel_event = threading.Event()
    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest", "--workspace-id=ws-1", "--dataset-id=ds-1"],
        log_dir=tmp_path / "logs",
        timeout=None,
        cancel_event=cancel_event,
    )

    assert result.success is True
    assert result.exit_code == 0
    assert result.extra == {"proof_type": "rest_refresh_completed"}
    assert captured["workspace_id"] == "ws-1"
    assert captured["dataset_id"] == "ds-1"
    assert captured["access_token"] == "env-token"
    # timeout=None 时应回落到 REST 默认轮询上限
    assert captured["timeout_seconds"] == POWERBI_REST_TIMEOUT
    assert captured["poll_interval"] == POWERBI_REST_POLL_INTERVAL
    # should_cancel 必须跟随 cancel_event
    assert captured["should_cancel"]() is False
    cancel_event.set()
    assert captured["should_cancel"]() is True
    # 进度日志写入 stdout 且不包含 token
    stdout_text = Path(result.stdout_path).read_text(encoding="utf-8")
    assert "刷新请求已受理" in stdout_text
    assert "env-token" not in stdout_text


def test_executor_rest_mode_respects_explicit_timeout(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POWERBI_ACCESS_TOKEN", "env-token")
    _forbid_desktop_lookup(monkeypatch)
    captured = {}

    def fake_refresh_dataset(workspace_id, dataset_id, access_token, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("executors.powerbi_executor.refresh_dataset", fake_refresh_dataset)

    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest", "--workspace-id=ws-1", "--dataset-id=ds-1"],
        log_dir=tmp_path / "logs",
        timeout=120,
    )

    assert result.success is True
    assert captured["timeout_seconds"] == 120


def test_executor_rest_mode_cancel_keeps_cancel_semantics(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POWERBI_ACCESS_TOKEN", "env-token")
    _forbid_desktop_lookup(monkeypatch)

    def fake_refresh_dataset(*args, **kwargs):
        raise PowerBIRestError("用户取消")

    monkeypatch.setattr("executors.powerbi_executor.refresh_dataset", fake_refresh_dataset)

    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest", "--workspace-id=ws-1", "--dataset-id=ds-1"],
        log_dir=tmp_path / "logs",
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.error_message == "用户取消"


def test_executor_rest_mode_rest_error_maps_to_step_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POWERBI_ACCESS_TOKEN", "env-token")
    _forbid_desktop_lookup(monkeypatch)

    def fake_refresh_dataset(*args, **kwargs):
        raise PowerBIRestError("访问令牌无效或权限不足（需要数据集读写权限与工作区访问）")

    monkeypatch.setattr("executors.powerbi_executor.refresh_dataset", fake_refresh_dataset)

    result = PowerBIExecutor().execute(
        "dummy.pbix",
        args=["--refresh-mode=rest", "--workspace-id=ws-1", "--dataset-id=ds-1"],
        log_dir=tmp_path / "logs",
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "访问令牌无效或权限不足" in (result.error_message or "")
    stderr_text = Path(result.stderr_path).read_text(encoding="utf-8")
    assert "访问令牌无效或权限不足" in stderr_text
