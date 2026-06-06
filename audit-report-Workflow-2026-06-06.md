# Fuck My Shit Mountain Audit Report

**Project:** Workflow
**Audit mode:** full
**Date:** 2026-06-06
**Reviewer:** Codex / GPT-5

---

## 1. Executive Summary

本次审计基于当前工作区状态执行，包含未提交的重构、测试、CI、发布和仓库卫生改动。项目已经从早前的高风险状态明显改善：`pytest -q` 当前为 137 项通过，`compileall` 通过，`tools/repo_hygiene.py` 通过；Webhook 密钥默认脱敏、钉钉 URL 校验、阶段事务服务、阶段卡片进度条、左右键阶段切换、CI 和手动打包 workflow 都已经落地。

剩余主要问题不是“功能不可用”，而是结构债仍偏重。`MainWindow`、`WorkflowEngine`、`StepTablePanel`、`database.py` 和 `StepEditorPanel` 仍是超过 1000 行的核心模块；执行器 `execute()` 仍把路径验证、外部进程/COM/UI 自动化、取消/超时、日志和结果映射混在一起。这些问题会继续拉高后续改动成本，尤其是 Excel/PowerBI、数据库迁移、JSON 导入和 UI 状态联动这些边界。

没有发现新的 Critical/High 级问题。当前项目可进入更稳定的迭代阶段，但如果准备公开稳定发布，建议先处理中等风险中的数据保留、执行器清理语义、导入校验、打包后 smoke 和核心文件拆分。

### Score Dashboard

```
Security        ████████░░  8.2  A   Webhook 默认脱敏、URL 白名单和仓库密钥扫描已补齐；显式 include-secrets 仍要求使用者纪律。
Stability       ███████░░░  7.3  A   取消、超时和事务化阶段变更改善明显；Excel/PowerBI 清理兜底和数据库 session 生命周期仍是主要风险。
Performance     ███████░░░  7.2  A   调度批次和 UI 部分拆分已改善；大 UI 重建、长函数和外部自动化阻塞路径仍限制扩展性。
Testing         ████████░░  8.0  A   137 项测试覆盖 CLI、schema、调度、执行器策略和 UI；Excel/PowerBI 真实集成与打包产物 smoke 仍不足。
Maintainability ███████░░░  6.7  B   MainWindow/Engine/StepTable 已拆出 helper，但 5 个核心文件仍超过 1000 行且多个函数超过 100 行。
Design          ███████░░░  6.9  B   分层边界比前一阶段清晰；UI/engine/database 仍存在 composition root、业务逻辑和基础设施耦合。
Release         ████████░░  7.6  A   CI、package workflow、release constraints 和 hygiene gate 已有；缺少打包后 exe smoke、签名和回滚清单。
─────────────────────────────────────
Overall         ███████░░░  7.4  A
```

Each dimension scored 0.0–10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based. See `rubrics/scoring.md` for anchor descriptions.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 10 | 10 | 0 |
| Low | 3 | 3 | 0 |
| Info | 0 | 0 | 0 |
| **Total** | **13** | **13** | **0** |

## 2. Project Map

项目是一个 Windows 桌面工作流管理器，主入口包括 `src/main.py` 的 PySide6 GUI、`src/cli.py` 的命令行管理入口，以及 `_import_and_run.py` 的批量导入/运行脚本。GUI 通过 `MainWindow` 组合工作流列表、工作台看板、步骤表、步骤编辑器、运行控制、日志、DAG 和历史记录面板。

运行生命周期由 `WorkflowEngine` 驱动：选择步骤、计算执行批次、创建 run history、按阶段/依赖执行步骤、调用具体 executor、写入 step log/run history，并向 UI 发出 Qt signals。已拆出的 `engine_core/*` 覆盖 selection、batch、preview、lifecycle、watcher、force_stop、log_cleanup 等局部职责，但 `src/engine.py` 仍是核心 orchestration hub。

持久层基于 SQLite + SQLAlchemy ORM。`src/database.py` 负责初始化、迁移、会话管理和大量 CRUD；`database_import_export.py`、`database_backup.py`、`database_clone.py`、`database_versions.py`、`database_field_guards.py` 已拆出部分边界逻辑。当前数据库仍依赖 `scoped_session` 复用线程 session，并返回 ORM 对象给 UI/engine 调用方。

外部接口包括本地文件系统、Python 子进程、Excel COM、Power BI Desktop + pywinauto、watchdog 文件监听、钉钉机器人 Webhook、JSON 导入导出、GitHub Actions CI/package。安全边界主要集中在 Webhook secret、JSON 导入、脚本路径、子进程执行、数据库迁移和本地 artifact。

测试结构集中在 `tests/`，覆盖 schema guards、stage mutation transaction、engine scheduling、executor policies、CLI contracts、UI logging、安全校验、workbench board、repo hygiene 等。测试真实度整体较好，但 Excel/PowerBI 仍主要依赖 monkeypatch/fake COM/fake process。

## 3. Top Risks

