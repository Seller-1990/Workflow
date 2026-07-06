# Development Guardrails

本项目的低风险修改应优先通过守卫脚本验证，而不是依赖人工记忆。

## 修改前后建议命令

```bash
python tools/check_test_env.py
python tools/check_requirements_consistency.py
python tools/audit_risky_calls.py
python tools/audit_broad_except.py
python tools/module_hotspot_report.py
python tools/run_tests.py --collect-only
```

`tools/check_test_env.py` 会在 pytest 前检查核心测试依赖（如 `SQLAlchemy`、`PySide6`、`watchdog`），缺失时先给出安装命令，避免直接进入 pytest 后出现不透明的导入失败。

## 审计 CLI 合同

`tools/audit_risky_calls.py` 与 `tools/audit_broad_except.py` 均支持两种模式：

- 不带参数：扫描仓库默认目标，用于本地/CI 质量门。
- 带显式路径：只扫描给定 `.py` 文件或目录，用于复现单个风险样本。

返回码语义必须保持稳定：

- `0`：扫描完成，未发现未批准风险。
- `1`：扫描完成，发现未批准风险调用或 broad exception。
- `2`：调用方式/目标无效，例如路径不存在或目标不是 `.py` 文件。该语义用于防止拼错路径导致空扫描误通过。

## 风险调用规则

- 新增 `subprocess` / `Popen` / `eval` / `exec` / `compile` 调用必须先解释必要性。
- 禁止 `shell=True`。
- 如必须保留风险调用，必须更新 `tools/audit_risky_calls.py` 中 allowlist reason，并补充测试。

## broad except 规则

新增裸 `except:`、`except Exception`、`except BaseException` 应优先收窄异常类型；不能收窄时必须有明确技术债原因与回归测试。

## 热点模块规则

`tools/module_hotspot_report.py --max-lines N --fail-on-threshold` 可作为预警，不在本轮强制拆分 `src/ui/main_window.py`、`src/database.py`、`src/engine.py`。

## 本地强制：git hooks

以上质量门此前依赖自觉执行，已出现红门改动直接提交入库的案例。仓库现提供受版本控制的钩子目录 `.githooks/`，安装后由 git 在本地强制执行：

```bash
python tools/install_hooks.py             # 安装：git config core.hooksPath .githooks
python tools/install_hooks.py --uninstall # 卸载：恢复默认钩子目录
```

安装脚本幂等，可重复执行；只修改当前仓库的本地 `core.hooksPath`，不触碰全局 git 配置。每个克隆/每台机器需各执行一次。非 Windows 环境如钩子未被执行，先 `chmod +x .githooks/pre-commit .githooks/pre-push`。

### 提交时执行（pre-commit，快速门）

- `python tools/audit_broad_except.py`
- `python tools/audit_risky_calls.py`
- `python tools/module_hotspot_report.py --top 0 --baseline quality/module_hotspot_baseline.json --fail-on-regression`
- `python -m compileall -q src tests _import_and_run.py`

### 推送时执行（pre-push，完整门）

快速门全部项，外加 `python -m pytest -q`。

### 紧急跳过与代价

`git commit --no-verify` / `git push --no-verify` 可跳过钩子，仅限紧急情况（如钩子自身故障、阻塞线上回滚）。跳过意味着红门改动可能入库：远端 CI 会再次拦截，但此时修复成本更高，还会污染主干历史。跳过后必须尽快手动补跑上述全部质量门并修复问题。

### 远端分支保护（尚未启用，由仓库所有者决定）

本地钩子可被 `--no-verify` 绕过，最终防线是 GitHub 分支保护。以下步骤**当前尚未执行**，是否启用、何时推送由仓库所有者决定：

1. 将 `main` 推送到远端 `github.com/Seller-1990/Workflow`，并让 CI（`.github/workflows/ci.yml`，工作流名 `CI`）至少跑过一次。
2. 打开仓库 Settings → Branches → Add branch protection rule，分支名填 `main`。
3. 勾选 "Require status checks to pass before merging"，搜索并选择状态检查 `test`（来自 `CI` 工作流的 `test` job，界面中可能显示为 `CI / test`）。
4. 勾选 "Require branches to be up to date before merging"（对应 API 的 `strict=true`）。
5. 如需对管理员同样生效，勾选 "Do not allow bypassing the above settings"。

也可用 `gh` CLI 一条命令完成（字段语法以当前 gh 版本文档为准）：

```bash
gh api -X PUT repos/Seller-1990/Workflow/branches/main/protection \
  -F "required_status_checks[strict]=true" \
  -F "required_status_checks[contexts][]=test" \
  -F enforce_admins=true \
  -F required_pull_request_reviews=null \
  -F restrictions=null
```

## 本地真实外设集成测试

既有测试对 Excel COM 与钉钉网络全部使用 mock，真实外设路径此前只能在生产环境验证。`tests/test_local_integration.py` 补上这一层 OPT-IN 的本地集成测试，统一使用 pytest marker `local_integration`（已在 `pytest.ini` 注册）：

- `test_excel_executor_real_com_roundtrip`：通过真实 COM 创建临时 `.xlsx`，再用 `ExcelExecutor` 真实启动 Excel 刷新并保存，校验执行结果、stdout 日志与文件 mtime 前进。
- `test_dingtalk_real_send`：调用 `notifier.send_dingtalk_message` 向真实机器人发送一条测试消息，断言发送成功（返回信息已做 token 脱敏）。
- `test_local_integration_marker_registered_in_pytest_ini`：廉价 wiring 自检，CI 中照常执行，防止 marker 注册被误删。

### 运行方式（Windows cmd）

```bash
set WORKFLOW_LOCAL_INTEGRATION=1 && python -m pytest tests/test_local_integration.py -m local_integration -q
```

钉钉测试需要额外提供真实机器人地址（必须是 `https://oapi.dingtalk.com/robot/send` 下的地址，URL 策略会拒绝其他主机）：

```bash
set WORKFLOW_TEST_DINGTALK_WEBHOOK=<真实机器人URL>
set WORKFLOW_TEST_DINGTALK_WEBHOOK_KEYWORD=<可选：机器人自定义关键词>
python -m pytest tests/test_local_integration.py -m local_integration -q
```

### 安全注意

- Excel 测试**会真实启动 Excel**（创建与执行阶段各启动并退出一次），整体约需 20 秒；运行期间不要手工操作 Excel，避免干扰 COM 会话。
- 钉钉测试**会真实发送一条钉钉消息**到目标机器人群，内容为「【集成测试】Workflow 本地集成测试消息」。
- 真实 Webhook 地址只允许通过环境变量注入，不要写入任何仓库文件；`tools/repo_hygiene.py` 会扫描 token 残留。

### 默认跳过（CI / hooks 不受影响）

两个真实外设测试均通过 `skipif` 环境变量门控：CI（`pytest -q`）、git hooks（pre-push 的 `python -m pytest -q`）与未设置环境变量的本地运行只会显示 skipped，不会启动 Excel、也不会发起任何网络请求，质量门保持绿色；`tools/run_tests.py --collect-only` 的收集数随之增加属预期，无固定数量断言。

