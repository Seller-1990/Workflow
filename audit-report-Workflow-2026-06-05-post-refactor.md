# Fuck My Shit Mountain Audit Report

**Project:** Workflow
**Audit mode:** full
**Date:** 2026-06-05
**Reviewer:** Codex / GPT-5

---

## 1. Executive Summary

本次审计是在前一轮修复和拆分之后进行的全量复查。项目已经比旧状态健康很多：`pytest -q` 当前为 `117 passed`，`compileall` 和 CLI smoke 通过；Webhook 普通导出默认脱敏，CI 已覆盖 Windows 下的测试、编译和 CLI 帮助命令。阶段卡片进度条、左右方向键切换阶段，以及 database/engine/MainWindow 的一部分职责拆分已经落地。

仍然不能把它视作“干净可长期维护”的状态。最大问题不是单点 bug，而是几个核心区域仍然过大、状态和副作用混杂：`MainWindow`、`StepTablePanel`、`StepEditorPanel`、`WorkflowEngine` 仍超过 1000 行，且 UI 层仍直接写 DB 并调用引擎校验。残余垃圾方面，工作区存在 ignored 的缓存、构建目录、本地 DB、日志和导出文件；其中 `workflows_export.json` 当前包含钉钉 webhook token，虽然未被 Git 跟踪，但位于 OneDrive 同步路径，属于真实敏感残留。

发布卫生是另一个优先级较高的问题：`.gitignore` 已忽略 `dist/`，但 `dist/工作流管理_4.0.0*.exe` 仍被 Git 跟踪，且 CI 未验证 PyInstaller 打包。建议先处理敏感残留、Git 索引中的二进制产物、发布验证，再继续拆 UI/Engine/DB 的大类和长函数。

### Score Dashboard

```
Security        ████████░░  8.0  A   普通导出默认脱敏已修复，但本地导出文件和自动备份仍可能保留 Webhook token。
Stability       ███████░░░  7.2  A   测试通过且执行器超时/取消有覆盖，但核心运行收尾和 UI 状态更新仍有大量 broad catch。
Performance     ███████░░░  7.4  A   桌面场景下未发现直接热路径灾难，但大 UI 渲染和 COM/DB 同步调用仍限制规模。
Testing         ████████░░  7.6  A   117 个测试提供了真实回归保护，但 MainWindow/StepTablePanel 真实 GUI 工作流仍缺端到端覆盖。
Maintainability ██████░░░░  5.8  B   拆分有进展，但 4 个核心类仍是千行级维护热点，职责边界还不稳定。
Design          ██████░░░░  6.2  B   新 helper 模块方向正确，但 UI、DB、Engine 之间仍有分层违规和 stringly typed 状态。
Release         ██████░░░░  5.8  B   CI 已存在，但 tracked EXE、残余构建产物、spec 重复和无锁依赖降低发布可信度。
─────────────────────────────────────
Overall         ███████░░░  6.9  B
```

Each dimension scored 0.0–10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 9 | 9 | 0 |
| Low | 6 | 5 | 1 |
| Info | 0 | 0 | 0 |
| **Total** | **15** | **14** | **1** |

## 2. Project Map

项目是 Windows 桌面工作流管理应用，主要入口包括 `src/main.py` GUI、`src/cli.py` CLI，以及 `_import_and_run.py` 批量导入/运行脚本。GUI 基于 PySide6，主窗口聚合工作流列表、配置、步骤表格、步骤编辑器、工作台阶段看板、DAG、运行历史、日志和 Webhook 管理。

核心执行流由 `src/engine.py` 的 `WorkflowEngine` 驱动，部分调度、阶段预览、日志清理、选择策略、强制停止逻辑已拆到 `src/engine_core/`。持久化层是 SQLite + SQLAlchemy，主入口仍是 `src/database.py`，并已拆出导入导出、克隆、备份、字段白名单和版本快照模块。外部接口包括本地文件系统、SQLite DB、Windows COM 自动化、Power BI Desktop、Python 子进程、钉钉 webhook、JSON 导入导出和 CLI。

状态所有权仍偏集中：`MainWindow` 拥有大量 UI 状态和运行状态，`StepTablePanel` 同时管理阶段展示、拖拽、DB 写入和执行计划校验，`WorkflowEngine` 同时处理运行生命周期、线程、取消、日志、信号、通知和步骤执行。安全边界主要集中在本机配置/数据库/JSON 导出文件和钉钉 webhook token，项目本身没有网络服务端认证面。

测试结构包括 engine scheduling、执行器策略、schema guards、CLI contracts、UI helper、watch 规则、workbench board 等。CI 使用 Windows runner，执行依赖安装、`compileall`、`pytest -q` 和 CLI smoke；尚未覆盖 PyInstaller 打包、artifact 校验、版本锁定或发布回滚。

## 3. Top Risks

| Rank | Finding | Severity | Summary |
|------|---------|----------|---------|
| 1 | 本地导出文件残留 Webhook token | Medium | `workflows_export.json` 位于 OneDrive 工作区且包含钉钉 `access_token`，虽然 ignored 但仍可能被同步或误共享。 |
| 2 | `dist/` 下 EXE 被 Git 跟踪 | Medium | `.gitignore` 忽略 `dist/`，但两个 4.0.0 EXE 已在索引中，发布产物和源码边界混乱。 |
| 3 | UI mega-class 仍是主要维护风险 | Medium | `MainWindow`、`StepTablePanel`、`StepEditorPanel` 都超过 1000 行，职责仍未充分拆开。 |
| 4 | Engine 核心运行路径仍过长 | Medium | `_run`、`_execute_steps`、`_execute_single_step` 仍集中生命周期、调度、日志和错误处理。 |
| 5 | UI 层直接写库并调用引擎校验 | Medium | `StepTablePanel` 在组件内部执行阶段/排序写库，并直接调用 `WorkflowEngine.compute_batches`。 |
| 6 | broad catch / empty pass 仍大量存在 | Medium | AST 粗扫发现 `src` 下 186 个 broad catch、80 个 empty catch，UI 状态失败容易被吞掉。 |
| 7 | 自动备份默认保留 secrets | Medium | `auto_backup_workflows(... include_secrets=True)` 对本机恢复友好，但同步盘/共享目录风险较高。 |
| 8 | CI 未验证打包且 spec 重复 | Medium | CI 只覆盖测试/编译/CLI smoke，三份 PyInstaller spec 重复 hiddenimports/excludes。 |
| 9 | GUI 真实工作流缺端到端覆盖 | Medium | 当前 UI 测试主要覆盖 helper 和局部面板，MainWindow/StepTablePanel 的真实交互链路仍可能漏测。 |

