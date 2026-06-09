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