| Priority | Finding | Severity | Summary |
|----------|---------|----------|---------|
| 1 | 核心模块和长函数仍是主要结构债 | Medium | 5 个核心文件超过 1000 行，多个函数超过 100 行，后续 UI/engine/database 改动仍容易牵连。 |
| 2 | 执行器 execute 方法仍混合过多职责 | Medium | Python/Excel/PowerBI/SubWorkflow 执行器把验证、执行、取消、日志和结果语义合在一个方法。 |
| 3 | Excel/PowerBI 外部自动化清理仍有静默兜底 | Medium | COM close/quit/taskkill/pywinauto fallback 多处吞异常或成功语义不够精确。 |
| 4 | 数据库 session 生命周期仍依赖调用方纪律 | Medium | `get_session()` 明确不 remove，并返回 ORM 对象，长运行 UI/worker 有 stale state 和 identity map 风险。 |
| 5 | `_ensure_step_uid_unique` 会在迁移中删除重复步骤 | Medium | 迁移保留最大 id 并删除其余重复 uid 步骤，缺少删除前导出和依赖/日志引用检查。 |
| 6 | JSON 导入 schema 校验仍偏宽 | Medium | 多处 `.get()` 默认值和 `int(...)` 强转会让坏数据错误定位不清，部分字段静默默认。 |
| 7 | 发布流程缺少打包后 exe smoke | Medium | package workflow 只检查 exe 存在和 SHA256，未运行产物的 `--smoke`/`--help`。 |
| 8 | PowerBI 自动刷新成功语义不够精确 | Medium | 进程正常结束和自动刷新真正触发是两个事实，当前 result contract 容易被误读。 |
| 9 | CLI 和脚本入口仍有双入口维护成本 | Medium | `src/cli.py` 与 `_import_and_run.py` 都实现导入/运行语义，后续容易漂移。 |
| 10 | UI 构造与主题函数仍偏长 | Low | StepEditor、WorkflowConfig、WebhookManager、RunControl、theme stylesheet 仍集中大量 UI 拼装。 |
| 11 | 测试真实性在外部集成边界仍不足 | Low | 单测多且有价值，但 Excel/PowerBI 真实桌面集成无法由当前 CI 证明。 |
| 12 | 本地 `dist/` 仍保留大 exe 残余物 | Low | 已不被 Git 跟踪，但工作区仍有约 50MB 和 66MB 的本地构建产物。 |
| 13 | 文档和交接材料存在历史噪声 | Low | 多份 handover/review 文档可能降低新维护者定位当前事实的效率。 |

## 4. Detailed Findings

### Finding: 核心模块和长函数仍是主要结构债

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: MainWindow / WorkflowEngine / StepTablePanel / database / StepEditor
- Evidence:
  - File: `src/ui/main_window.py:1`
  - Function / Module: `MainWindow`
  - Relevant behavior: 当前文件约 1726 行；`_on_run_requested()` 从 `src/ui/main_window.py:1439` 开始，仍包含运行冲突弹窗、取消当前运行、信号连接、重试闭包和线程启动。
  - File: `src/engine.py:1`
  - Function / Module: `WorkflowEngine`
  - Relevant behavior: 当前文件约 1390 行；`_run()` 从 `src/engine.py:612` 开始仍负责锁、上下文、查询、run history、信号、执行和收尾。
  - File: `src/ui/step_table/panel.py:1`
  - Function / Module: `StepTablePanel`
  - Relevant behavior: 当前文件约 1332 行；`load_steps()` 从 `src/ui/step_table/panel.py:484` 开始仍负责数据加载、批次计算和表格渲染协调。
- Problem: MainWindow、Engine、StepTable、database 和 StepEditor 都已经经历拆分，但仍承担多个变化原因。违反 SRP 1.1、File Size 1.2、Function Size 1.3。当前风险不是单点 bug，而是变更传播面仍大。
- Why it matters: 后续任何工作流运行、阶段排序、UI 主题、步骤编辑或数据库迁移的改动，都可能需要同时理解 UI、状态、持久化和执行语义。
- Realistic failure scenario: 维护者修改运行冲突逻辑时误断开 Qt signal，导致“停止当前并运行新的”无法重新触发；或者修改步骤表渲染时破坏批次标识和阶段进度联动。
- Minimal fix: 继续按边界拆分：`MainWindow` 只保留 composition/root wiring；运行请求抽到 `ui/run_actions.py`；`StepTablePanel.load_steps()` 抽出 query/view-model/render 三段。
- Better long-term fix: 建立稳定应用服务层，例如 `WorkflowRunService`、`WorkflowQueryService`、`StepOrderingService`，UI 只消费 DTO 和命令结果。
- Regression test suggestion: 为运行冲突弹窗、阶段移动、步骤加载和 run history 收尾分别保留行为测试，确保拆分不改变外部行为。
- Estimated effort: 3-5 days

### Finding: 执行器 execute 方法仍混合过多职责

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Executors
- Evidence:
  - File: `src/executors/powerbi_executor.py:80`
  - Function / Module: `PowerBIExecutor.execute`
  - Relevant behavior: 方法约 234 行，包含路径检查、PBIDesktop 查找、进程启动、自动刷新、等待、日志写入和结果映射。
  - File: `src/executors/excel_executor.py:59`
  - Function / Module: `ExcelExecutor.execute`
  - Relevant behavior: 方法约 215 行，包含 COM 初始化、连接设置、刷新等待、保存关闭、taskkill 和日志写入。
  - File: `src/executors/python_executor.py:141`
  - Function / Module: `PythonExecutor.execute`
  - Relevant behavior: 方法约 201 行，包含解释器解析、命令构造、子进程管理、取消/超时和输出线程。
  - File: `src/executors/sub_workflow_executor.py:35`
  - Function / Module: `SubWorkflowExecutor.execute`
  - Relevant behavior: 方法约 149 行，包含目标解析、循环检测、runner 注入、future 轮询、取消和超时。
- Problem: 执行器入口仍违反 SRP 1.1 和 Function Size 1.3。执行策略、资源管理和结果语义耦合在一个函数内，单元测试只能覆盖局部 fake 场景。
- Why it matters: 外部程序执行是最容易产生超时、取消、残留进程和文件锁的边界；职责混合会让修复一个边界行为时影响另一个边界。
- Realistic failure scenario: 为 PowerBI 增加新的刷新按钮定位策略时，误改了 auto_close 的等待/超时分支，导致用户关闭 PowerBI 后仍返回超时。
- Minimal fix: 每个 executor 先抽出 `prepare_context()`、`run_external()`、`cleanup()`、`write_logs()`、`to_result()`，保持 public `execute()` 签名不变。
- Better long-term fix: 建立通用 `ExternalProcessRun` / `DesktopAutomationRun` 模板，把取消、超时、日志、进程树清理和结果状态统一到 base 层。
- Regression test suggestion: 对每个 executor 增加取消、超时、依赖缺失、清理失败、日志落盘和结果 extra/error_message 的参数化测试。
- Estimated effort: 2-4 days