## 4. Detailed Findings

### Finding: 本地导出文件残留 Webhook token

- Severity: Medium
- Confidence: High
- Category: Security / Release
- Status: Confirmed
- Affected area: Local workspace / JSON export
- Evidence:
  - File: `workflows_export.json:6`
  - File: `.gitignore:65`, `.gitignore:76`
  - Function / Module: local export artifact
  - Relevant behavior: `workflows_export.json` 未被 Git 跟踪但仍存在于仓库根目录，内容包含 `webhook_url` 和钉钉 `access_token`；报告中已脱敏，不展开真实值。
- Problem: 该文件是 ignored 的本地残留，不会进入 Git 提交，但当前工作区位于 OneDrive 路径，仍可能被云同步、误发压缩包或被其他工具采集。
- Why it matters: Webhook token 不是源码 secret，但它是可用凭据；一旦共享给无关人员，可触发钉钉机器人消息发送。
- Realistic failure scenario: 用户把项目目录整体打包给别人排查问题，或 OneDrive 同步目录被共享，`workflows_export.json` 中的 token 随文件泄露。
- Minimal fix: 删除或重新生成脱敏版 `workflows_export.json`；在清理前先确认是否仍需本机恢复用途。
- Better long-term fix: 所有含 secrets 的导出统一放到明确的 `data/backups/` 或用户配置目录，并在文件名或 metadata 标记 `secrets_included=true`；CLI 对当前目录 secret export 增加显式警告。
- Regression test suggestion: 增加仓库卫生脚本，扫描根目录 JSON 中的 `access_token=`、`webhook_url` 等敏感模式，CI 对 tracked 和 untracked release staging 目录都可运行。
- Estimated effort: 30-60 分钟。

### Finding: `dist/` 下二进制发布产物被 Git 跟踪

- Severity: Medium
- Confidence: High
- Category: Release / Maintainability
- Status: Confirmed
- Affected area: Git repository / release artifacts
- Evidence:
  - File: `.gitignore:7`, `.gitignore:9`
  - File: `dist/工作流管理_4.0.0.exe`
  - File: `dist/工作流管理_4.0.0_slim2.exe`
  - Function / Module: repository artifact hygiene
  - Relevant behavior: `.gitignore` 忽略 `build/` 和 `dist/`，但 `git ls-files -s dist` 显示两个 EXE 已被 Git 跟踪；当前文件大小约 66 MB 和 50 MB。
- Problem: 源码仓库同时包含忽略规则和已跟踪二进制，说明历史索引没有清理，发布产物可能陈旧且无法从当前源码可复现。
- Why it matters: 仓库膨胀、差异审查困难、杀毒/供应链扫描噪声增加，并且用户可能误用旧 EXE 当作最新构建。
- Realistic failure scenario: 修复源码后没有重新打包，但仓库里仍有旧 EXE；使用者从 `dist/` 直接运行，得到未修复版本。
- Minimal fix: 经确认后使用 `git rm --cached dist/*.exe` 从索引移除，并保留 `.gitignore`。
- Better long-term fix: 使用 GitHub Release 或 CI artifacts 发布 EXE，附带版本号、commit SHA、hash 和打包日志。
- Regression test suggestion: 增加 CI 检查 `git ls-files dist build data *.exe`，发现 tracked build artifact 直接失败。
- Estimated effort: 30 分钟；如需迁移 release 流程，0.5-1 天。

### Finding: 工作区存在残余构建、缓存、DB 和日志垃圾

- Severity: Low
- Confidence: High
- Category: Release / Code consistency
- Status: Confirmed
- Affected area: Local workspace hygiene
- Evidence:
  - File: `.gitignore:2`, `.gitignore:7`, `.gitignore:9`, `.gitignore:41`, `.gitignore:63`, `.gitignore:67`
  - File: `data/workflows.db`, `data/workflows.db-shm`, `data/workflows.db-wal`, `data/workflow.db`
  - Function / Module: workspace cleanup
  - Relevant behavior: 当前存在 `__pycache__/`、`.pytest_cache/`、`build/`、`dist/`、`data/*.db`、`logs/`、`image/` 和 `workflows_export.json`；多数已被 ignore。
- Problem: 大部分残留不会进入 Git，但它们会污染交接包、误导审计、增加本地搜索噪声；DB/WAL/日志还可能携带业务数据。
- Why it matters: 发布前如果直接打包项目目录，会混入本地运行状态和历史产物。
- Realistic failure scenario: 用户将整个目录复制到新机器，旧 DB 和日志导致新环境出现旧工作流、旧 schema cache 或旧 token。
- Minimal fix: 增加显式清理脚本或 release checklist，删除缓存、build、local DB、logs、local export。
- Better long-term fix: 将运行数据全部迁到用户数据目录，源码目录只保留源码、测试、docs 和 build spec。
- Regression test suggestion: 增加 `repo-hygiene` 检查，列出 ignored 但敏感/大体积的目录；release 前人工确认清理。
- Estimated effort: 1-2 小时。

### Finding: UI mega-class 仍是主要维护风险

