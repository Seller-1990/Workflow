# Workflow fuck-my-shit-mountain Full 模式代码体检报告（Deep Fix 修复后）

- 项目路径：`D:\OneDrive - PowerBI学谦\Software Development\desktop\Workflow`
- 报告日期：2026-06-09
- 执行模式：Goal / 多分片方案设计 / 审查合并 / 最小风险修复 / 多分片复审 / fuck-my-shit-mountain full
- 总结论：**PASS。本轮已按审查报告问题完成最小风险修复，并把关键风险从“人工发现”升级为“可执行质量门”。**

## 0. 交付物与证据索引

| 类型 | 路径 | 用途 |
|---|---|---|
| 最终中文 Markdown 报告 | `D:\OneDrive - PowerBI学谦\Software Development\desktop\Workflow\audit-report-Workflow-2026-06-09-deep-fix-full.md` | fuck-my-shit-mountain full / Deep Fix 修复后主交付物 |
| 合并批准方案 | `plan_workflow_deep_fix/approved_fix_plan.md` | 记录四批次方案审查、取舍、修改范围与回滚半径 |
| 修复后复审报告 | `plan_workflow_deep_fix/review_worker_security/report.md`、`review_worker_testing/report.md`、`review_worker_architecture/report.md`、`review_worker_runtime/report.md` | 四分片并行复审 PASS 证据 |
| Deep Fix VERIFY | `plan_workflow_deep_fix/verify_results.md` | 报告存在、必需章节、4份复审、测试证据与计划状态验证 |
| FMSM质量检查 | `plan_workflow_fmsm/deep_fix_report_quality_check.json` | 检查报告是否包含 full 模式、4批次、评分、PASS、最新测试证据和章节顺序 |
| 独立最终VERIFY | `plan_workflow_fmsm/independent_final_verify_deep_fix.json` | 交叉核对报告、计划勾选、复审PASS、评分与表格结构，`all_ok=true` |
| 第5轮审阅变更面探针 | `plan_workflow_fmsm/wakeup5_reviewer_change_map_probe.json`、`plan_workflow_fmsm/wakeup5_change_surface_probe.json` | 面向首次审阅者统计当前 49 个改动文件的类别、插入/删除规模与优先审阅路径，降低大 diff 归因成本 |
| 第5轮行尾策略守卫 | `.gitattributes`、`tests/test_repo_hygiene.py`、`plan_workflow_fmsm/wakeup5_gitattributes_guard_verify_v2.json`、`plan_workflow_fmsm/wakeup5_full_pytest_after_gitattributes.json` | 锁定文本文件 LF 与二进制不转换；`git check-attr` 确认二进制 `text unset/eol unspecified`，全量回归 `316 passed` |

### 0.1 首次审阅者导航

本轮改动横跨工具、CI、执行器、UI、数据库、测试与报告。为避免审阅者被大 diff 淹没，建议按“风险闭环”而不是按文件名顺序审阅：

| 审阅顺序 | 关注问题 | 代表文件 | 已有验证/锁定 |
|---:|---|---|---|
| 1 | 新增质量门是否真的会失败，而不是只输出提示 | `tools/audit_risky_calls.py`、`tools/audit_broad_except.py`、`tests/test_audit_risky_calls.py`、`tests/test_audit_broad_except.py` | 显式危险样本/坏目标负例、allowlist reason 校验、相关审计测试 |
| 2 | CI/Package 是否绕过本地 gate，发布产物缺失是否会软成功 | `.github/workflows/ci.yml`、`.github/workflows/package.yml`、`tests/test_ci_workflow_guards.py` | workflow 文本守卫、pre-build guard 模拟、`if-no-files-found: error` 与 exe/sha256 路径测试 |
| 3 | 大量测试新增是否只测实现细节，还是覆盖用户可感知契约 | `tests/test_ui_main_window_actions.py`、`tests/test_executor_policies.py`、`tests/test_schema_guards.py`、`tests/test_cli_contracts.py` | 全量 `316 passed`；关键守卫组合 `22 passed`；UI/CI/main 相关 `34 passed`；仓库行尾策略守卫已加入 repo hygiene |
| 4 | 运行时修复是否引入启动副作用或 Windows 编码回归 | `src/main.py`、`_import_and_run.py`、`src/config.py` | `--help` 隔离探针确认无 app-data 副作用；CLI 合同测试覆盖 UTF-8 错误输出 |
| 5 | 架构债是否被“声明修复”但实际只隐藏风险 | `tools/module_hotspot_report.py`、`docs/development_guardrails.md`、`src/ui/main_window.py`、`src/database.py`、`src/engine.py` | 热点报告阈值失败模式已可用；报告明确保留巨型模块拆分为后续风险，不把本轮守卫增强包装成彻底重构 |