### Finding: Excel/PowerBI 外部自动化清理仍有静默兜底

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: ExcelExecutor / PowerBIExecutor
- Evidence:
  - File: `src/executors/excel_executor.py:145`
  - Function / Module: `ExcelExecutor.execute`
  - Relevant behavior: 获取 Excel PID 失败时设置 `excel_pid = None`；连接属性设置失败、workbook close、Excel quit、taskkill、gc、CoUninitialize 多处 `except Exception: pass`。
  - File: `src/executors/excel_executor.py:200`
  - Function / Module: `ExcelExecutor.execute`
  - Relevant behavior: finally 中的关闭和释放路径吞掉异常；如果这些失败，返回结果只可能带主错误，不一定暴露清理失败。
  - File: `src/executors/powerbi_executor.py:324`
  - Function / Module: `PowerBIExecutor._try_auto_refresh`
  - Relevant behavior: `connect(process=pid)` 失败后 fallback 到 `connect(path=pbidesktop)`；自动刷新失败会追加 `error_messages`，但主流程 `src/executors/powerbi_executor.py:284` 仍可返回 `success=True`。
- Problem: 这是典型 fallback/empty catch 风险。部分兜底是合理的资源释放策略，但当前没有统一 warning 或 structured warning 输出。违反 Fail-Fast 4.4 和 Don't Swallow Errors 6.1。
- Why it matters: Excel/PowerBI 清理失败常见后果是进程残留、文件锁未释放、下一次刷新失败或误操作其他窗口。静默吞掉清理异常会增加定位成本。
- Realistic failure scenario: Excel COM `Quit()` 失败且未拿到 PID，文件保持锁定；用户下一步 Python 脚本读同一个文件失败，但日志只显示后续步骤失败。
- Minimal fix: 对清理失败追加 warning 到 stderr 或 `ExecutorResult.extra["warnings"]`；PowerBI 自动刷新失败时把结果语义改为 `success=True` + `warning` 或可配置为 fail-fast。
- Better long-term fix: 建立 `CleanupReport`，记录每个清理动作的状态，并由 engine 在 step log 中保存 warnings。
- Regression test suggestion: monkeypatch workbook.Close、excel.Quit、taskkill、pywinauto connect 失败，断言结果中出现 warning 且主错误不被覆盖。
- Estimated effort: 1-2 days

### Finding: 数据库 session 生命周期仍依赖调用方纪律

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Database session management
- Evidence:
  - File: `src/database.py:448`
  - Function / Module: `get_session`
  - Relevant behavior: 注释明确“不在此处调用 scoped_session.remove()”，原因是 database.py 中的函数经常返回 ORM 对象供调用方使用。
  - File: `src/database.py:464`
  - Function / Module: `get_session`
  - Relevant behavior: 从 `_scoped_session()` 取得线程 session；正常路径 yield 后不 remove，异常路径才 rollback + remove。
  - File: `src/database.py:477`
  - Function / Module: `cleanup_session`
  - Relevant behavior: 需要应用退出或 worker 结束时显式释放当前线程 session。
- Problem: 当前设计把 session 生命周期转移给调用方纪律。虽然 worker cleanup 已补强，但 UI 主线程长期运行时仍可能保留 stale ORM 对象和 identity map。违反 Explicit Dependencies 7.3 和 resource management 原则。
- Why it matters: 长生命周期 ORM session 会让“数据库当前值”和“UI 持有对象”之间出现不一致，也可能让内存随长时间使用增长。
- Realistic failure scenario: UI 读取一个 workflow ORM 对象后，另一路导入/迁移修改同一 workflow；UI 后续基于旧对象保存配置，覆盖新字段或显示过期状态。
- Minimal fix: 给高频 query 增加 DTO/dict 返回函数；对返回 ORM 的函数明确命名或文档标记；在主窗口关键刷新点调用 `cleanup_session()` 或 `expire_all()`。
- Better long-term fix: 将 database 层分成 repository + DTO mapper，UI/engine 不直接持有 ORM 实体。
- Regression test suggestion: 构造同线程两次读取和外部更新场景，验证 DTO 查询不会返回 stale state；验证 worker 完成后 session remove 被调用。
- Estimated effort: 2-4 days

### Finding: `_ensure_step_uid_unique` 会在迁移中删除重复步骤

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Database migration
- Evidence:
  - File: `src/database.py:380`
  - Function / Module: `_ensure_step_uid_unique`
  - Relevant behavior: 迁移扫描 `(workflow_id, uid)` 重复步骤。
  - File: `src/database.py:392`
  - Function / Module: `_ensure_step_uid_unique`
  - Relevant behavior: 每组重复保留 `MAX(id)`。
  - File: `src/database.py:397`
  - Function / Module: `_ensure_step_uid_unique`
  - Relevant behavior: 执行 `DELETE FROM steps WHERE workflow_id=:w AND uid=:u AND id != :k`。
- Problem: 迁移在没有导出删除行、没有检查依赖引用和历史日志语义的情况下删除步骤。目标是修复唯一约束，动机合理，但数据保留策略偏激进。
- Why it matters: 对旧库而言，重复 uid 可能来自导入 bug、兼容脚本或用户手工数据修复；直接保留最新 id 可能丢失仍被依赖的步骤语义。
- Realistic failure scenario: A 步骤依赖旧重复 uid 对应的早期步骤，迁移删除旧行后，依赖解析指向保留的新行，执行顺序和业务含义改变。
- Minimal fix: 删除前把重复组写入迁移备份表或 JSON 文件，并记录 warning；删除前检查依赖、日志和 stage 引用。
- Better long-term fix: 迁移策略改为“重命名重复 uid + 保留行 + 修复依赖映射”，再创建唯一索引。
- Regression test suggestion: 构造重复 uid 且存在 depends_on 的旧库，运行迁移后断言没有业务步骤被直接丢失，或至少产生可恢复备份。
- Estimated effort: 1-2 days