- Severity: Medium
- Confidence: High
- Category: Maintainability / Frontend-state
- Status: Confirmed
- Affected area: PySide6 UI layer
- Evidence:
  - File: `src/ui/main_window.py:58-2073`
  - File: `src/ui/step_table/panel.py:51-1824`
  - File: `src/ui/step_editor.py:48-1423`
  - Function / Module: `MainWindow`, `StepTablePanel`, `StepEditorPanel`
  - Relevant behavior: AST 统计显示 `MainWindow` 2016 行、`StepTablePanel` 1774 行、`StepEditorPanel` 1376 行；`StepEditorPanel._setup_ui` 484 行，`MainWindow._setup_ui` 313 行，`MainWindow._apply_theme` 261 行。
- Problem: 这些类同时处理布局、主题、状态、事件、DB 交互和业务分发，明显违反 SRP 1.1、文件大小 1.2、函数长度 1.3。
- Why it matters: 新功能容易改到错误区域，局部测试难以隔离，UI 状态 bug 的修复成本会随代码量非线性上升。
- Realistic failure scenario: 修改阶段选择样式时触发运行状态锁定、保存/删除按钮或步骤详情刷新逻辑回归，因为这些逻辑都在同一个大类内交织。
- Minimal fix: 按现有拆分方向继续提取纯函数和小 service，例如主题应用、toolbar/actions、stage mutation、editor field state。
- Better long-term fix: 将 MainWindow 降为 composition root；面板只发意图信号，状态转换和持久化通过应用服务完成。
- Regression test suggestion: 对每次拆分增加 helper-level 行为测试，并保留 GUI smoke 测试覆盖主窗口启动、选择工作流、选择阶段、编辑保存、运行/停止。
- Estimated effort: 3-6 天分阶段完成。

### Finding: Engine 核心运行路径仍然过长且职责集中

- Severity: Medium
- Confidence: High
- Category: Stability / Maintainability
- Status: Confirmed
- Affected area: Workflow execution engine
- Evidence:
  - File: `src/engine.py:522-746`
  - File: `src/engine.py:837-983`
  - File: `src/engine.py:1084-1271`
  - Function / Module: `WorkflowEngine._run`, `_execute_steps`, `_execute_single_step`
  - Relevant behavior: `_run` 225 行，`_execute_steps` 147 行，`_execute_single_step` 188 行；生命周期、线程、取消、日志、DB、通知、信号都混在主类方法内。
- Problem: 虽然 `engine_core` 已拆出部分 helper，但关键运行路径仍难以审查和局部验证。
- Why it matters: 取消、失败收尾、嵌套子工作流和并行执行互相影响，长函数让状态一致性 bug 难以及时发现。
- Realistic failure scenario: 某个步骤执行失败后触发取消、通知和 run_history finalize，某个 broad catch 吞掉异常，UI 解锁但 DB 状态仍为 running。
- Minimal fix: 继续把 `_run` 拆成 begin/select/execute/finalize/emit_notification 五个小步骤，并让 finalize 返回结构化结果。
- Better long-term fix: 引入 RunCoordinator 或 RunLifecycleService，`WorkflowEngine` 只负责 Qt 信号适配和执行入口。
- Regression test suggestion: 增加 finalize 失败、通知提交失败、外部 cancel、nested run cancel 的组合测试，断言 DB 状态和信号顺序。
- Estimated effort: 2-4 天。

### Finding: `StepTablePanel` 在 UI 层直接写库并调用引擎校验

- Severity: Medium
- Confidence: High
- Category: Maintainability / Architecture
- Status: Confirmed
- Affected area: Step table / stage ordering
- Evidence:
  - File: `src/ui/step_table/panel.py:1545-1584`
  - File: `src/ui/step_table/panel.py:1595-1640`
  - Function / Module: `StepTablePanel._apply_orders_and_stage_updates`, `_move_stage_order`
  - Relevant behavior: UI 组件内部打开 DB session、修改 `Step.order` 和 `stage_uid`、查询 stages、调用 `WorkflowEngine.compute_batches` 校验，然后 commit。
- Problem: UI 层持有持久化和业务校验细节，违反 layered architecture 7.1 和 business logic independence 7.2。
- Why it matters: 同一阶段排序/拖拽规则未来需要 CLI 或其他 UI 复用时必须复制逻辑；DB 事务失败也更难在 UI 之外测试。
- Realistic failure scenario: CLI 增加“移动阶段/步骤”命令时重新实现一套排序规则，和 UI 版本在依赖校验或回滚行为上不一致。
- Minimal fix: 提取 `stage_mutation_service.apply_step_order_and_stage_updates()`，UI 只传入意图并展示结果。
- Better long-term fix: 将阶段/步骤变更定义为命令对象，统一由 service 做校验、事务和事件返回。
- Regression test suggestion: 使用临时 SQLite DB 测试跨阶段拖拽、删除阶段迁移、阶段上移/下移、非法依赖回滚。
- Estimated effort: 1-2 天。

### Finding: broad catch 和 empty pass 仍可能掩盖 UI 状态失败

- Severity: Medium
- Confidence: High
- Category: Stability / Fallback
- Status: Confirmed
- Affected area: UI state, engine finalize, database cleanup
- Evidence:
  - File: `src/ui/step_editor.py:688-738`
  - File: `src/ui/step_editor.py:892-907`
  - File: `src/engine.py:667-731`
  - File: `src/database.py:116-147`, `src/database.py:478-490`
  - Function / Module: fallback/error handling
  - Relevant behavior: AST 粗扫显示 `src` 下 186 个 broad catch、80 个 empty catch；例如控件状态设置异常直接 `pass`，依赖预览刷新失败直接 `return`。
- Problem: 一些 fallback 是合理的 UI 容错或 cleanup best effort，但大量 broad catch/empty pass 让真实错误不可见。
- Why it matters: 用户看到的是按钮状态、依赖预览或运行状态异常，而日志中可能没有足够上下文定位根因。
- Realistic failure scenario: 某个控件未初始化导致编辑锁定失败，被 `pass` 吞掉；用户在不可预期状态下保存步骤，引发后续配置漂移。
- Minimal fix: 对 UI best-effort 操作统一使用 `safe_ui_call(label, fn)`，至少记录 debug/warning；对依赖预览失败显示非阻塞错误状态。
- Better long-term fix: 定义错误处理策略：哪些路径 fail-fast，哪些路径 keep-with-alert，哪些 cleanup 可忽略，并用 helper 强制一致。
- Regression test suggestion: 注入控件异常，断言日志记录和 UI fallback 提示；对依赖预览 DB 异常断言不会静默失败。
- Estimated effort: 1-3 天，取决于清理范围。