## 1. 执行摘要

本轮目标不是对核心业务做大重构，而是针对既有审查报告暴露的问题，先用并行分片方案收敛风险，再实施可验证、可回退的守卫增强。

已完成：

1. 探索当前仓库、既有审查报告、git diff、测试和工具现状。
2. 按安全执行、运行稳定性、测试发布、架构维护性四个方向设计修复方案。
3. 合并并审查方案，形成 `plan_workflow_deep_fix/approved_fix_plan.md`。
4. 按方案修改工具、测试、文档、CI/package 工作流，并只对 `_import_and_run.py` 做测试暴露出的局部编码修复。
5. 完整验证：`python -m pytest -q` 通过，结果为 **316 passed**；本轮追加了审计工具显式路径负例测试，确认临时危险样本会被 gate 拒绝；同时补充无效目标测试，确认不存在路径/非 `.py` 文件不会被空扫描静默放过；并从 package 执行者角度物理模拟打包前质量门序列，最终 **ALL_OK True**，`tools/run_tests.py --collect-only` 为 **309 collected**。
6. 修复后四分片复审均为 **PASS**。
7. 追加回归修复：完整回归暴露 `StepTablePanel` 初始化仍引用已抽离的样式表方法，已改为直接使用 `build_table_stylesheet(COLORS)`，对应 8 个 UI 回归测试与全量测试均通过。

## 2. 本轮实际修复内容

### 2.1 高风险调用审计升级为失败型 gate

相关文件：

- `tools/audit_risky_calls.py`
- `tests/test_audit_risky_calls.py`
- `docs/execution_security_checklist.md`

修复点：

- 扫描 `eval` / `exec` / `compile` / `os.system` / `os.popen` / `subprocess.run` / `subprocess.Popen` 等高风险调用。
- 将现有已审查调用纳入 allowlist，并要求每个 allowlist 项必须有 reason。
- 新增未知高风险调用或 `shell=True` 未获批准时返回非 0。
- 匹配策略基于文件路径和调用类型，避免依赖脆弱行号。

### 2.2 broad exception 审计升级为失败型 gate

相关文件：

- `tools/audit_broad_except.py`
- `tests/test_audit_broad_except.py`

修复点：

- 扫描裸 `except:`、`except Exception:`、`except BaseException:`。
- 当前历史存量通过 allowlist 固定，防止无意识新增 broad exception。
- allowlist 项必须带 reason；测试覆盖“新增未批准 broad except 应失败”。

### 2.3 模块热点报告增强

相关文件：

- `tools/module_hotspot_report.py`
- `tests/test_module_hotspot_report.py`
- `docs/development_guardrails.md`

修复点：

- 保留默认报告模式，输出大文件/复杂模块排行。
- 增加 `--max-lines` 与 `--fail-on-threshold`，后续可在 CI 中逐步启用硬阈值。
- 通过测试覆盖默认输出、阈值失败、参数行为。

### 2.4 CI 与 Package 工作流纳入守卫

相关文件：

- `.github/workflows/ci.yml`
- `.github/workflows/package.yml`
- `tests/test_ci_workflow_guards.py`

修复点：

- CI 新增测试环境预检。
- CI/Package 均加入风险与架构守卫：requirements consistency、risky calls、broad except、module hotspot、collect-only。
- 打包前执行同一组质量门，减少“测试能过但发布包绕过守卫”的风险。
- Package artifact 上传显式设置 `if-no-files-found: error`，并将 exe 与 `.sha256` 两个输出路径写入 workflow 守卫测试，避免上传步骤在产物缺失时降级为软成功。

### 2.5 开发与执行安全文档补齐

相关文件：

- `docs/development_guardrails.md`
- `docs/execution_security_checklist.md`
- `tests/test_docs_guardrails.py`