### Finding: JSON 导入 schema 校验仍偏宽

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: JSON import/export boundary
- Evidence:
  - File: `src/database_import_export.py:224`
  - Function / Module: `_build_workflow`
  - Relevant behavior: 大量使用 `wf_data.get(..., default)` 构造 workflow，缺少字段类型和范围校验。
  - File: `src/database_import_export.py:275`
  - Function / Module: `_import_stages`
  - Relevant behavior: 非 dict stage 被跳过；`order` 通过 `int(...)` 强转。
  - File: `src/database_import_export.py:312`
  - Function / Module: `_import_steps`
  - Relevant behavior: 未先验证 `steps_data` 元素类型；`retry_count` 强转，布尔字段用 `bool(...)`，坏类型可能运行时异常或被静默解释。
- Problem: 导入边界仍混合默认值、静默跳过和运行时强转。违反 Fail-Fast 4.4 和 InputBoundary 类型安全要求。
- Why it matters: JSON 是用户可编辑/迁移/备份恢复边界。错误信息如果不能指出 workflow/stage/step 索引和字段名，会让恢复失败难以定位。
- Realistic failure scenario: 用户导入旧 JSON，`retry_count` 是 `"abc"`，导入过程抛出 ValueError，但错误没有说明是第几个 workflow 的第几个 step，用户只能手动二分文件。
- Minimal fix: 增加轻量 schema validator，返回包含路径的错误，例如 `workflows[2].steps[5].retry_count must be int`。
- Better long-term fix: 使用 dataclass/pydantic-like 内部 schema 对导入数据先解析为 DTO，再落 ORM。
- Regression test suggestion: 覆盖坏类型、缺字段、未知字段、stage 非对象、step 非对象、布尔字符串等导入错误，断言错误路径明确。
- Estimated effort: 1-2 days

### Finding: 发布流程缺少打包后 exe smoke

- Severity: Medium
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: GitHub Actions package workflow
- Evidence:
  - File: `.github/workflows/package.yml:33`
  - Function / Module: Package workflow
  - Relevant behavior: 运行 `pyinstaller ${{ inputs.spec }} --noconfirm`。
  - File: `.github/workflows/package.yml:36`
  - Function / Module: Verify artifact
  - Relevant behavior: 只检查 `dist/*.exe` 存在并输出 SHA256。
  - File: `src/main.py:28`
  - Function / Module: `main`
  - Relevant behavior: GUI 入口已支持 `--smoke` 启动后立即退出，但 package workflow 未运行生成 exe 的 smoke。
- Problem: 发布流程已经有 CI 和 artifact hash，但只证明“构建出了 exe”，没有证明打包产物能启动、资源路径能解析、Qt 插件能加载。
- Why it matters: PyInstaller 问题常发生在开发态测试之后，例如缺 DLL、缺 Qt platform plugin、资源路径错误、隐藏导入缺失。
- Realistic failure scenario: CI 构建成功并上传 exe；用户下载后双击立即退出，因为 PyInstaller 漏收某个 Qt/plugin/图标资源，而 package workflow 没有捕获。
- Minimal fix: 在 package workflow 里运行最新 exe 的 `--smoke`，设置 `QT_QPA_PLATFORM=offscreen`，并收集退出码和 stdout/stderr。
- Better long-term fix: 增加 release manifest、版本号检查、hash 文件上传、签名步骤和 rollback checklist。
- Regression test suggestion: GitHub Actions package job 中新增 `& $exe.FullName --smoke`，并在失败时上传 dist 日志。
- Estimated effort: 1-3 hours

### Finding: UI 构造与主题函数仍偏长

- Severity: Low
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: PySide6 UI
- Evidence:
  - File: `src/ui/step_editor.py:88`
  - Function / Module: `StepEditorPanel._setup_ui`
  - Relevant behavior: 方法约 268 行。
  - File: `src/ui/workflow_config.py:48`
  - Function / Module: `WorkflowConfigPanel._setup_ui`
  - Relevant behavior: 方法约 184 行。
  - File: `src/ui/webhook_manager.py:33`
  - Function / Module: `WebhookManagerDialog._setup_ui`
  - Relevant behavior: 方法约 141 行。
  - File: `src/ui/theme.py:193`
  - Function / Module: `get_stylesheet`
  - Relevant behavior: 方法约 401 行。
- Problem: UI 拼装函数仍远超 50 行目标。它们主要是布局和样式，不是高风险业务逻辑，因此定级为 Low。
- Why it matters: UI 长函数会让可访问性、响应式约束、状态启用/禁用、主题切换和控件引用变得难以局部验证。
- Realistic failure scenario: 新增 StepEditor 字段时插入到错误 layout 区块，保存逻辑使用旧控件引用，导致 UI 显示字段但保存不生效。
- Minimal fix: 按 section/component 拆出 `_build_basic_section()`、`_build_dependency_section()`、`_build_advanced_section()`；stylesheet 拆成 token + component snippets。
- Better long-term fix: 为 UI section 建立 dataclass 控件句柄和独立测试，减少 panel 持有的零散 widget 字段。
- Regression test suggestion: 针对 StepEditor 保存、只读状态、主题刷新和字段默认值建立控件级测试。
- Estimated effort: 1-3 days

### Finding: 测试真实性在外部集成边界仍不足

- Severity: Low
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: Executor integration tests
- Evidence:
  - File: `tests/test_executor_policies.py:13`
  - Function / Module: `install_fake_excel_modules`
  - Relevant behavior: 使用 `SimpleNamespace` 注入 fake `pythoncom` / `win32com`。
  - File: `tests/test_executor_policies.py:173`
  - Function / Module: `test_excel_executor_waits_for_async_queries_before_saving`
  - Relevant behavior: 用 fake Excel app/workbook/connections 覆盖 COM 行为。
  - File: `tests/test_executor_policies.py:512`
  - Function / Module: `test_powerbi_executor_can_cancel_during_startup_wait`
  - Relevant behavior: monkeypatch PowerBI 路径和 fake `subprocess.Popen`。