### Finding: 自动备份默认保留 Webhook secrets

- Severity: Medium
- Confidence: High
- Category: Security / Configuration
- Status: Confirmed
- Affected area: Backup/export
- Evidence:
  - File: `src/database.py:1472-1489`
  - File: `src/cli.py:694-803`
  - File: `README.md:91-110`
  - Function / Module: `auto_backup_workflows`, `cmd_backup`
  - Relevant behavior: 普通 `export` 默认脱敏，但 `backup` 默认 `include_secrets=True`，CLI 需要 `--without-secrets` 才移除完整 Webhook URL。
- Problem: 这个设计有本机恢复价值，但默认含 secrets 对同步盘、共享盘和误打包场景风险更高。
- Why it matters: 备份通常比手动导出更容易被长期保留或同步，泄露窗口更长。
- Realistic failure scenario: 用户把备份目录放在 OneDrive/共享盘，历史备份长期保留完整钉钉 token。
- Minimal fix: CLI 执行 `backup` 时输出明显提示，包含目标路径和 `secrets_included=True`；对非默认目录要求显式 `--include-secrets`。
- Better long-term fix: 默认不含 secrets；提供 `backup --include-secrets --encrypt` 或至少把 secrets backup 存到用户本机私有目录。
- Regression test suggestion: CLI contract 测试覆盖默认 backup 提示、`--without-secrets` 行为和非默认目录下 include secrets 的确认规则。
- Estimated effort: 0.5-1 天。

### Finding: Webhook URL 校验只验证任意 HTTPS URL

- Severity: Low
- Confidence: High
- Category: Security / Configuration
- Status: Confirmed
- Affected area: Webhook manager
- Evidence:
  - File: `src/ui/webhook_manager.py:323-331`
  - Function / Module: `WebhookManagerDialog._validate_webhook_url`
  - Relevant behavior: 校验逻辑只要求 `url.startswith("https://")` 且 `urlparse(url)` 有 scheme/netloc。
- Problem: 当前 UI 可接受任何 HTTPS URL，而不是钉钉机器人 endpoint 或至少带 `access_token` 的预期格式。
- Why it matters: 对本地桌面工具不是远程漏洞，但会导致误配、发送失败，或把通知发到非预期 endpoint。
- Realistic failure scenario: 用户粘贴公司内部 HTTPS URL，保存成功；运行后通知请求把工作流状态发送到错误服务。
- Minimal fix: 校验 host/path/query，例如 `oapi.dingtalk.com/robot/send` 且存在 `access_token`；非标准 endpoint 要用户确认。
- Better long-term fix: 将 webhook provider 抽象为 DingTalk provider，未来扩展企业微信/飞书时各自定义校验。
- Regression test suggestion: 增加 `_validate_webhook_url` 单测：合法钉钉 URL 通过，普通 HTTPS URL、缺 token、HTTP URL 拒绝或要求确认。
- Estimated effort: 1-2 小时。

### Finding: 通知失败时会丢失 HTTP 状态和非 JSON 响应上下文

- Severity: Low
- Confidence: High
- Category: Stability / Observability
- Status: Confirmed
- Affected area: DingTalk notifier
- Evidence:
  - File: `src/notifier.py:148-167`
  - Function / Module: `send_dingtalk_message`
  - Relevant behavior: `requests.post` 设置了 timeout，但直接 `response.json()`；非 JSON 响应进入 generic exception，返回 `未知错误`。
- Problem: 发送失败时缺少 status code、响应正文摘要和 endpoint provider 语义，排查配置问题成本高。
- Why it matters: 通知不是主执行路径，但运行失败通知本身失败时，用户最需要诊断信息。
- Realistic failure scenario: 钉钉返回 HTML/网关错误页或 403，用户只看到“未知错误”，无法区分 token 错误、网络代理还是服务端异常。
- Minimal fix: 先检查 `response.status_code`，捕获 `ValueError`，返回 `HTTP <code>` 和截断后的响应文本。
- Better long-term fix: 定义 `NotificationResult`，包含 `ok/status_code/provider_code/message/raw_excerpt`，UI 和日志统一展示。
- Regression test suggestion: mock `requests.post` 返回非 JSON、403 JSON、200 errcode 非 0，断言错误信息保留状态码和摘要。
- Estimated effort: 1-2 小时。

### Finding: CI 未验证打包产物，PyInstaller spec 重复维护

- Severity: Medium
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: CI / packaging
- Evidence:
  - File: `.github/workflows/ci.yml:29-43`
  - File: `build.spec:20-48`
  - File: `build_slim.spec:38-98`
  - File: `build_slim2.spec:38-98`
  - Function / Module: release build process
  - Relevant behavior: CI 覆盖 compileall、pytest、CLI smoke；三份 spec 重复 hiddenimports/excludes，未做 PyInstaller smoke build 或 artifact hash。
- Problem: 测试通过不等于 EXE 可用，尤其 PySide6、pywin32、pywinauto、Power BI/Excel 自动化依赖打包时容易缺 hidden import 或资源。
- Why it matters: 发布失败通常发生在源码测试之后、用户机器运行之前；当前流程不能提前发现。
- Realistic failure scenario: 依赖升级后测试仍过，但 EXE 启动缺 PySide6 plugin 或 COM 模块，用户下载后才发现。
- Minimal fix: 增加手动触发或 tag 触发的 packaging CI，至少构建 slim2 并运行 `--help`/启动 smoke。
- Better long-term fix: 合并 spec 公共规则到 `src/build_slim_rules.py` 或生成脚本，CI 输出 hash、artifact、版本 metadata。
- Regression test suggestion: CI job 执行 PyInstaller 构建 smoke，并验证生成 EXE 存在、版本号和 CLI/GUI 最小启动。
- Estimated effort: 0.5-2 天。