修复点：

- 明确本地修改前后建议运行的守卫命令。
- 记录执行器、subprocess、`shell=True`、allowlist、异常处理和发布前检查要求。
- 文档测试确保关键命令和安全关键词不会被误删。

### 2.6 CLI 错误输出编码修复

相关文件：

- `_import_and_run.py`
- `tests/test_cli_contracts.py` 既有合同测试

修复点：

- 完整回归时发现 Windows 子进程中文错误输出在测试按 UTF-8 读取时乱码。
- 已显式设置 stdout/stderr UTF-8，并在 `FileNotFoundError` 路径使用 UTF-8 写出。
- 目标用例与完整测试均通过。

### 2.7 仓库行尾策略与跨平台 diff 噪声控制

相关文件：

- `.gitattributes`
- `tests/test_repo_hygiene.py`

修复点：

- 新增仓库级行尾策略：全局 `text=auto`，源代码/文档/CI/配置等文本类型显式 `eol=lf`。
- 将 png/ico/db/sqlite/exe/dll/zip 等二进制产物标记为 `binary`，避免行尾转换误伤。
- `git check-attr` 已确认文本路径为 `eol: lf`，二进制路径为 `text: unset` / `eol: unspecified`；repo hygiene 新增测试锁定该策略。
- 注意：新增策略后，当前已有 CRLF 工作树文件在 `git diff --check` 中会提示下一次 Git touch 时归一化为 LF；本轮未执行大规模 renormalize，以避免无关行尾变更淹没 Deep Fix diff。

## 3. 验证证据

### 3.0 四批次 Deep Fix 闭环与评分

本轮 Deep Fix 不是单点修补，而是以 4 个批次将历史架构债从“报告里的风险描述”推进到“可执行、可复审、可继续收敛的质量门”。批次设计、合并审查、代码修改与修复后复审的证据如下：

| 批次 | 初步方案来源 | 合并后批准动作 | 修改/优化落点 | 修复后复审 | 批次评分 |
|---|---|---|---|---|---:|
| Batch A：高风险调用白名单化 | `fix_plan_worker_security_exec/plan.md` | 未知 `eval/exec/compile/os.system/os.popen/subprocess.run/subprocess.Popen` 失败；allowlist 必须有 reason；`shell=True` 必须显式批准；显式传入不存在/非 `.py` 目标返回 2，防止空扫描误通过 | `tools/audit_risky_calls.py`、`tests/test_audit_risky_calls.py`、`docs/execution_security_checklist.md` | 安全执行分片 PASS：未批准高风险调用为 0；显式坏目标/危险样本均有负例测试 | 93/100 |
| Batch B：broad except 审计升级 | `fix_plan_worker_security_exec/plan.md` + `fix_plan_worker_stability_runtime/plan.md` | 新增裸 `except:`、`except Exception:`、`except BaseException:` 未批准即失败；reason 缺失失败；显式传入不存在/非 `.py` 目标返回 2，防止拼错路径造成假阴性 | `tools/audit_broad_except.py`、`tests/test_audit_broad_except.py` | 安全/运行分片 PASS：未批准 broad exception 为 0；显式坏目标/宽泛异常样本均有负例测试 | 91/100 |
| Batch C：CI/package 绑定守卫 | `fix_plan_worker_testing_release/plan.md` | 本地 guard 必须进入 CI 和 Package，防止发布链路绕过审计；artifact 上传必须对缺失文件硬失败 | `.github/workflows/ci.yml`、`.github/workflows/package.yml`、`tests/test_ci_workflow_guards.py` | 测试发布分片 PASS：本地全量测试 316 passed，工作流文本锁定质量门、verify-before-upload 与 `if-no-files-found: error` | 94/100 |
| Batch D：热点/开发守卫可发现性 | `fix_plan_worker_maint_arch/plan.md` | 热点报告支持阈值失败模式；开发文档列出关键质量门，避免守卫资产成为孤岛 | `tools/module_hotspot_report.py`、`tests/test_module_hotspot_report.py`、`docs/development_guardrails.md`、`tests/test_docs_guardrails.py` | 架构维护分片 PASS：未大拆巨型模块，但建立后续拆分可量化入口 | 88/100 |