- Problem: 当前测试很好地覆盖策略和回归点，但不能证明真实 Excel/PowerBI 桌面集成在目标机器上可用。
- Why it matters: COM、pywinauto、Power BI Desktop 和 Windows UI 自动化受版本、权限、窗口焦点和本机环境影响很大。
- Realistic failure scenario: 单测全部通过，但某台发布机器的 Power BI Desktop 窗口标题/焦点行为不同，F5 没有触发刷新，执行仍返回成功 note。
- Minimal fix: 增加手动/可选 integration smoke：真实 xlsx 刷新、真实 pbix 启动、取消、超时、清理进程检查。
- Better long-term fix: 将外部桌面自动化纳入 nightly/manual Windows job，并记录依赖版本和前置条件。
- Regression test suggestion: 新增 `pytest -m integration_desktop` 标记，默认 CI 不跑；发布前在 Windows 桌面环境执行。
- Estimated effort: 0.5-2 days

### Finding: 本地 `dist/` 仍保留大 exe 残余物

- Severity: Low
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Repository hygiene / local artifacts
- Evidence:
  - File: `dist/工作流管理_4.0.0.exe`
  - Function / Module: local artifact
  - Relevant behavior: 本地文件大小约 66,110,267 bytes，修改时间 2026-06-02 09:30:55。
  - File: `dist/工作流管理_4.0.0_slim2.exe`
  - Function / Module: local artifact
  - Relevant behavior: 本地文件大小约 49,959,869 bytes，修改时间 2026-06-02 09:31:50。
  - File: `tools/repo_hygiene.py:13`
  - Function / Module: `TRACKED_ARTIFACT_PREFIXES`
  - Relevant behavior: hygiene 已检查 build/dist/data/logs 和 exe/db/sqlite 后缀；当前 `git ls-files -s dist` 无输出。
- Problem: 产物已从 Git 索引移除，repo hygiene 也通过，所以这不是仓库污染问题。但本地工作区仍保留大体积构建产物，容易在人工复制、压缩或扫描时混入。
- Why it matters: 本地残留 artifact 会拖慢搜索、备份和安全扫描，也可能被误传到共享目录。
- Realistic failure scenario: 维护者打包整个工作目录发给他人，`dist` 下旧 exe 被误认为最新发布产物。
- Minimal fix: 保持 `.gitignore` 和 repo hygiene；在发布文档里明确 `dist/` 是本地产物，不进入 Git。
- Better long-term fix: 统一把 release artifact 只放在 CI artifact 或版本化 release 目录，并定期清理本地 `dist`。
- Regression test suggestion: 保留 `test_repo_hygiene.py` 中 tracked artifact 检查，新增 README 发布说明检查可选。
- Estimated effort: 15-30 minutes

### Finding: 文档和交接材料存在历史噪声

- Severity: Low
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Documentation
- Evidence:
  - File: `HANDOVER.md:1`
  - Function / Module: project docs
  - Relevant behavior: 项目根目录存在 handover 文档。
  - File: `HANDOVER_AI_SWITCH_2026-02-13.md:1`
  - Function / Module: project docs
  - Relevant behavior: 项目根目录存在按日期命名的交接文档。
  - File: `05_整体Review与改进建议.md:1`
  - Function / Module: project docs
  - Relevant behavior: 根目录仍保留历史 review 文档；同时本次和上次审计报告也在根目录。
- Problem: 历史文档有价值，但根目录长期堆积 review/handover/audit 会让新维护者难以判断哪份是当前事实源。
- Why it matters: 文档噪声会造成维护者按旧方案执行，或者误以为旧问题仍未修复。
- Realistic failure scenario: 新维护者打开旧 handover，按过期模块结构排查问题，忽略当前已经拆出的 `database_import_export.py` 和 `engine_core/*`。
- Minimal fix: 将历史审计和交接归档到 `docs/archive/`，README 只链接“当前维护入口”和最新审计报告。
- Better long-term fix: 建立 `docs/MAINTENANCE.md` 作为单一维护入口，历史材料只作为附录。
- Regression test suggestion: 无需自动化强制；可在 repo hygiene 中可选检查根目录 Markdown 白名单。
- Estimated effort: 30-60 minutes

### Finding: PowerBI 自动刷新成功语义不够精确

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: PowerBIExecutor result contract
- Evidence:
  - File: `src/executors/powerbi_executor.py:227`
  - Function / Module: `PowerBIExecutor.execute`
  - Relevant behavior: auto_refresh 打开时调用 `_try_auto_refresh()`，该函数将失败写入 `error_messages`。
  - File: `src/executors/powerbi_executor.py:281`
  - Function / Module: `PowerBIExecutor.execute`
  - Relevant behavior: 若不是取消/超时/启动失败，最终返回 `ExecutorResult(success=True)`；只有 `note` 在有无 `error_messages` 时不同。
  - File: `src/executors/powerbi_executor.py:343`
  - Function / Module: `_try_auto_refresh`
  - Relevant behavior: 未安装 pywinauto 或自动刷新失败只追加错误消息。
- Problem: “Power BI 进程正常结束”和“自动刷新已触发成功”是两个不同事实。当前 `success=True` 容易被上层解释成刷新成功。
- Why it matters: 工作流引擎通常只看 executor success 决定后续步骤是否继续；如果实际没有触发刷新，后续步骤可能处理旧数据。
- Realistic failure scenario: 机器未安装 pywinauto，PowerBI 打开后用户未手动刷新但关闭窗口；步骤返回成功，后续 Python 脚本生成基于旧数据的报表。
- Minimal fix: 将自动刷新状态写入 `extra={"auto_refresh": "succeeded|failed|disabled", "warnings": [...]}`，并在 UI/日志中明确显示。
- Better long-term fix: 增加 PowerBI 刷新确认机制，例如检测文件修改时间、用户确认或可配置 fail-on-auto-refresh-failure。
- Regression test suggestion: 模拟 pywinauto 缺失和 connect 失败，断言 result.extra 包含失败状态，且 engine step log 能显示 warning。
- Estimated effort: 0.5-1 day