### Finding: 依赖未锁定版本，发布可复现性不足

- Severity: Low
- Confidence: High
- Category: Dependency-weight / Release
- Status: Confirmed
- Affected area: Python dependency management
- Evidence:
  - File: `requirements.txt:4`, `requirements.txt:7`, `requirements.txt:10`, `requirements.txt:13`, `requirements.txt:16`, `requirements.txt:19`, `requirements.txt:22`
  - Function / Module: dependency manifest
  - Relevant behavior: 依赖使用 `>=` 范围，包括 PySide6、SQLAlchemy、pywin32、pywinauto、watchdog、psutil、requests。
- Problem: 对开发安装友好，但发布构建不具备完全可复现性；上游 minor/major 行为变化可能影响 EXE。
- Why it matters: 桌面应用打包依赖二进制 wheel 和 Qt plugin，版本漂移更容易导致运行时问题。
- Realistic failure scenario: CI 或新机器安装到更新的 PySide6/SQLAlchemy，测试可能过，但 PyInstaller 打包资源路径变化。
- Minimal fix: 增加 `requirements.lock.txt` 或 constraints 文件用于 release build。
- Better long-term fix: 使用 pip-tools/uv 生成锁文件和 hash，开发依赖与运行依赖分离。
- Regression test suggestion: CI release job 使用 lock 文件安装，并输出 `pip freeze` artifact。
- Estimated effort: 2-4 小时。

### Finding: 拆分后仍有未使用导入和 stale compatibility imports

- Severity: Low
- Confidence: Medium
- Category: Code consistency / Maintainability
- Status: Confirmed
- Affected area: Engine / CLI / database / executors
- Evidence:
  - File: `src/engine.py:18-23`, `src/engine.py:62-79`
  - File: `src/cli.py:24-28`, `src/cli.py:53-63`
  - File: `src/database.py:4-12`
  - File: `src/executors/powerbi_executor.py:4-12`
  - Function / Module: import organization
  - Relevant behavior: AST 粗扫显示 `engine.py` 中 `as_completed`、`field`、`Callable`、`Any`、`StepLog`、`send_workflow_notification`、`get_webhook_by_id` 等未引用；`database.py` 的 `os`、`cli.py` 的 `os/signal` 和部分数据库导入、`powerbi_executor.py` 的 `time` 也疑似未使用。
- Problem: 这是低风险问题，但它反映拆分后清理不完整，增加阅读噪声。
- Why it matters: 未使用导入会让读者误判模块依赖，长期会掩盖真实循环依赖或 stale feature。
- Realistic failure scenario: 继续拆 Engine 时误以为 notifier/database webhook 仍由 `engine.py` 直接使用，导致重复迁移或错误依赖保留。
- Minimal fix: 使用 ruff/pyflakes 或 IDE 检查移除未使用导入。
- Better long-term fix: CI 增加轻量 lint，仅启用 unused-import、undefined-name、syntax 类规则，不一次性引入过宽格式约束。
- Regression test suggestion: 增加 `ruff check --select F401,F821` 或等价脚本。
- Estimated effort: 1-2 小时。

### Finding: GUI 真实工作流缺端到端覆盖

- Severity: Medium
- Confidence: High
- Category: Testing / Testing-authenticity
- Status: Confirmed
- Affected area: GUI workflows
- Evidence:
  - File: `tests/test_workbench_board.py:77-125`
  - File: `tests/test_watch_ui.py:118-213`
  - File: `tests/test_executor_policies.py`
  - Function / Module: UI tests
  - Relevant behavior: 现有测试对阶段进度、左右键切换、关闭确认、执行器策略等有价值；但大量测试使用 `monkeypatch`、`SimpleNamespace`、fake COM/engine/database，对真实 MainWindow/StepTablePanel/StepEditorPanel 的整链路覆盖有限。
- Problem: helper 测试能保护纯逻辑，但无法完全覆盖 PySide 信号连接、焦点、表格选中、DB 事务、运行按钮锁定之间的组合问题。
- Why it matters: 当前最大维护风险正好在 GUI 大状态组件，测试重心还没有完全跟上风险分布。
- Realistic failure scenario: 左右键切阶段单测通过，但真实 MainWindow 中焦点在表格或输入框时事件被不同控件消费，运行控制面板未同步选中阶段。
- Minimal fix: 增加少量 high-value GUI integration smoke：启动 MainWindow、创建临时 DB、选择工作流、选择阶段、左右键切换、添加步骤、保存、运行 dry-run。
- Better long-term fix: 建立 PySide GUI 测试夹具，区分 pure helper、panel integration、main-window smoke 三层。
- Regression test suggestion: 使用临时 SQLite + offscreen Qt，测试从工作流选择到阶段选择和步骤保存的真实信号链。
- Estimated effort: 1-3 天。

### Finding: 历史交接/审计文档散落根目录，单一事实源不够清晰

- Severity: Low
- Confidence: Medium
- Category: Documentation / Code consistency
- Status: Suspected
- Affected area: Repository documentation
- Evidence:
  - File: `HANDOVER.md:1`
  - File: `HANDOVER_AI_SWITCH_2026-02-13.md:1`
  - File: `V7_iOS_Minimal_Handover.md:1`
  - File: `05_整体Review与改进建议.md:1`
  - File: `docs/REVIEW_2026-05-15.md:1`
  - Function / Module: documentation structure
  - Relevant behavior: 根目录和 `docs/` 同时存在多份历史 handover/review 文档。