综合评分（fuck-my-shit-mountain full / Deep Fix 后）：**92/100**。

评分拆解：

| 维度 | 分数 | 扣分原因 |
|---|---:|---|
| 安全执行边界 | 93 | 已冻结新增未知高风险调用，并补上显式坏目标返回 2 的防空扫描负例；扣分点是执行器历史 `subprocess/Popen` 行为尚未完全策略化（timeout/cwd/env/参数合同仍需后续细化）。 |
| 稳定性/异常治理 | 90 | broad-except 新增风险已变成失败型 gate，且拼错/非 `.py` 目标不会再静默通过；扣分点是历史 broad-except 存量仍多，本轮选择冻结而非一次性清除。 |
| 测试与发布闭环 | 98 | 本地 `pytest -q` 为 316 passed，CI/package 已绑定守卫；新增显式路径负例确认危险样本会被审计脚本拒绝；package workflow 已补 `requirements-release.txt` + `requirements-ci.txt` 安装顺序，并在 `pyinstaller` 前运行 docs/CI workflow guard 测试；artifact 上传已锁定 `if-no-files-found: error` 且测试覆盖 exe/sha256 输出路径；本地已模拟 package pre-build guard 全序列 ALL_OK，collect-only 309 collected；扣分点仅剩远端 GitHub Actions 尚未在本轮物理触发确认。 |
| 架构可维护性 | 87 | module hotspot 已可量化并可阈值失败；扣分点是 `main_window.py/database.py/engine.py` 等巨型模块仍未拆分。 |
| 可追溯性/回滚半径 | 93 | 方案、审查、修改、复审和VERIFY证据链完整；扣分点是仓库存在大量历史未提交变更，本报告需明确归因边界。 |

判定：**PASS（可进入代码审阅/远端CI验证）**。本轮已经达到“Deep Fix 第二阶段”的核心目标：不做高半径重写，而是把最高风险的历史债务转成可持续执行的守卫、测试和复审闭环。

| 命令 | 返回码 | 结果 |
|---|---:|---|
| `python tools/audit_risky_calls.py` | 0 | `Unapproved risky call sites: 0` |
| `python tools/audit_broad_except.py` | 0 | `Unapproved broad exception handlers: 0` |
| `python tools/module_hotspot_report.py` | 0 | 成功输出热点排行 |
| `python tools/check_requirements_consistency.py` | 0 | 依赖一致性检查通过 |
| `python tools/check_test_env.py` | 0 | 测试环境检查通过 |
| `python tools/run_tests.py --collect-only` | 0 | 309 collected；package workflow 依赖修复后 collect-only 守卫具备 pytest 可用性 |
| `python tools/audit_risky_calls.py C:\Users\Seller\GenericAgent\temp\plan_workflow_fmsm\adversarial_guard_probe_v3\bad_risky.py` | 1 | 显式路径危险样本被拒绝：`shell=True is forbidden` |
| `python tools/audit_broad_except.py C:\Users\Seller\GenericAgent\temp\plan_workflow_fmsm\adversarial_guard_probe_v3\bad_broad.py` | 1 | 显式路径宽泛异常样本被拒绝：`broad-except missing allowlist reason` |
| `python tools/audit_risky_calls.py <missing.py / not_python.txt>` | 2 | 显式无效目标被拒绝：`Invalid audit target`，防止拼错路径空扫描 |
| `python tools/audit_broad_except.py <missing.py / not_python.txt>` | 2 | 显式无效目标被拒绝：`Invalid audit target`，防止拼错路径空扫描 |
| `python -m pytest tests/test_ui_main_window_actions.py ... tests/test_watch_ui.py` | 0 | 8 passed；确认 StepTablePanel 样式表初始化回归已修复 |
| `python -m pytest tests/test_audit_risky_calls.py tests/test_audit_broad_except.py tests/test_module_hotspot_report.py tests/test_ci_workflow_guards.py tests/test_docs_guardrails.py -q` | 0 | 19 passed；新增文档守卫锁定审计 CLI 显式路径与返回码合同，CI workflow 守卫锁定 package 安装 `requirements-ci.txt` 与打包前 docs/CI guard 测试 |
| `python -m pytest tests/test_cli_contracts.py::test_import_and_run_import_requires_existing_json_file -q` | 0 | 1 passed |
| `python -m pytest tests/test_ci_workflow_guards.py tests/test_docs_guardrails.py -q` | 0 | 6 passed；验证 package workflow 安装 CI 依赖并在 pyinstaller 前运行 docs/CI workflow guard 测试，且 `Verify artifact` 早于 `Upload artifact` 被测试锁定 |
| `python -m pytest tests/test_ci_workflow_guards.py -q` | 0 | 3 passed；第4次唤醒追加验证 artifact 上传 `if-no-files-found: error`，并锁定 exe 与 `.sha256` 输出路径 |
| `python -m pytest -q` | 0 | 316 passed；新增 `.gitattributes` 行尾策略守卫后全量回归通过 |
| `python -m pytest tests/test_main_self_check.py::test_main_help_returns_without_starting_gui -q` | 0 | 1 passed；确认 `--help` 不创建隔离 app-data，不提前初始化 GUI/config |

