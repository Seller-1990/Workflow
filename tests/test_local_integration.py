# -*- coding: utf-8 -*-
"""本地真实外设集成测试（默认全部跳过，按环境变量显式开启）。

背景：仓库内既有测试对 Excel COM 与钉钉网络全部使用 mock，真实外设路径
（真实启动 Excel 刷新、真实发送钉钉消息）此前只能在生产环境验证。本模块
补上这一层 OPT-IN 的本地集成测试：CI 与未设置环境变量的本地运行自动跳过，
不影响质量门；需要验证真实外设时按下述方式显式开启。

激活方式（Windows cmd）：

- 真实 Excel COM 往返测试::

    set WORKFLOW_LOCAL_INTEGRATION=1
    python -m pytest tests/test_local_integration.py -m local_integration -q

- 真实钉钉发送测试（会真实发送一条消息到目标机器人）::

    set WORKFLOW_TEST_DINGTALK_WEBHOOK=<真实机器人URL>
    rem 可选：机器人安全设置为「自定义关键词」时提供
    set WORKFLOW_TEST_DINGTALK_WEBHOOK_KEYWORD=<关键词>
    python -m pytest tests/test_local_integration.py -m local_integration -q

注意：

- Webhook URL 必须是 ``https://oapi.dingtalk.com/robot/send`` 下的真实机器人
  地址，``src/webhook_url_policy.py`` 会拒绝其他主机或非 HTTPS 地址。
- 本文件不得硬编码任何 access_token 残留（``tools/repo_hygiene.py`` 会扫描
  tests/ 目录），真实地址只允许通过环境变量注入，不落盘。
- 本文件不得新增 broad except（``tools/audit_broad_except.py`` 对 tests/ 同样
  生效且 baseline 中没有本文件的豁免条目），COM 探测只捕获精确异常类型。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import notifier

ROOT = Path(__file__).resolve().parents[1]

# Excel COM SaveAs 的 .xlsx 格式常量（XlFileFormat.xlOpenXMLWorkbook）
XL_OPEN_XML_WORKBOOK = 51


@pytest.mark.local_integration
@pytest.mark.skipif(
    os.environ.get("WORKFLOW_LOCAL_INTEGRATION") != "1",
    reason="未设置 WORKFLOW_LOCAL_INTEGRATION=1，默认跳过真实 Excel COM 集成测试",
)
def test_excel_executor_real_com_roundtrip(tmp_path):
    """真实 Excel COM 往返：COM 创建 .xlsx → ExcelExecutor 真实刷新保存 → 校验产物。

    跳过条件：未显式开启环境变量；或本机 pywin32 / Excel COM 不可用。
    """
    # 探测阶段一：pywin32 是否可用（CI 装了 pywin32 但环境门已先行跳过）
    try:
        import pywintypes
        import win32com.client
    except ImportError as exc:
        pytest.skip(f"pywin32 不可用，无法执行真实 Excel COM 测试: {exc}")

    from executors.excel_executor import ExcelExecutor

    tmp_xlsx = tmp_path / "local_integration_roundtrip.xlsx"

    # 阶段二：通过真实 COM 创建临时工作簿。DispatchEx 同时充当 Excel 可用性
    # 探测：启动失败（未安装 Excel / COM 注册损坏）按跳过处理而非失败。
    # 创建阶段必须在 finally 中 Close + Quit，避免遗留 Excel 进程持有文件锁；
    # 后续执行阶段由 ExcelExecutor 自行管理其独立的 COM 生命周期。
    excel = None
    workbook = None
    try:
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
        except (pywintypes.com_error, OSError) as exc:
            pytest.skip(f"本机无法启动 Excel COM（可能未安装 Excel）: {exc}")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Add()
        workbook.Worksheets(1).Cells(1, 1).Value = "workflow-local-integration"
        workbook.SaveAs(str(tmp_xlsx), FileFormat=XL_OPEN_XML_WORKBOOK)
    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except (pywintypes.com_error, OSError):
                pass
        if excel is not None:
            try:
                excel.Quit()
            except (pywintypes.com_error, OSError):
                pass

    assert tmp_xlsx.exists(), "COM 创建临时 .xlsx 失败"
    mtime_before = tmp_xlsx.stat().st_mtime
    # 让后续保存的 mtime 严格大于创建时间（防御文件系统时间戳粒度）
    time.sleep(1.0)

    result = ExcelExecutor().execute(
        script_path=str(tmp_xlsx),
        log_dir=tmp_path,
        timeout=120,
    )

    assert result.success is True, f"ExcelExecutor 真实刷新失败: {result.error_message}"
    stdout_path = Path(result.stdout_path)
    assert stdout_path.exists(), "stdout 日志文件未生成"
    assert stdout_path.read_text(encoding="utf-8").strip(), "stdout 日志为空"
    assert tmp_xlsx.stat().st_mtime > mtime_before, "刷新保存后 .xlsx 的 mtime 未前进"


@pytest.mark.local_integration
@pytest.mark.skipif(
    not os.environ.get("WORKFLOW_TEST_DINGTALK_WEBHOOK"),
    reason="未设置 WORKFLOW_TEST_DINGTALK_WEBHOOK，默认跳过真实钉钉发送测试",
)
def test_dingtalk_real_send():
    """真实钉钉发送：向环境变量提供的机器人真实发送一条集成测试消息。"""
    url = os.environ["WORKFLOW_TEST_DINGTALK_WEBHOOK"]
    keyword = os.environ.get("WORKFLOW_TEST_DINGTALK_WEBHOOK_KEYWORD", "")

    ok, message = notifier.send_dingtalk_message(
        url,
        "【集成测试】Workflow 本地集成测试消息",
        keyword=keyword,
    )

    # send_dingtalk_message 返回的 message 已做 access_token 脱敏，可安全展示
    assert ok is True, f"真实钉钉发送失败: {message}"


@pytest.mark.local_integration
def test_local_integration_marker_registered_in_pytest_ini():
    """廉价 wiring 自检（CI 中照常执行）：marker 必须已在 pytest.ini 注册。

    防止 pytest.ini 的 markers 注册被误删导致本层测试退化为未注册 marker。
    """
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "markers" in text, "pytest.ini 缺少 markers 配置段"
    assert "local_integration:" in text, "pytest.ini 未注册 local_integration marker"
    assert "默认跳过" in text, "local_integration marker 描述应注明默认跳过"