### Finding: CLI 和脚本入口仍有双入口维护成本

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: CLI / import-and-run script
- Evidence:
  - File: `src/cli.py:744`
  - Function / Module: `main`
  - Relevant behavior: `src/cli.py` 约 756 行，负责 export、backup、history、run 等命令。
  - File: `_import_and_run.py:1`
  - Function / Module: batch import/run script
  - Relevant behavior: 独立脚本自行初始化 QApplication、导入 JSON、查找 workflow、连接 engine signals 并运行。
  - File: `.github/workflows/ci.yml:40`
  - Function / Module: CLI smoke
  - Relevant behavior: CI 同时 smoke `src/cli.py` 和 `_import_and_run.py`。
- Problem: 主 CLI 和 `_import_and_run.py` 都承载导入/运行语义，存在双入口漂移风险。当前 `_import_and_run.py` 可用，但它绕过了部分 `src/cli.py` 命令组织。
- Why it matters: 后续如果运行参数、通知策略、导入选项或错误码契约变化，维护者需要同时更新两个入口。
- Realistic failure scenario: `src/cli.py run` 新增某个安全预检，但 `_import_and_run.py run` 未同步，批处理路径仍允许旧行为。
- Minimal fix: 让 `_import_and_run.py` 调用 `src/cli.py` 的命令函数或共享 service，而不是重复实现 workflow 查找和运行信号处理。
- Better long-term fix: 抽出 `WorkflowCommandService`，GUI、CLI 和批处理脚本共享同一运行契约。
- Regression test suggestion: 增加 CLI 与 `_import_and_run.py` 对同一不存在 workflow、导入失败、运行失败的错误码一致性测试。
- Estimated effort: 1-2 days

## 5. Security Concerns

已验证的安全改进包括：Webhook URL 管理界面要求 `https://oapi.dingtalk.com/robot/send?access_token=...`，默认导出/备份脱敏，显式 `--include-secrets` 才保留完整密钥，`tools/repo_hygiene.py` 会扫描 tracked artifact 和未脱敏 access_token。`tests/test_ui_security.py`、`tests/test_schema_guards.py`、`tests/test_repo_hygiene.py` 覆盖这些路径。

本轮没有发现新的 Critical/High 安全问题。剩余安全相关风险主要是配置/导入边界：JSON 导入校验偏宽、显式 include-secrets 依赖用户纪律、本地 `dist` artifact 需要继续避免进入 Git。

## 6. Stability Concerns

稳定性最主要的剩余风险集中在外部自动化和持久化边界。Excel/PowerBI 执行器已经有取消、超时、taskkill 和进程树清理策略，但清理失败还没有统一 warning 契约。数据库 session 正常路径不 remove 是为了避免 ORM detached，但长期运行 UI 会承担 stale state 风险。

阶段变更已明显改善：`src/stage_mutation_service.py` 将阶段/步骤顺序变更放在事务里，并用 `engine_core.batch.compute_batches` 预校验未来依赖。对应 `tests/test_stage_mutation_service.py` 已覆盖事务提交、迁移阶段步骤和失败回滚。

## 7. Performance Concerns

项目规模下没有发现明显的热路径灾难。`compute_batches` 和 step table view model 已将部分 O(n) 结构前置；日志清理、watcher、run state 等已有独立 helper。

剩余性能风险主要是 UI 重建和大函数维护成本：`src/ui/workbench_board.py:450 refresh_theme` 约 203 行，`src/ui/theme.py:193 get_stylesheet` 约 401 行。它们不一定造成当前卡顿，但会让主题切换、响应式调整和控件状态维护变得难以优化。

## 8. Testing Gaps

当前测试数量和质量比上次审计明显提高：`pytest -q` 当前为 137 passed。测试覆盖 CLI contract、schema guard、导入导出脱敏、阶段事务、engine scheduling、executor policy、UI 安全、workbench board 阶段进度和左右键切换。

测试缺口集中在真实桌面自动化和打包产物。Excel/PowerBI 使用 fake COM/fake process 是合理的单元测试策略，但它不能替代发布前真实环境 smoke。package workflow 也还没有运行生成 exe 的 `--smoke`。

## 9. Maintainability Concerns

维护性分数仍被大文件和长函数拉低。当前拆分方向正确：`database_import_export.py`、`database_backup.py`、`database_clone.py`、`database_versions.py`、`engine_core/*`、`ui/run_actions.py`、`ui/run_state.py`、`ui/main_window_theme.py`、`ui/step_table/*` 都在降低单文件职责。

下一步不建议大爆炸重写，而是继续沿现有 helper 边界拆。优先从低风险的 UI section、executor cleanup/report 和 database DTO query 开始，每拆一次跑对应测试和全量 pytest。

## 10. Design / Principles Concerns

主要违反原则是 SRP 1.1、File Size 1.2、Function Size 1.3、Fail-Fast 4.4、Don't Swallow Errors 6.1、Explicit Dependencies 7.3。已遵守较好的原则包括：安全默认值、字段白名单、事务性阶段变更、CI 自动验证、仓库卫生 gate、取消/超时边界测试。

设计层面最大进步是将阶段顺序变更、engine core 辅助逻辑和 database 边界逐步拆出；最大残留问题是 UI/engine/database 仍共享 ORM 对象和大量直接函数调用，应用服务层还没有形成稳定边界。

## 11. Release Concerns

Release 基础已经可用：`.github/workflows/ci.yml` 在 Windows runner 上安装依赖、编译、跑 repo hygiene、pytest 和 CLI smoke；`.github/workflows/package.yml` 支持手动 PyInstaller 打包、SHA256 输出和 artifact 上传；`requirements-release.txt` 锁定直接运行依赖。

剩余缺口是发布产物级验证：package workflow 未运行 exe，未检查 `src/main.py --smoke` 的打包形态，未生成 release manifest，未签名，未记录回滚策略。对稳定公开发布而言，这些应该在发布前补齐。

## 12. Documentation Accuracy