## 4. 修复后复审结论

复审报告已落盘：

- `plan_workflow_deep_fix/review_worker_security/report.md`：PASS
- `plan_workflow_deep_fix/review_worker_testing/report.md`：PASS
- `plan_workflow_deep_fix/review_worker_architecture/report.md`：PASS
- `plan_workflow_deep_fix/review_worker_runtime/report.md`：PASS

### 4.1 安全执行分片

结论：**PASS**。

依据：高风险调用与 broad exception 均已从报告型脚本升级为失败型 gate；allowlist 必须写明 reason；新增未知风险会导致非 0。

保留风险：执行器中的 subprocess/Popen 是业务核心路径，本轮未改变运行行为；后续应逐步补 timeout/cwd/env/参数约束的更细合同测试。

### 4.2 测试发布分片

结论：**PASS**。

依据：本地完整 pytest 通过，CI 和 Package 均已纳入新增质量门，文档与工作流有测试锁定；Package 上传步骤已显式对缺失 artifact 硬失败，避免发布产物缺失时误上传成功。

保留风险：GitHub Actions 远端实际运行仍需后续在 PR/Push 中确认。

### 4.3 架构维护性分片

结论：**PASS**。

依据：module hotspot 支持报告与阈值失败模式；本轮未拆核心大文件，避免引入高半径回归。

保留风险：`src/ui/main_window.py`、`src/database.py`、`src/engine.py` 等热点模块仍大，建议后续专门开拆分计划。

### 4.4 运行稳定性分片

结论：**PASS**。

依据：完整回归暴露并修复 CLI 中文错误输出编码问题；目标用例和全量测试均通过。

保留风险：未执行真实 Excel/PowerBI 外部程序集成，本轮以静态 gate、合同测试和单元测试控制风险。

## 5. Git/归因说明

当前工作区存在大量历史未提交变更和本轮新增文件。第6轮从“首次接手提交者/发布维护者”视角补充完整归因入口，避免只看代表文件导致新增守卫、质量基线、运行时辅助模块或根配置漏提交。

### 5.1 本轮交付面完整清单

生成依据：`git diff --name-only` + `git diff --cached --name-only` + `git ls-files --others --exclude-standard`，并排除旧审计报告、旧阶段性验证文本和异常引号路径样本。机器可读证据见 `plan_workflow_fmsm/wakeup6_delivery_change_manifest.json`，Markdown 清单见 `plan_workflow_fmsm/wakeup6_delivery_change_manifest.md`。

- **根配置/发布配置（7）**
  - `.gitattributes` (untracked)
  - `build.spec` (modified)
  - `build_slim.spec` (modified)
  - `build_slim2.spec` (modified)
  - `requirements-ci.txt` (modified,staged)
  - `requirements-release.txt` (modified)
  - `requirements.txt` (modified)
- **CI/Package 工作流（2）**
  - `.github/workflows/ci.yml` (modified)
  - `.github/workflows/package.yml` (modified)
- **文档/开发守则（3）**
  - `README.md` (modified)
  - `docs/development_guardrails.md` (untracked)
  - `docs/execution_security_checklist.md` (untracked)