- Problem: 这些文档可能有保留价值，但缺少“当前有效/历史归档”的边界，容易让后续维护者参考旧方案。
- Why it matters: 大规模重构后，过期交接文档会造成错误决策，尤其是结构图和运行流程描述。
- Realistic failure scenario: 新维护者阅读旧 handover，认为某些模块尚未拆分或某些安全问题仍未修复，导致重复工作或错误修复。
- Minimal fix: 在 README 或 docs index 中标记当前事实源，并将历史文档归档到 `docs/archive/`。
- Better long-term fix: 只保留一个当前架构文档和一个 changelog/release note，历史报告按日期归档。
- Regression test suggestion: 增加 docs hygiene checklist，根目录只允许 README、AGENTS、CHANGELOG、当前报告等白名单文档。
- Estimated effort: 1-2 小时。

## 5. Security Concerns

主要安全风险集中在本机 secret 生命周期，而不是远程攻击面。普通导出默认脱敏是正确修复，但根目录残留的 `workflows_export.json` 和自动备份默认保留 secrets 仍需要处理。Webhook URL 校验目前只保证是 HTTPS，不保证是钉钉机器人 endpoint。

Relevant findings: 本地导出文件残留 Webhook token；自动备份默认保留 Webhook secrets；Webhook URL 校验只验证任意 HTTPS URL。

## 6. Stability Concerns

稳定性整体比旧状态好：执行器超时、取消、子工作流取消、DB schema guard 和 run finalize 都有测试。剩余风险在于核心运行路径仍长，且 broad catch/empty pass 会降低故障可见性。

Relevant findings: Engine 核心运行路径仍然过长；broad catch 和 empty pass 仍可能掩盖 UI 状态失败；通知失败时会丢失 HTTP 状态和非 JSON 响应上下文。

## 7. Performance Concerns

未发现桌面规模下的明显灾难性性能问题。已有改进包括 schema cache、批量取消 pending step logs、最近日志查询避免 N+1、CLI 查询命令不强制启动 QApplication。后续性能风险主要来自大 UI 组件渲染、同步 DB/COM 调用和 PyInstaller 打包体积。

Relevant findings: UI mega-class 仍是主要维护风险；CI 未验证打包产物；依赖未锁定版本。

## 8. Testing Gaps

当前 `117 passed` 是真实进步，不是纯绿灯幻觉。高价值测试包括 engine scheduling、schema guards、dependency manifest、engine_core selection/preview/force_stop/log_cleanup、database backup/version helper、CLI contracts 和 workbench board 阶段进度/键盘切换。主要缺口是 MainWindow/StepTablePanel/StepEditorPanel 的真实集成链路。

Relevant findings: GUI 真实工作流缺端到端覆盖；UI mega-class 仍是主要维护风险。

## 9. Maintainability Concerns

维护性是最低分维度。新增模块让 database、engine 和 MainWindow 有了拆分方向，但旧核心类仍承担过多职责，UI 层仍拥有业务事务，导入噪声显示拆分后收尾不足。

Relevant findings: UI mega-class 仍是主要维护风险；Engine 核心运行路径仍然过长；`StepTablePanel` 在 UI 层直接写库并调用引擎校验；拆分后仍有未使用导入。

## 10. Design / Principles Concerns

最明显的原则问题是 SRP、文件大小、函数长度、分层边界和 fail-fast 一致性。项目也有明显改善：字段白名单、导出脱敏、engine_core helper、database helper 和 CI 说明设计方向已经变好。

Relevant findings: UI mega-class 仍是主要维护风险；`StepTablePanel` 在 UI 层直接写库并调用引擎校验；broad catch 和 empty pass 仍可能掩盖 UI 状态失败。

## 11. Release Concerns

发布前必须处理 Git 索引中的 EXE、ignored 但敏感的本地导出文件、残余构建/DB/日志，以及未覆盖打包验证的问题。当前 CI 对源码正确性有帮助，但不能证明 EXE 可发布。

Relevant findings: `dist/` 下二进制发布产物被 Git 跟踪；工作区存在残余构建、缓存、DB 和日志垃圾；CI 未验证打包产物；依赖未锁定版本。

## 12. Documentation Accuracy

README 已同步新增模块和 Webhook 脱敏/备份行为，这是正向变化。风险在于根目录历史 handover/review 文档较多，缺少当前事实源和归档边界。

Relevant findings: 历史交接/审计文档散落根目录，单一事实源不够清晰。

## 13. Configuration Safety

配置层已增加错误处理测试，`test_config_errors.py` 覆盖 invalid JSON 和目录创建失败。风险仍在 secret-bearing backup 默认行为和 Webhook URL 校验过宽。

Relevant findings: 自动备份默认保留 Webhook secrets；Webhook URL 校验只验证任意 HTTPS URL。

## 14. Observability

运行日志和错误诊断模块存在，Engine 收尾失败也会记录警告。缺口是通知失败上下文、UI fallback 日志和一些 cleanup path 的错误可见性。

Relevant findings: broad catch 和 empty pass 仍可能掩盖 UI 状态失败；通知失败时会丢失 HTTP 状态和非 JSON 响应上下文。

---

## 15. Principles Compliance

整体遵循情况是“局部有纪律，核心仍沉重”。新增 helper 和字段白名单说明代码正在向更好的边界迁移，但 UI/Engine/DB 主入口仍承载过多历史职责。

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP 1.1) | 4 | Medium | `MainWindow`, `StepTablePanel`, `StepEditorPanel`, `WorkflowEngine` |
| File Size Limit (1.2) | 7 | Medium | `main_window.py`, `step_table/panel.py`, `database.py`, `step_editor.py`, `engine.py`, `workbench_board.py`, `cli.py` |
| Function/Method Size (1.3) | 10+ | Medium | `_setup_ui`, `_apply_theme`, `_run`, `_execute_single_step`, executor `execute` methods |
| Dependency Rule (7.1) | 1 | Medium | `StepTablePanel` 直接 DB + Engine |
| Business Logic Independence (7.2) | 2 | Medium | UI stage mutation, Engine DB lifecycle coupling |
| Don't Swallow Errors (6.1) | Many | Medium | UI fallback, cleanup paths |
| Don't Lose Error Context (6.2) | 2 | Low | notifier, UI fallback |
| Configuration Safety (9.1/9.2) | 2 | Medium | backup secrets, webhook URL validation |