README 已说明 compile、pytest、CLI smoke、CI 和 package workflow，整体与当前工程状态相符。文档风险不是缺失，而是历史文档太多：根目录存在多份 handover、review 和旧审计报告，建议归档历史材料，减少当前事实源噪声。

## 13. Configuration Safety

配置层面已补强：Webhook 默认脱敏，CLI backup/export 显式提示 include-secrets，watch 配置有规则测试，release dependencies 单独锁定。`src/config.py` 和相关测试已经覆盖配置错误日志和目录创建错误。

仍需注意导入 JSON 中的默认值策略。对外部 JSON，默认值应该只用于兼容明确版本，坏类型应 fail-fast 并给出字段路径。

## 14. Observability

执行日志、run history、step log、UI log panel 和 notifier 错误上下文都在改善。`tests/test_ui_logging.py` 覆盖了多个 UI 失败日志场景，`src/diagnostics.py` 能提供错误诊断。

观测缺口在 warnings：清理失败、PowerBI 自动刷新失败、fallback 激活等情况还没有统一结构化记录。建议将 executor warning 纳入 step log 或 result extra。

## 15. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 3 | 2 | 1 | 0 |
| EmptyCatch | 6 | 5 | 1 | 0 |
| CompatibilityBranch | 2 | 2 | 0 | 0 |
| SilentCorrection | 3 | 1 | 2 | 0 |
| DefensiveGuess | 2 | 2 | 0 | 0 |

主要 fallback 包括 Excel 清理、PowerBI connect fallback、JSON 导入默认值和迁移重复 uid 清理。合理兜底应保留，但需要 warning；导入坏类型和迁移删除数据这类边界应更接近 fail-fast 或可恢复策略。

## 16. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|-----------------|------|--------|
| Schema guards / import-export | High | 可捕获字段白名单、脱敏和迁移失败路径 | Keep |
| Stage mutation service | High | 可捕获阶段移动事务和依赖预校验回滚 | Keep |
| Engine scheduling / cancellation | Medium-High | 可捕获调度、取消、嵌套工作流策略问题 | Keep |
| Executor policies | Medium | 策略覆盖好，但外部桌面真实行为仍逃逸 | Keep but augment |
| UI workbench board | Medium | 阶段进度和左右键切换有直接回归保护 | Keep |
| Package executable | Low | 当前只证明构建产物存在，不证明可启动 | Add smoke |

### Valuable Tests

`tests/test_stage_mutation_service.py`、`tests/test_schema_guards.py`、`tests/test_workbench_board.py`、`tests/test_repo_hygiene.py` 和 `tests/test_executor_policies.py` 是当前最有价值的回归保护。它们覆盖真实业务规则，而不是只测试实现细节。

### Suspicious Tests

没有发现需要删除的假测试。需要注意的是 executor 外部集成测试使用大量 monkeypatch 和 `SimpleNamespace`，这些是合理的单元替身，但不能被当成真实 Excel/PowerBI 集成证明。

### Missing Tests

缺少打包后 exe smoke、真实 Excel/PowerBI manual/nightly integration、JSON 坏 schema 精确错误路径、迁移重复 uid 的依赖保留策略测试。

## 17. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 2 | 0 | 0 | 2 | 0 |
| InputBoundary | 2 | 0 | 0 | 2 | 0 |
| OutputLeak | 0 | 0 | 0 | 0 | 0 |
| BooleanTrap | 1 | 0 | 0 | 0 | 1 |
| StringlyTyped | 2 | 0 | 0 | 1 | 1 |
| ErrorType | 1 | 0 | 0 | 0 | 1 |

Python 项目本身没有静态类型强制。当前最大类型风险是 JSON 导入边界用 dict + `.get()` + 强转，executor result/status 也较依赖字符串状态。建议先补输入 schema，再考虑为核心 DTO 和 result extra 加 TypedDict/dataclass。

## 18. Frontend State Analysis

### Summary

| Subtype | Count | Affected Components |
|---------|-------|---------------------|
| ComponentSize | 5 | MainWindow, StepTablePanel, StepEditorPanel, WorkbenchBoardPanel, Theme |
| StateDuplication | 2 | MainWindow run state, WorkbenchBoard selected stage |
| PropDrilling | 1 | MainWindow panel wiring |
| EffectChain | 2 | theme refresh, run retry after stop |
| UIBusinessCoupling | 3 | MainWindow, StepTablePanel, StepEditorPanel |
| DOMasState | 0 | N/A |
| RequestState | 1 | run thread / engine signal bridge |
| RenderPerf | 2 | StepTablePanel load, WorkbenchBoard refresh_theme |

阶段卡片进度条和左右键切换已实现并测试。前端状态的主要问题不在单个功能缺失，而是 MainWindow 仍承担太多协调职责，运行状态、面板状态、主题刷新和后台运行提示仍在同一个类中交织。

## 19. Backend API Analysis

本项目没有网络后端 API；等价边界是 CLI、JSON import/export、SQLite repository、executor contract 和 Webhook notifier。

### Summary

| Subtype | Count | Affected Endpoints |
|---------|-------|-------------------|
| ApiConsistency | 2 | CLI / `_import_and_run.py`, ExecutorResult |
| Validation | 2 | JSON import, Webhook URL |
| Auth | 0 | N/A |
| NplusOne | 0 | N/A |
| Caching | 1 | ORM scoped_session identity map |
| ErrorResponse | 2 | JSON import errors, executor warnings |
| BusinessLogic | 2 | engine/database coupling, stage mutation |
| DataFlow | 2 | ORM object returns, import/export |

Webhook URL 验证和字段白名单是强项；JSON 导入错误路径、executor result warning 和 ORM session 生命周期是主要待优化项。