- **执行器/运行时/CLI（11）**
  - `_import_and_run.py` (modified)
  - `src/cli.py` (modified)
  - `src/executors/__init__.py` (modified)
  - `src/executors/base.py` (modified)
  - `src/executors/excel_executor.py` (modified)
  - `src/executors/powerbi_executor.py` (modified)
  - `src/executors/python_executor.py` (modified)
  - `src/executors/result_policy.py` (untracked)
  - `src/executors/sub_workflow_executor.py` (modified)
  - `src/runtime/__init__.py` (untracked)
  - `src/runtime/process_runner.py` (untracked)
- **报告（1）**
  - `audit-report-Workflow-2026-06-09-deep-fix-full.md` (untracked)
- **质量基线（1）**
  - `quality/module_hotspot_baseline.json` (untracked)
- **业务核心/配置/模型（12）**
  - `src/config.py` (modified)
  - `src/database.py` (modified)
  - `src/database_import_export.py` (modified)
  - `src/database_versions.py` (modified)
  - `src/engine.py` (modified)
  - `src/engine_core/log_cleanup.py` (modified)
  - `src/engine_core/watcher.py` (modified)
  - `src/main.py` (modified)
  - `src/models.py` (modified)
  - `src/notifier.py` (modified)
  - `src/watch_rules.py` (modified)
  - `src/webhook_url_policy.py` (untracked)
- **UI（7）**
  - `src/ui/main_window.py` (modified)
  - `src/ui/step_editor.py` (modified)
  - `src/ui/step_table/panel.py` (modified)
  - `src/ui/step_table/styles.py` (untracked)
  - `src/ui/webhook_manager.py` (modified)
  - `src/ui/workflow_config.py` (modified)
  - `src/ui/workflow_list.py` (modified)
- **测试/回归守卫（27）**
  - `tests/conftest.py` (untracked)
  - `tests/test_audit_broad_except.py` (untracked)
  - `tests/test_audit_risky_calls.py` (untracked)
  - `tests/test_build_slim_rules.py` (modified)
  - `tests/test_ci_workflow_guards.py` (untracked)
  - `tests/test_cli_contracts.py` (modified)
  - `tests/test_cli_subprocess.py` (untracked)
  - `tests/test_database_versions.py` (modified)
  - `tests/test_dependency_manifest.py` (modified)
  - `tests/test_docs_guardrails.py` (untracked)
  - `tests/test_engine_core_log_cleanup.py` (modified)
  - `tests/test_executor_policies.py` (modified)
  - `tests/test_executor_runtime_cleanup.py` (untracked)
  - `tests/test_main_self_check.py` (untracked)
  - `tests/test_module_hotspot_report.py` (untracked)
  - `tests/test_notifier.py` (modified)
  - `tests/test_process_runner.py` (untracked)
  - `tests/test_repo_hygiene.py` (modified)
  - `tests/test_requirements_consistency.py` (untracked)
  - `tests/test_schema_guards.py` (modified)
  - `tests/test_step_table_styles.py` (untracked)
  - `tests/test_ui_main_window_actions.py` (modified)
  - `tests/test_ui_security.py` (modified)
  - `tests/test_watch_engine.py` (modified)
  - `tests/test_watch_rules.py` (modified)
  - `tests/test_watch_ui.py` (modified)
  - `tests/test_workflow_config_guard.py` (modified)
- **质量门工具（8）**
  - `tools/audit_broad_except.py` (untracked)
  - `tools/audit_risky_calls.py` (untracked)
  - `tools/check_requirements_consistency.py` (untracked)
  - `tools/check_test_env.py` (untracked)
  - `tools/module_hotspot_baseline.json` (untracked)
  - `tools/module_hotspot_report.py` (untracked)
  - `tools/repo_hygiene.py` (modified)
  - `tools/run_tests.py` (untracked)

### 5.2 提交边界与注意事项

- `requirements-ci.txt` 当前是 **AM 双层状态**：index 中已暂存新增文件初版，worktree 又追加了 `certifi==2026.1.4`。正式提交前必须以最终工作树内容重新统一 stage，或显式确认 index 与 worktree 差异；否则容易只提交缺少 `certifi` 的 CI 依赖文件，造成 package/CI 语义与本地验证不一致。
- `.gitattributes` 与 `tests/test_repo_hygiene.py` 是第5轮新增的行尾策略闭环，属于本轮可交付面；不要因其未跟踪而遗漏。
- 旧审计报告、旧阶段验证输出、`wake2_progress*` 等历史产物不应作为本轮 Deep Fix 主提交依据；本报告仅引用当前 full 报告与工作目录证据。
- 行尾策略已设置 LF/二进制保护，但本轮未执行大规模 renormalize；若后续统一 stage 出现大量纯行尾 diff，应单独提交或单独说明，避免与架构债修复混淆。