### Principles Respected

- 字段更新白名单已存在，`update_step/update_webhook` 会拒绝未知字段。
- JSON 普通导出默认脱敏，并有测试覆盖 masked webhook import/export。
- `engine_core` 和 `database_*` helper 拆分方向正确，降低了部分纯逻辑测试成本。
- CI 已覆盖 Windows 测试、编译和 CLI smoke。
- 执行器取消、超时和进程树清理有专门测试。

---

## 15a. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| BroadCatch | 186 | 120 | 45 | 21 |
| EmptyCatch | 80 | 50 | 20 | 10 |
| SilentFallback | 78 | 45 | 25 | 8 |
| CompatibilityBranch | 3 | 3 | 0 | 0 |
| SilentCorrection | 2 | 2 | 0 | 0 |
| DefensiveGuess | 6 | 4 | 2 | 0 |

上表中 `BroadCatch`、`EmptyCatch` 和 `SilentFallback` 的前两项来自 AST 粗扫；KeepWithAlert/FailFast/Remove 是审计分类建议，不是机械结论。清理时优先处理 UI 状态、DB 写入、Engine finalize 和用户可见失败路径；COM cleanup、process kill cleanup 可以保留 best-effort，但应增加上下文日志。

## 15b. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|-----------------|------|--------|
| `tests/test_engine_scheduling.py` | High | 调度纯逻辑回归 | Keep |
| `tests/test_schema_guards.py` | High | JSON 导入导出、字段白名单、迁移失败 | Keep |
| `tests/test_executor_policies.py` | Medium | fake COM/进程可覆盖策略，不覆盖真实 Office/Power BI | Keep with smoke |
| `tests/test_workbench_board.py` | Medium | 覆盖阶段进度和左右键，但不覆盖 MainWindow 焦点链 | Extend |
| `tests/test_watch_ui.py` | Medium | 覆盖关闭/未保存行为，但依赖 monkeypatch | Keep |
| MainWindow full workflow | Low | 信号连接、焦点、DB、运行状态组合 bug 会逃逸 | Add integration |
| PyInstaller EXE | None | 打包缺模块/插件无法提前发现 | Add release smoke |

### Valuable Tests

`test_schema_guards.py`、`test_database_helpers.py`、`test_database_versions.py`、`test_engine_core_selection.py`、`test_engine_core_stage_preview.py`、`test_engine_core_force_stop.py`、`test_engine_core_log_cleanup.py`、`test_cli_contract*.py` 和 `test_workbench_board.py` 对当前改动有真实保护价值。

### Suspicious Tests

没有发现“为了通过而伪造成功”的测试，但 GUI 与执行器测试大量使用 fake objects，这是 PySide/COM 场景下合理的折中。风险不是测试无效，而是测试层级缺少真实 integration smoke。

### Missing Tests

缺少 MainWindow 真实启动后从选择工作流到选择阶段、添加/编辑步骤、保存、dry-run/运行锁定、停止/关闭的端到端测试；缺少 release EXE smoke；缺少 repo hygiene/secret scan。

---

## 15c. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 0 | 0 | 0 | 0 | 0 |
| InputBoundary | 3 | 0 | 0 | 1 | 2 |
| OutputLeak | 1 | 0 | 0 | 1 | 0 |
| BooleanTrap | 1 | 0 | 0 | 0 | 1 |
| StringlyTyped | 3 | 0 | 0 | 2 | 1 |
| ErrorType | 2 | 0 | 0 | 0 | 2 |

Python 动态类型本身不是问题；当前风险主要来自状态字符串、JSON dict、`notify_config`、`stage_uid` 和 backup/export 的 boolean flag。建议对运行状态、导出 secret 策略、通知结果逐步引入 dataclass/Enum。

## 15d. Frontend State Analysis

### Summary

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 4 | `MainWindow`, `StepTablePanel`, `StepEditorPanel`, `WorkbenchBoardPanel` |
| StateDuplication | 3 | selected step/stage, run lock, table/board status |
| PropDrilling | 1 | MainWindow 到多个 panel 的状态分发 |
| EffectChain | 3 | load workflow surfaces, run events, editor dependency preview |
| UIBusinessCoupling | 2 | StepTablePanel DB writes, MainWindow direct database imports |
| DOMasState | 1 | table row metadata mirrors step/stage state |
| RequestState | 1 | run/stop lifecycle UI lock |
| RenderPerf | 1 | large table/board refresh and theme repaint |

优先处理 `StepTablePanel` 的 stage mutation service 和 `MainWindow` 的 action/state 拆分。不要一次性重写 UI，继续按“纯 helper + 小服务 + integration test”的方式拆。

## 15e. Backend API Analysis

### Summary

| Subtype | Count | Affected Endpoints |
|---------|-------|-------------------|
| ApiConsistency | 1 | CLI commands / database function contracts |
| Validation | 2 | JSON import, webhook URL |
| Auth | 0 | 无网络后端 API |
| NplusOne | 0 | 已有日志查询优化 |
| Caching | 1 | schema cache fallback |
| ErrorResponse | 2 | CLI errors, notifier result |
| BusinessLogic | 1 | UI stage mutation |
| DataFlow | 1 | export/backup secret policy |

项目没有 HTTP 后端 API；本审计把 CLI、JSON import/export 和 database function 视为接口边界。最大问题是 UI 仍绕过 service 直接操作 database transaction。

## 15f. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| PySide6>=6.6.0 | Healthy but heavy | High | High | GUI | Keep; release lock |
| SQLAlchemy>=2.0.0 | Healthy | Medium | Medium | SQLite ORM | Keep; release lock |
| pywin32>=306 | Platform-specific | Medium | Medium | Excel COM | Keep; Windows-only note |
| pywinauto>=0.6.8 | Platform-specific | Medium | Medium | Power BI UI automation | Keep; smoke test |
| watchdog>=4.0.0 | Healthy | Low | Low | 文件监听 | Keep |
| psutil>=5.9.0 | Healthy | Low | Low | 进程树清理 | Keep |
| requests>=2.31.0 | Healthy | Low | Low | 钉钉通知 | Keep |

