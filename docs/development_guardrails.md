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