## 6. 建议后续动作

1. 在远端 GitHub Actions 上触发 CI 和 Package workflow，确认 Windows hosted runner 与本地一致，特别确认 package job 的 `requirements-release.txt` + `requirements-ci.txt` 安装顺序、打包前 docs/CI guard 测试、hotspot baseline gate 与 collect-only 全序列。
2. 将执行器 subprocess/Popen 的策略测试继续细化到 timeout、cwd、env、参数 allowlist。
3. 审计 CLI 的显式路径模式已纳入开发文档并由文档测试锁定；后续在 CI 示例中继续保持无效目标返回 2、危险样本返回 1 的语义不回退。
4. 以单独计划拆分热点模块，不要与安全策略改造混在同一批次。
5. 对 historical broad-except 逐模块收敛，每次只处理少量文件并保持 pytest 绿。

## 7. 最终结论

本轮 Deep Fix 已完成闭环：**方案设计 → 方案审查 → 最小风险修复 → 完整测试 → 多分片复审 → full 模式中文报告**。

当前可交付状态：**通过本地验证，建议进入代码审阅/远端 CI 验证阶段。**

## 8. 第7轮首次审阅者/攻击者视角补充核验（当前仓库版）

本节为当前仓库补回版新增内容，用于修正“主报告只存在于 cleanup backup、当前 repo 缺失主交付物”的交付边界问题，并记录最新已进入 Git 基线的 UI 依赖错误定位鲁棒性修复。

### 8.1 最新基线证据

- 当前 Git 最近提交：`ac47aa4 fix: harden dependency error step locator`、`63c75f4 fix: make dependency mutation errors actionable`、`623b318 ci: force utf-8 for windows test jobs`。
- 当前工作树核验：`git status --porcelain=v1 --untracked-files=all` 输出为空，说明本报告生成前代码基线干净。
- 关键回归：`python -m pytest tests/test_ui_main_window_actions.py tests/test_executor_policies.py tests/test_ci_workflow_guards.py tests/test_repo_hygiene.py -q` → **89 passed in 1.41s**。
- UI 定位专项：`python -m pytest tests/test_ui_main_window_actions.py -q` → **33 passed**。

### 8.2 新增修复：依赖错误定位可行动性加固

首次审阅者/攻击者视角发现：依赖错误弹窗虽然提供“定位问题步骤”，但若错误消息中的 uid 不是固定 `uid=...` 格式，或目标行已被过滤/刷新导致 `select_step` 抛错，用户会看到不可定位或潜在 UI 异常。

已进入基线的修复：

- `src/ui/step_table/panel.py`：依赖错误解析支持 `uid=xxx`、`uid='xxx'`、`uid="xxx"` 与 JSON 风格 `"uid":"xxx"`；定位按钮执行时捕获 `RuntimeError/ValueError/TypeError` 并通过状态栏提示失败原因，避免弹窗操作变成二次异常。
- `tests/test_ui_main_window_actions.py`：新增 JSON/引号 uid 解析用例，以及 `select_step` 失败时的状态栏兜底用例。

### 8.3 当前评分微调

综合评分维持 **92/100（A-）**。理由：本轮补丁提升了 UI 可行动性和审阅者可验证性，但不改变第二阶段 Deep Fix 的主要架构债边界；剩余风险仍集中在执行器 subprocess/Popen 参数策略、远端 GitHub Actions 实跑确认、热点模块渐进拆分。

### 8.4 当前仓库交付边界修正

此前 `audit-report-Workflow-2026-06-09-deep-fix-full.md` 仅在 `Workflow_cleanup_backup_20260609_163727` 中可被 `es` 定位，当前 repo 根目录缺失该主交付物。当前文件即为补回后的主报告，避免审阅者只拿到代码提交却找不到 full 模式中文评分报告。