未发现明显未使用的 declared dependency。主要问题不是依赖过多，而是 release 未锁版本、打包验证不足。

---

## 16. Recommended Fix Order

### Fix Immediately

| Issue | Reason | Suggested action |
|-------|--------|------------------|
| 本地导出文件残留 Webhook token | 当前工作区真实存在 secret-bearing JSON | 删除或重新生成脱敏版；确认无需本机恢复后清理 |
| `dist/` 下 EXE 被 Git 跟踪 | 发布产物污染源码索引 | 经确认后 `git rm --cached dist/*.exe`，改用 release artifacts |

### Fix Before Stable Release

| Issue | Reason | Suggested action |
|-------|--------|------------------|
| 自动备份默认保留 secrets | 同步盘/共享盘风险 | 改默认或增加强提示/显式参数 |
| CI 未验证打包产物 | 测试通过不能证明 EXE 可用 | 增加 PyInstaller smoke 和 artifact hash |
| UI 层直接写库 | 分层违规影响稳定迭代 | 提取 stage mutation service |
| Engine 运行路径过长 | 取消/finalize/通知组合难审查 | 拆 RunLifecycle/RunCoordinator |
| GUI E2E 缺口 | 最大风险区域测试不足 | 增加 MainWindow integration smoke |

### Schedule Later

| Issue | Reason | Suggested action |
|-------|--------|------------------|
| UI mega-class | 结构债务，需持续拆分 | 分批提取 actions/state/theme/editor helpers |
| broad catch 清理 | 需要逐条判断 | 先加日志 helper，再分路径 fail-fast |
| 依赖未锁定 | 发布可复现性问题 | 增加 constraints/lock |
| 未使用导入 | 低风险重构残留 | 增加 ruff F401/F821 |
| 文档归档 | 维护效率问题 | 建 docs index/archive |

### Ignore for Now

| Issue | Reason |
|-------|--------|
| COM cleanup path 中的少量 best-effort `pass` | 清理失败本身低风险，可先加 debug 日志，不必强制 fail-fast |
| PySide6 依赖体积 | GUI 应用核心依赖，不建议为减体积替换框架 |

## 17. Quick Wins

| Quick win | Impact | Effort |
|-----------|--------|--------|
| 清理或脱敏 `workflows_export.json` | 立即降低 secret 残留风险 | 30 分钟 |
| 从 Git 索引移除 `dist/*.exe` | 改善发布卫生和仓库体积 | 30 分钟 |
| 增加 repo hygiene/secret scan | 防止残余垃圾和 token 回流 | 1-2 小时 |
| 给 notifier 增加 status code / non-JSON 错误上下文 | 提升通知故障可诊断性 | 1-2 小时 |
| Webhook URL 校验钉钉 host/path/token | 减少误配置 | 1-2 小时 |
| 移除未使用导入并加轻量 lint | 降低重构噪声 | 1-2 小时 |
| CLI backup 输出 secrets 提示 | 降低误备份风险 | 1 小时 |

## 18. Long-term Refactor Plan

1. Stage mutation service

   Motivation: `StepTablePanel` 目前同时负责 UI、DB transaction 和 execution plan validation。

   Approach: 提取 `stage_mutation_service`，提供 apply order、move stage、migrate stage steps、insert stage 四类命令；UI 只调用 service 并展示结果。

   Risk: 阶段排序和依赖校验非常容易引入回归。

   Testing strategy: 使用临时 SQLite DB 覆盖跨阶段拖拽、删除阶段迁移、非法依赖回滚、阶段上移/下移。

2. Run lifecycle service

   Motivation: `WorkflowEngine._run` 仍是运行一致性核心风险。

   Approach: 拆分 begin/select/execute/finalize/notify，finalize 返回结构化状态；Engine 保留 Qt signal adapter。

   Risk: 信号顺序、nested run 和 cancel 行为容易被破坏。

   Testing strategy: 增加 run lifecycle contract tests，覆盖成功、失败、取消、finalize DB failure、notification submit failure。

3. MainWindow composition root

   Motivation: `MainWindow` 仍承担太多状态协调。

   Approach: 将 toolbar/action wiring、run state、json actions、panel layout、selection sync 分批迁出；每批只改变一个职责边界。

   Risk: GUI 信号连接和焦点行为难以单元测试。

   Testing strategy: 每批拆分后运行 `pytest -q`，并增加 offscreen MainWindow smoke。

4. Release pipeline

   Motivation: 当前 CI 证明源码测试通过，但不证明 EXE 可发布。

   Approach: 用 release lock 安装依赖，执行 PyInstaller smoke，上传 artifact，输出 hash 和 commit SHA。

   Risk: CI 时间增加，Windows runner 依赖 Office/Power BI 的部分功能无法完全验证。

   Testing strategy: 先验证 EXE 启动/CLI help/GUI import smoke，Office/Power BI 保留手动验收清单。

5. Error handling policy

   Motivation: broad catch/empty pass 清理不能靠一次性 grep 修改。

   Approach: 定义 `FailFast`、`KeepWithAlert`、`BestEffortCleanup` 三类策略；UI 使用统一 safe call helper，DB/Engine 关键路径返回结构化错误。

   Risk: 过度 fail-fast 可能降低桌面容错体验。

   Testing strategy: 对每类策略各写失败注入测试，确保用户可见路径有日志或提示。

---

Audit verification performed:

- `pytest -q`: `117 passed in 10.45s`
- `python -m compileall src tests _import_and_run.py`: passed
- `python src\cli.py --help`: passed
- `python src\cli.py export --help`: passed
- `python _import_and_run.py --help`: passed

No cleanup or deletion was performed during this audit.