## 20. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|--------------------|
| PySide6==6.10.1 | Healthy / Heavy but required | Large | Many | Desktop GUI | Keep |
| SQLAlchemy==2.0.46 | Healthy | Medium | Some | SQLite ORM | Keep |
| pywin32==311 | Healthy / Platform-specific | Medium | Few | Excel COM | Keep |
| pywinauto==0.6.9 | Optional but useful | Medium | Some | PowerBI automation | Keep with graceful warning |
| watchdog==6.0.0 | Healthy | Medium | Few | File watching | Keep |
| psutil==7.2.2 | Healthy | Medium | Few | Process tree cleanup | Keep |
| requests==2.32.5 | Healthy | Small | Some | DingTalk webhook | Keep |

依赖集合与产品目标匹配，没有发现明显未使用的重量级依赖。发布依赖已经单独锁定在 `requirements-release.txt`，这是正向改进。

---

## 21. Principles Compliance

代码库在安全默认、事务化变更、测试保护和发布 gate 上进步明显；结构层面仍需要继续拆分。当前不是“不可维护”，但核心模块仍偏重，外部边界的 warning/error contract 还不够明确。

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP 1.1) | 5 | Medium | MainWindow, Engine, StepTablePanel, database, executors |
| File Size Limit (1.2) | 5 | Medium | main_window.py, engine.py, panel.py, database.py, step_editor.py |
| Function/Method Size (1.3) | 20+ | Medium | theme, executor execute, UI setup, engine run |
| Fail-Fast (4.4) | 3 | Medium | JSON import, migration duplicate cleanup, PowerBI auto refresh |
| Don't Swallow Errors (6.1) | 6 | Medium | Excel cleanup, PowerBI fallback, database cleanup_session |
| Explicit Dependencies (7.3) | 2 | Medium | scoped_session, CLI/script duplicate entry |
| Timeout Every External Call (10.4) | Mostly respected | Low | requests/subprocess/COM paths mostly have timeouts |

### Principles Respected

字段白名单、Webhook 脱敏、repo hygiene、CI gate、阶段事务服务、取消/超时策略、run history/step log、测试覆盖和 release constraints 都是当前代码库中值得保留的工程基线。

---

## 22. Recommended Fix Order

### Fix Immediately

没有发现需要立即阻断使用的 Critical/High 问题。

### Fix Before Stable Release

| Order | Issue | Why |
|-------|-------|-----|
| 1 | 打包后 exe smoke | 成本低，能直接捕获 PyInstaller 产物不可启动。 |
| 2 | Excel/PowerBI warning contract | 外部自动化失败是最现实的用户风险。 |
| 3 | `_ensure_step_uid_unique` 数据保留策略 | 迁移删除数据必须可恢复、可解释。 |
| 4 | JSON 导入 schema validation | 备份恢复和跨版本迁移需要明确错误路径。 |
| 5 | PowerBI 自动刷新 result extra | 避免 success 被误解为刷新真实完成。 |

### Schedule Later

| Order | Issue | Why |
|-------|-------|-----|
| 1 | Executor execute 分段 | 降低取消/超时/日志改动风险。 |
| 2 | database DTO/repository 化 | 减少 scoped_session 长生命周期副作用。 |
| 3 | MainWindow/StepTable/StepEditor 继续拆分 | 降低 UI 迭代成本。 |
| 4 | CLI 与 `_import_and_run.py` 共享 service | 避免双入口行为漂移。 |

### Ignore for Now

本地 `dist/` artifact 可以暂时保留，不影响 repo hygiene；历史文档噪声也不是功能风险，但建议在下一次文档整理时归档。

## 23. Quick Wins

| Task | Impact | Effort |
|------|--------|--------|
| package workflow 运行 `dist/*.exe --smoke` | 捕获打包产物启动失败 | 1-3 hours |
| ExecutorResult 增加 warnings/extra 展示 | 暴露清理和自动刷新失败 | 0.5-1 day |
| JSON 导入错误加字段路径 | 大幅提升恢复问题定位效率 | 0.5-1 day |
| 迁移重复 uid 删除前写备份 | 降低旧库迁移数据损失风险 | 0.5-1 day |
| README 标明 `dist/` 本地产物不进 Git | 降低 artifact 误传 | 15 minutes |
| 将历史 handover/audit 归档到 docs/archive | 降低根目录噪声 | 30-60 minutes |

## 24. Long-term Refactor Plan

1. Executor 分层
   - Motivation: 外部自动化是最容易出事故的边界。
   - Approach: 每个 executor 拆成 validate/prepare/run/cleanup/result；共用取消、超时、日志和 warning contract。
   - Risk: 行为细节容易变化。
   - Testing strategy: 先补充现有 executor policy 的 golden behavior，再逐个 executor 拆分。

2. Database repository + DTO
   - Motivation: 消除 UI/engine 持有长生命周期 ORM 对象。
   - Approach: 新增 query DTO，不一次性替换所有 CRUD；高频读取路径先迁移。
   - Risk: 需要处理已有调用方对 ORM relationship 的依赖。
   - Testing strategy: 增加 stale session、并发 worker cleanup、导入后刷新读取测试。

3. MainWindow composition root 化
   - Motivation: 让 MainWindow 只负责拼装和信号 wiring。
   - Approach: 运行命令、主题刷新、panel layout、JSON action、run state 继续外移到独立 helper/service。
   - Risk: Qt signal 生命周期和闭包断开容易回归。
   - Testing strategy: 保留 `tests/test_ui_main_window_actions.py` 和 watch UI 测试，每次拆分后全量 pytest。

4. StepTable/StepEditor section 化
   - Motivation: 降低 UI 功能迭代成本。
   - Approach: view model、row cell、stage header 已是好的方向；继续拆 table loading/rendering 和 editor sections。
   - Risk: 控件引用和保存逻辑容易脱节。
   - Testing strategy: 控件级测试覆盖字段默认值、保存、只读、阶段选择和依赖摘要。

5. Release hardening
   - Motivation: 当前 CI 证明源码可测，尚未充分证明产物可发。
   - Approach: package smoke、manifest、hash file、签名、release note 和 rollback checklist。
   - Risk: Windows runner/GUI offscreen 环境可能有兼容问题。
   - Testing strategy: 先跑 `--smoke`，再逐步增加启动日志和 artifact 校验。
