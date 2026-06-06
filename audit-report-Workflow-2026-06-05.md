# Fuck My Shit Mountain Audit Report

**Project:** Workflow  
**Audit mode:** full  
**Date:** 2026-06-05  
**Reviewer:** GPT-5 Codex

---

## 1. Executive Summary

这是一个本地 Windows 桌面工作流编排工具，核心能力围绕 PySide6 UI、SQLite/SQLAlchemy 持久化、工作流调度执行、Excel/Power BI/脚本执行器、钉钉通知和文件监听。项目已经有一批有价值的回归测试，当前基线 `pytest -q` 为 `69 passed in 5.98s`，调度、执行器策略、schema guard、监听规则和部分 UI 日志逻辑有真实保护。

主要风险不是“完全不可维护”，而是几个核心模块已经明显超载：`MainWindow`、`WorkflowEngine`、`database.py`、`StepTablePanel`、`StepEditorPanel` 同时承担 UI 编排、状态同步、持久化、错误处理和业务规则，导致修改成本和回归风险偏高。另有一个已确认的用户可触发缺陷：CLI 的 `history --detail` 使用了不存在的 `StepLog.duration` 和 `StepLog.step_name` 属性，会在该路径下崩溃。

发布和安全边界也偏弱：Webhook URL 明文存储并完整导出，依赖清单与代码/打包配置存在漂移，缺少 CI、锁文件、lint/type gate 和打包验证。对于个人本地工具这些问题可以分阶段修，但进入稳定分发前需要优先处理。

### Score Dashboard

```
Security        ██████░░░░  6.5  B   Webhook URL 明文展示/导出，适合本地但不适合无提示共享备份
Stability       ██████░░░░  6.0  B   CLI detail 可崩溃，迁移/配置/COM 路径存在静默失败
Performance     ███████░░░  7.0  A   暂无明确热点瓶颈，但 UI 全量刷新和大组件限制后续扩展
Testing         ██████░░░░  6.5  B   69 个测试有效，但缺 CI、CLI detail、打包和关键 UI 交互覆盖
Maintainability ████░░░░░░  4.5  C   多个 1000+ 行类/文件，SRP 和模块边界压力明显
Design          █████░░░░░  5.0  C   领域模型存在，但 fail-fast、类型边界和状态所有权不够清晰
Release         ████░░░░░░  4.5  C   依赖未锁定、缺 CI、打包 hiddenimports 与 requirements 漂移
─────────────────────────────────────
Overall         ██████░░░░  5.8  C
```

Each dimension scored 0.0-10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based. See `rubrics/scoring.md` for anchor descriptions.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 1 | 1 | 0 |
| Medium | 9 | 9 | 0 |
| Low | 4 | 4 | 0 |
| Info | 1 | 1 | 0 |
| **Total** | **15** | **15** | **0** |

## 2. Project Map

项目结构和主要职责：

| Area | Key files | Role |
|------|-----------|------|
| GUI entry | `src/main.py`, `src/ui/main_window.py` | PySide6 应用启动、主窗口、主题、菜单、运行控制、面板协作 |
| CLI entry | `src/cli.py` | 命令行运行工作流、查看历史、克隆工作流、钉钉通知 |
| Engine | `src/engine.py`, `src/engine_core/*` | 工作流运行、调度、生命周期、通知、文件监听 |
| Persistence | `src/database.py`, `src/models.py` | SQLite/SQLAlchemy session、迁移、CRUD、导入导出、克隆、历史 |
| Executors | `src/executors/*` | Python、Excel COM、Power BI、子工作流执行 |
| UI panels | `src/ui/*` | 步骤编辑、阶段表格、工作台看板、运行历史、配置、Webhook 管理 |
| Tests | `tests/*` | 调度、执行策略、schema guard、监听、UI 日志等回归测试 |
| Packaging | `build.spec`, `build_slim.spec`, `build_slim2.spec` | PyInstaller 打包配置 |

关键数据流：

1. GUI/CLI 选择工作流后从 `database.py` 读取 `Workflow`、`Step`、`WorkflowStage`。
2. `WorkflowEngine` 根据 `depends_on`、stage order、run mode 组织执行。
3. 执行器启动 Python/COM/Power BI/子工作流，写入运行历史和步骤日志。
4. UI 通过信号更新 DAG、工作台卡片、日志面板、历史列表。
5. 导入导出把工作流、步骤、阶段和 Webhook 配置序列化到 JSON。

风险集中区：

| Risk area | Why risky |
|-----------|-----------|
| `src/ui/main_window.py` | 2093 行，主窗口承担过多 UI、状态、业务流转和错误处理 |
| `src/database.py` | 1943 行，CRUD、迁移、导入导出、克隆和 schema guard 混合 |
| `src/engine.py` | 1535 行，调度、执行、通知、日志和取消路径耦合 |
| `src/ui/step_editor.py` / `src/ui/step_table/panel.py` | 表单和表格渲染逻辑巨大，状态同步与验证散落 |
| Webhook import/export | 明文 URL 会随备份文件外泄 |
| Build/dependencies | requirements、PyInstaller hiddenimports、实际 optional imports 不一致 |

## 3. Top Risks

| Priority | Finding | Severity | Summary |
|----------|---------|----------|---------|
| 1 | CLI `history --detail` 使用不存在的日志属性 | High | `src/cli.py` 访问 `log.duration` 和 `log.step_name`，但 `StepLog` 只有 `duration_seconds` 和 `step` relationship。 |
| 2 | Webhook URL 明文展示、存储和导出 | Medium | 导出的 JSON 直接包含 `webhook_url`，共享备份会泄露钉钉机器人 token。 |
| 3 | 核心模块过大且职责混杂 | Medium | 多个文件超过 1400 行，`WorkflowEngine` / `MainWindow` / `database.py` 均承担多类职责。 |
| 4 | 广义异常捕获和静默 fallback 过多 | Medium | 热点文件存在大量 `except Exception` / `pass`，真实失败容易被吞掉。 |
| 5 | schema 迁移失败后继续启动 | Medium | 迁移失败只记录日志并 `return`，可能让应用在半升级数据库上继续运行。 |
| 6 | 依赖清单与代码/打包配置漂移 | Medium | `watchdog`、`psutil` 被代码/打包使用但未在 requirements 声明，`networkx` 声明但当前未见使用。 |
| 7 | 缺少 CI、锁文件和静态检查 gate | Medium | 当前无法自动保证 Windows 打包、CLI、lint/type 和测试基线稳定。 |
| 8 | 类型边界和配置更新接口过宽 | Medium | 大量 `dict/list/object`、JSON 字符串、`**kwargs` 和长参数列表削弱契约。 |
| 9 | 测试覆盖真实但有关键缺口 | Medium | CLI detail、PyInstaller、Webhook 导出安全、主要 UI 交互缺少自动化覆盖。 |
| 10 | 旧 `copy_workflow` 复制依赖 UID 不重映射 | Medium | 虽当前 UI/CLI 使用 `clone_workflow`，但保留的函数会复制出引用源工作流 UID 的依赖。 |
| 11 | 缺失脚本路径允许保存 | Low | 编辑器只提示脚本路径不存在，仍保存可能在运行时失败的配置。 |
| 12 | `_import_and_run.py` 含硬编码 OneDrive 路径 | Low | 脚本绑定个人目录，离开当前机器不可复现。 |
| 13 | README 与代码状态漂移 | Low | README 仍列出不存在的 `_tmp_check.py`，并声明 `networkx` DAG 辅助但代码未见使用。 |
| 14 | 阶段看板缺少进度与键盘切换 | Low | `StageLane` 只有点击选中和卡片状态，缺用户提出的阶段进度和左右键导航。 |
| 15 | 后端 API 审计不适用，但 CLI/data contract 需补强 | Info | 项目无网络后端 API；主要 contract 风险在 CLI、DB CRUD 和 JSON 导入导出。 |

## 4. Detailed Findings

### Finding: CLI `history --detail` 使用不存在的日志属性

- Severity: High
- Confidence: High
- Category: Stability / Testing
- Status: Confirmed
- Affected area: CLI history detail
- Evidence:
  - File: `src/cli.py:580`
  - Function / Module: `cmd_history`
  - Relevant behavior: detail 分支遍历 `StepLog` 后访问 `log.duration` 和 `log.step_name`。
  - File: `src/models.py:285`
  - Function / Module: `StepLog`
  - Relevant behavior: 模型定义 `duration_seconds` property 和 `step` relationship，没有 `duration` 或 `step_name` 字段。
- Problem: CLI 的普通 history 列表路径可运行，但 `--detail` 路径会在存在步骤日志时触发 `AttributeError`。
- Why it matters: 这是用户可触发的真实崩溃，且历史详情通常用于排查失败，越在出错时越需要可靠。
- Realistic failure scenario: 用户运行 `python src/cli.py history --detail` 查看最近一次失败工作流，存在 step logs，程序在格式化第一条日志时崩溃，无法看到错误摘要。
- Minimal fix: 使用 `log.duration_seconds`，步骤名通过 `log.step.name` 或查询时 join/预加载 `Step` 获取；不存在 step 时显示 `step_id` fallback。
- Better long-term fix: 为 CLI 输出建立单独 DTO，例如 `StepLogView(step_name, status, duration_seconds, error_message)`，避免 CLI 直接依赖 ORM shape。
- Regression test suggestion: 构造含 `StepLog` 和关联 `Step` 的临时数据库，调用 `cmd_history` detail 分支并断言输出包含步骤名与耗时且不抛异常。
- Estimated effort: 30-60 分钟

### Finding: Webhook URL 明文展示、存储和导出

- Severity: Medium
- Confidence: High
- Category: Security / Release
- Status: Confirmed
- Affected area: Webhook manager, JSON import/export
- Evidence:
  - File: `src/models.py:344`
  - Function / Module: `WebhookConfig`
  - Relevant behavior: `webhook_url` 以 `Text` 明文存储。
  - File: `src/ui/webhook_manager.py:285`
  - Function / Module: `_load_webhook`
  - Relevant behavior: 编辑界面直接把完整 webhook URL 填入输入框。
  - File: `src/database.py:1560`
  - Function / Module: `export_to_json`
  - Relevant behavior: 导出 JSON 中完整写入 `"webhook_url": wh.webhook_url`。
  - File: `src/database.py:1377`
  - Function / Module: `import_from_json`
  - Relevant behavior: 导入同名 webhook 时以导入文件中的 URL 覆盖现有配置。
- Problem: 钉钉机器人 Webhook URL 通常包含访问 token。当前导出文件可被直接转发、提交或上传，泄露后外部人员可伪造机器人消息。
- Why it matters: 本地桌面工具不一定需要复杂密钥管理，但导出/共享边界必须默认保护敏感字段。
- Realistic failure scenario: 用户把 `workflows_export.json` 发给同事排查流程，文件中包含生产钉钉 webhook，接收方或中间存储获得发送权限。
- Minimal fix: 导出默认脱敏 `webhook_url`，增加显式 `include_secrets=True` 选项和 UI 确认；导入时对脱敏值不覆盖本机已有 URL。
- Better long-term fix: Windows 下使用 Credential Manager/DPAPI 存储 webhook token，数据库只保存引用名；导入导出只迁移非敏感元数据。
- Regression test suggestion: 覆盖 `export_to_json` 默认不包含完整 webhook URL；覆盖显式带密导出需要参数并带警示字段。
- Estimated effort: 0.5-1 天

### Finding: schema 迁移失败后继续启动

- Severity: Medium
- Confidence: High
- Category: Stability / Release
- Status: Confirmed
- Affected area: database initialization and migration
- Evidence:
  - File: `src/database.py:216`
  - Function / Module: `_run_pending_migrations`
  - Relevant behavior: migration exception 被 `logger.exception` 记录后 `return`，注释说明“不抛出，避免破坏冷启动”。
- Problem: 迁移失败后应用仍可能继续启动，后续代码会在未知 schema 版本上读写，错误位置会远离根因。
- Why it matters: 数据库迁移是持久化边界。半升级状态继续运行可能造成二次写入、字段缺失、导入导出异常或用户数据损坏。
- Realistic failure scenario: 用户升级版本时某个迁移因锁表或权限失败，应用仍打开；用户继续编辑步骤，后续写入落在旧 schema 上，引发难以恢复的不一致。
- Minimal fix: 迁移失败时 fail-fast，阻止 GUI/CLI 正常进入，并显示可操作错误信息和数据库路径；保留“下次重试”但不继续业务读写。
- Better long-term fix: 增加迁移事务、备份、schema health check 和恢复入口；启动时对实际 schema 与版本表做强校验。
- Regression test suggestion: monkeypatch 一个迁移函数抛错，断言 `init_db` 或启动 health check 返回失败并阻止业务 CRUD。
- Estimated effort: 0.5 天

### Finding: 广义异常捕获和静默 fallback 过多

- Severity: Medium
- Confidence: High
- Category: Stability / Fallback
- Status: Confirmed
- Affected area: config, database, engine, UI, executors
- Evidence:
  - File: `src/config.py:26`
  - Function / Module: module init
  - Relevant behavior: 创建 `data` / `logs` 目录失败后 `pass`。
  - File: `src/config.py:66`
  - Function / Module: `load_user_config`
  - Relevant behavior: 读取配置异常后返回 `{}`。
  - File: `src/database.py:473`
  - Function / Module: `_wal_checkpoint`
  - Relevant behavior: checkpoint 异常直接 `pass`。
  - File: `src/engine_core/watcher.py:190`
  - Function / Module: `_start_watchdog_observer`
  - Relevant behavior: `ImportError` 时直接回退 mtime 轮询，其他异常 warning 后回退。
  - AST scan: `src/ui/main_window.py` 48 个 broad except，`src/ui/step_editor.py` 24 个，`src/ui/step_table/panel.py` 21 个，`src/engine.py` 19 个。
- Problem: 宽泛捕获本身不是错误，但当前有多处空 catch 或弱提示，会把配置、I/O、schema、UI 状态刷新和 COM 清理问题隐藏到后续行为里。
- Why it matters: 桌面自动化工具的失败多来自环境、权限、路径和外部进程。吞掉这些错误会显著增加排障成本。
- Realistic failure scenario: 日志目录创建失败，配置加载失败被静默替换为默认值，用户看到的是通知/历史缺失，而不是根因权限错误。
- Minimal fix: 把静默 catch 分级：启动关键路径 fail-fast；可降级路径必须 warning + UI 状态提示；清理路径保留 debug 但记录上下文。
- Better long-term fix: 引入统一错误策略表和 `Result`/diagnostic 对象，让 UI、CLI、engine 对同类错误使用一致处理。
- Regression test suggestion: 对 `load_user_config`、目录创建、watchdog fallback、WAL checkpoint 分别注入异常，断言日志级别和用户可见状态符合策略。
- Estimated effort: 1-2 天

### Finding: 核心模块过大且职责混杂

- Severity: Medium
- Confidence: High
- Category: Maintainability / Design
- Status: Confirmed
- Affected area: UI, engine, database
- Evidence:
  - File: `src/ui/main_window.py`
  - Function / Module: `MainWindow`
  - Relevant behavior: 文件 2093 行，类 2040 行，`_setup_ui` 313 行，`_apply_theme` 261 行，`_on_run_requested` 114 行。
  - File: `src/database.py`
  - Function / Module: module
  - Relevant behavior: 文件 1943 行，`import_from_json` 184 行，`export_to_json` 113 行。
  - File: `src/engine.py`
  - Function / Module: `WorkflowEngine`
  - Relevant behavior: 类 1411 行，`_run` 225 行，`_execute_single_step` 188 行。
  - File: `src/ui/step_table/panel.py`
  - Function / Module: `StepTablePanel`
  - Relevant behavior: 类 1774 行，`load_steps` 210 行。
- Problem: 大类长期承载多个变化原因，导致小需求也容易碰到运行、UI、持久化、主题和状态同步的共享区域。
- Why it matters: 项目现在已经有稳定业务逻辑，后续改阶段卡片、运行状态、导入导出或通知时，回归面会被大类放大。
- Realistic failure scenario: 修改 `MainWindow` 的运行按钮状态时无意影响日志面板或看板刷新；修改 `database.py` 导入逻辑时影响 clone/schema/version 逻辑。
- Minimal fix: 从最热路径开始做小提取：CLI history formatter、webhook import/export policy、engine run context、workbench progress state，不做一次性重写。
- Better long-term fix: 按边界拆分 `database` repository/service、engine scheduler/execution context、UI controller/view model，逐步把大类降到单一职责。
- Regression test suggestion: 每次提取前锁定现有行为测试，例如 run lifecycle、clone dependencies、import/export roundtrip、UI selection state。
- Estimated effort: 分阶段 3-10 天

### Finding: 类型边界和配置更新接口过宽

- Severity: Medium
- Confidence: High
- Category: Type Safety / Maintainability
- Status: Confirmed
- Affected area: database CRUD, engine, notifier, executors
- Evidence:
  - File: `src/engine.py:467`
  - Function / Module: `run`
  - Relevant behavior: 参数数量 10。
  - File: `src/engine.py:534`
  - Function / Module: `_run`
  - Relevant behavior: 参数数量 11，函数 225 行。
  - File: `src/notifier.py:170`
  - Function / Module: `send_workflow_notification`
  - Relevant behavior: 参数数量 13。
  - File: `src/database.py`
  - Function / Module: `update_workflow`, `update_step`, `update_stage` 等
  - Relevant behavior: 多处以 `**kwargs` 和 `hasattr` 更新 ORM 字段，未知字段通常不会强失败。
- Problem: 参数过宽、字符串状态、JSON 字符串字段和动态 kwargs 让错误很晚才暴露，IDE/type checker 也难以提供保护。
- Why it matters: 工作流配置是长期数据。字段名拼错、状态值拼错、JSON shape 漂移都可能在运行时才暴露。
- Realistic failure scenario: 调用 `update_step(..., timeout_second=30)` 拼错字段，函数静默忽略，用户以为超时已设置，实际运行无限等待。
- Minimal fix: 对核心更新函数增加允许字段白名单和未知字段报错；为 run/notifier 参数引入 dataclass config。
- Better long-term fix: 引入 typed DTO/schema，状态值改为 `Literal`/Enum，JSON 字段在边界解析为结构化对象。
- Regression test suggestion: 对 `update_step` 传入未知字段，断言抛出明确异常；对 run config dataclass 做默认值和序列化测试。
- Estimated effort: 1-3 天

### Finding: 依赖清单与代码/打包配置漂移

- Severity: Medium
- Confidence: High
- Category: Release / Dependency Weight
- Status: Confirmed
- Affected area: requirements and PyInstaller specs
- Evidence:
  - File: `requirements.txt:4`
  - Function / Module: dependency manifest
  - Relevant behavior: 使用 lower-bound spec，例如 `PySide6>=6.6.0`、`SQLAlchemy>=2.0.0`，没有锁定版本。
  - File: `requirements.txt:19`
  - Function / Module: dependency manifest
  - Relevant behavior: 声明 `networkx>=3.0`。
  - File: `src/engine_core/watcher.py:193`
  - Function / Module: `_start_watchdog_observer`
  - Relevant behavior: optional import `watchdog`。
  - File: `src/executors/powerbi_executor.py:31`
  - Function / Module: `_terminate_process_tree` / Power BI cleanup
  - Relevant behavior: optional import `psutil`。
  - File: `build.spec`
  - Function / Module: hiddenimports
  - Relevant behavior: hiddenimports 包含 `watchdog`，excludes 包含 `networkx`。
- Problem: 安装依赖、运行环境和打包环境三者没有同一事实来源。某些功能在开发机可用，在新机器或打包环境可能降级或失败。
- Why it matters: 这类工具高度依赖 Windows 本机环境，可复现安装比普通库项目更重要。
- Realistic failure scenario: 新机器按 `requirements.txt` 安装后没有 `watchdog`，文件监听静默退回 mtime；Power BI 终止进程树缺 `psutil` 导致清理能力弱化。
- Minimal fix: 明确 optional dependencies：`watchdog`、`psutil` 要么加入 requirements，要么在 UI/日志中声明功能降级；删除未用 `networkx` 或恢复实际使用。
- Better long-term fix: 使用 lockfile 和分组依赖，例如 runtime、dev、build；PyInstaller spec 从同一依赖配置生成/校验。
- Regression test suggestion: 增加依赖一致性测试，扫描 optional imports、hiddenimports、requirements 的差异并输出人工确认清单。
- Estimated effort: 0.5-1 天

### Finding: 缺少 CI、锁文件和静态检查 gate

- Severity: Medium
- Confidence: High
- Category: Release / Testing
- Status: Confirmed
- Affected area: project tooling
- Evidence:
  - File: project root
  - Function / Module: tooling
  - Relevant behavior: 未发现 `.github`、`pyproject.toml`、`ruff.toml`、`mypy.ini`、lockfile 或 release workflow。
  - File: `pytest.ini:1`
  - Function / Module: pytest config
  - Relevant behavior: 当前只有 pytest 配置入口，未见覆盖率或静态检查配置。
- Problem: 本地测试虽然通过，但没有自动化 gate 保证不同机器、不同 Python/PySide6/SQLAlchemy 版本和打包过程稳定。
- Why it matters: 桌面应用问题常在用户机器暴露；缺 CI 和锁文件会让“我这里能跑”变成主要质量标准。
- Realistic failure scenario: PySide6 或 SQLAlchemy 发布新 minor 后满足 `>=`，新环境安装到不兼容版本，GUI 或 ORM 行为变化，发布前没有自动发现。
- Minimal fix: 增加最小 CI：Python 3.10/3.11 Windows pytest、compileall、ruff basic；生成 pinned runtime lock。
- Better long-term fix: 加入 PyInstaller smoke build、CLI command smoke、离线安装验证和 release artifact checksum。
- Regression test suggestion: CI workflow 中固定运行 `python -m compileall src`、`pytest -q`、`python src/cli.py --help`。
- Estimated effort: 0.5-2 天

### Finding: 测试覆盖真实但关键路径缺口仍明显

- Severity: Medium
- Confidence: High
- Category: Testing / Testing Authenticity
- Status: Confirmed
- Affected area: tests
- Evidence:
  - Command: `pytest -q`
  - Relevant behavior: `69 passed in 5.98s`。
  - File: `tests/test_schema_guards.py:95`
  - Function / Module: `test_clone_workflow_remaps_dependencies_to_later_steps`
  - Relevant behavior: 有价值地覆盖 `clone_workflow` 依赖 UID 重映射。
  - File: `tests/test_workflow_watch_config.py:22`
  - Function / Module: module skip marker
  - Relevant behavior: 依赖本地 `workflows_export.json` 和 `data/workflows.db`，缺失时 skip。
  - File: `src/cli.py:580`
  - Function / Module: `cmd_history`
  - Relevant behavior: detail 崩溃路径当前未被测试捕获。
- Problem: 测试不是空壳，但覆盖偏向引擎和 schema，CLI、打包、安全导出、关键 UI 交互和错误路径不足。
- Why it matters: 当前最明确的崩溃就是测试缺口暴露出的 CLI detail；发布链路和 UI 交互也容易出现类似盲点。
- Realistic failure scenario: 修改 StepLog 模型后 CLI detail 崩溃未被发现；发布 exe 后 hiddenimports 问题在用户机器出现。
- Minimal fix: 补 CLI detail 回归、webhook export 脱敏测试、workbench stage keyboard/progress 测试、PyInstaller spec import smoke。
- Better long-term fix: 引入测试分层：unit、integration、local-fixture、Windows-only、manual smoke，并在 CI 中明确哪些必须通过。
- Regression test suggestion: 为每个 bug fix 先写最小复现测试；本地数据依赖测试改为生成临时 fixture 或标为 manual/local。
- Estimated effort: 1-2 天

### Finding: 旧 `copy_workflow` 复制依赖 UID 不重映射

- Severity: Medium
- Confidence: High
- Category: Maintainability / Stability
- Status: Confirmed
- Affected area: database legacy workflow copy
- Evidence:
  - File: `src/database.py:785`
  - Function / Module: `copy_workflow`
  - Relevant behavior: 创建新步骤时生成新 `uid`。
  - File: `src/database.py:850`
  - Function / Module: `copy_workflow`
  - Relevant behavior: `depends_on=step.depends_on` 直接复制旧依赖。
  - File: `src/database.py:1740`
  - Function / Module: `clone_workflow`
  - Relevant behavior: 新实现会建立 `old_to_new_uid` 并重映射依赖。
  - File: `src/ui/workflow_list.py:285`
  - Function / Module: `_copy_workflow`
  - Relevant behavior: UI 当前调用的是 `clone_workflow`。
- Problem: `copy_workflow` 是保留的旧函数，行为与当前正确实现不一致。如果未来被重新使用，会复制出依赖源工作流步骤 UID 的错误工作流。
- Why it matters: 遗留函数会误导维护者，且名称比 `clone_workflow` 更直观，存在被调用的风险。
- Realistic failure scenario: 新 CLI 或脚本调用 `copy_workflow`，复制后步骤 A 依赖旧工作流的步骤 B UID，调度时依赖缺失或跨工作流引用。
- Minimal fix: 删除 `copy_workflow`，或改成调用 `clone_workflow` 并保留兼容包装。
- Better long-term fix: 统一 workflow duplication API，所有克隆路径只保留一个实现和一套测试。
- Regression test suggestion: 如果保留 `copy_workflow`，复用 `test_clone_workflow_remaps_dependencies_to_later_steps` 的场景断言依赖重映射。
- Estimated effort: 30-60 分钟

### Finding: 缺失脚本路径允许保存

- Severity: Low
- Confidence: High
- Category: Stability / UX
- Status: Confirmed
- Affected area: step editor validation
- Evidence:
  - File: `src/ui/step_editor.py:1218`
  - Function / Module: validation before save
  - Relevant behavior: 脚本路径不存在时只显示 warning，仍继续保存配置。
- Problem: 非阻塞保存适合跨机器同步场景，但没有强提示状态或显式用户确认，会让明显不可运行的配置进入数据库。
- Why it matters: 运行失败被延后到 engine/executor，排查链路变长。
- Realistic failure scenario: 用户路径输错一个字符，编辑器提示后误点继续，之后定时/监听触发运行才失败。
- Minimal fix: 将 warning 改为明确确认对话框，或保存后在步骤卡片/表格显示“路径缺失”状态。
- Better long-term fix: 建立 step validation service，区分 error、warning、portable-warning，并让 UI/CLI 复用。
- Regression test suggestion: 构造不存在路径保存，断言需要确认或保存后 validation status 为 warning。
- Estimated effort: 0.5 天

### Finding: `_import_and_run.py` 含硬编码 OneDrive 路径

- Severity: Low
- Confidence: High
- Category: Release / Code Consistency
- Status: Confirmed
- Affected area: helper script
- Evidence:
  - File: `_import_and_run.py:38`
  - Function / Module: module constant
  - Relevant behavior: `WORKFLOWS_JSON = Path(r"D:\OneDrive - PowerBI学谦\Data Analysis\workflows_export.json")`。
- Problem: 该脚本绑定当前个人目录，离开这台机器或目录结构就不能运行。
- Why it matters: 项目里存在可执行脚本时，维护者会默认它是可复用入口。
- Realistic failure scenario: 同事按 README 或脚本注释运行 import，直接因为路径不存在失败。
- Minimal fix: 改为 CLI 参数 `--workflows-json`，默认使用项目根目录 `workflows_export.json`。
- Better long-term fix: 把脚本功能并入正式 CLI，去掉一次性辅助脚本。
- Regression test suggestion: 调用脚本 parser，断言可通过参数设置导入路径，默认值不含个人绝对路径。
- Estimated effort: 30-60 分钟

### Finding: README 与代码状态漂移

- Severity: Low
- Confidence: High
- Category: Comment Coverage / Release
- Status: Confirmed
- Affected area: README and dependency comments
- Evidence:
  - File: `README.md:150`
  - Function / Module: project tree
  - Relevant behavior: 列出 `_tmp_check.py`，当前根目录未发现该文件。
  - File: `requirements.txt:18`
  - Function / Module: dependency comment
  - Relevant behavior: 注释写 `DAG 可视化辅助`，并声明 `networkx>=3.0`；当前代码扫描未发现 `networkx` import。
- Problem: 文档和依赖注释已经不能稳定反映当前项目状态。
- Why it matters: 文档漂移会影响新维护者判断入口、依赖用途和发布准备程度。
- Realistic failure scenario: 维护者为 `_tmp_check.py` 或 `networkx` 追踪不存在的路径，浪费排查时间；或者删除依赖时担心破坏未知功能。
- Minimal fix: 更新 README 目录树和依赖说明，删除或解释 `networkx`。
- Better long-term fix: 用脚本生成基础目录树/依赖使用报告，减少手工漂移。
- Regression test suggestion: 增加文档 lint 或轻量脚本，检查 README 中列出的根文件是否存在。
- Estimated effort: 30 分钟

### Finding: 阶段看板缺少进度与键盘切换

- Severity: Low
- Confidence: High
- Category: Frontend State / UX
- Status: Confirmed
- Affected area: `WorkbenchBoardPanel`, `StageLane`
- Evidence:
  - File: `src/ui/workbench_board.py:205`
  - Function / Module: `StageLane`
  - Relevant behavior: 阶段泳道只有 header、卡片列表、count label 和 click selection。
  - File: `src/ui/workbench_board.py:661`
  - Function / Module: `select_stage`
  - Relevant behavior: 点选阶段只更新 `_selected_stage_uid`、样式和 signal。
  - File: `src/ui/workbench_board.py:700`
  - Function / Module: `reset_all_status` / `highlight_step`
  - Relevant behavior: 更新卡片状态，但未汇总成阶段进度。
- Problem: 用户无法在阶段层面快速判断完成比例，也不能在选中阶段后用键盘快速切换。
- Why it matters: 工作流阶段多时，阶段级导航和进度是高频扫描信息。
- Realistic failure scenario: 工作流运行中用户需要查看相邻阶段进展，只能靠鼠标点选和逐张卡片识别。
- Minimal fix: 在 `StageLane` 下方增加细进度条，`WorkbenchBoardPanel` 增加左右键阶段切换；点击阶段后设置 focus。
- Better long-term fix: 把阶段状态汇总为 view model，统一供看板、表格和 DAG 使用。
- Regression test suggestion: Qt 测试中选中中间阶段，发送 Left/Right key，断言 `selected_stage_uid` 改变；设置卡片状态后断言 lane progress 值更新。
- Estimated effort: 0.5-1 天

### Finding: 配置加载失败静默回到默认值

- Severity: Low
- Confidence: High
- Category: Stability / Fallback
- Status: Confirmed
- Affected area: config
- Evidence:
  - File: `src/config.py:66`
  - Function / Module: `load_user_config`
  - Relevant behavior: `CONFIG_PATH` 存在但读取或 JSON 解析异常时直接 `pass`，返回 `{}`。
- Problem: 用户配置损坏、编码错误或权限错误时，应用看起来正常启动，但实际配置已回到默认值。
- Why it matters: 这会影响通知、并行参数、冷却时间等行为，用户不一定能立即发现。
- Realistic failure scenario: `config.json` 被手工编辑成非法 JSON，应用启动后静默禁用通知配置。
- Minimal fix: 捕获具体异常并记录 warning；GUI 启动时显示配置加载失败提示，保留默认值但明确告知。
- Better long-term fix: 配置文件增加 schema/version 和自动备份，损坏时提供恢复入口。
- Regression test suggestion: 写入非法 config json，断言 `load_user_config` 记录 warning 并返回带错误状态的结果。
- Estimated effort: 30-60 分钟

### Finding: 后端 API 审计不适用，但 CLI/data contract 需要补强

- Severity: Info
- Confidence: High
- Category: Backend API / Design
- Status: Confirmed
- Affected area: CLI and data layer contracts
- Evidence:
  - File: project structure
  - Function / Module: whole project
  - Relevant behavior: 未发现 HTTP server、REST/GraphQL endpoint 或网络后端 API。
  - File: `src/cli.py`
  - Function / Module: CLI commands
  - Relevant behavior: CLI 直接依赖 ORM model shape 和 database functions。
- Problem: backend-api 模式在此项目中主要映射为 CLI/data contract，而不是网络 API。
- Why it matters: contract 仍然存在，只是边界从 HTTP 变成 CLI 参数、JSON 导入导出和 ORM CRUD。
- Realistic failure scenario: ORM 字段变更后 GUI 测试通过，但 CLI/detail 或 JSON import/export contract 崩溃。
- Minimal fix: 为 CLI 输出和导入导出 schema 建立稳定 DTO/test fixture。
- Better long-term fix: 把 CLI、GUI、engine 都依赖的 contract 抽到 service 层，避免直接操作 ORM shape。
- Regression test suggestion: CLI command contract tests 覆盖 help、history detail、clone、run dry/smoke；JSON schema fixture 做 roundtrip。
- Estimated effort: 1-2 天

## 5. Security Concerns

| Concern | Severity | Status | Evidence | Action |
|---------|----------|--------|----------|--------|
| Webhook URL 明文导出 | Medium | Confirmed | `src/database.py:1560` | 默认脱敏，显式带密导出需确认 |
| Webhook 明文展示 | Medium | Confirmed | `src/ui/webhook_manager.py:285` | 输入框默认 mask 或仅显示尾部；编辑时可 reveal |
| 导入同名 Webhook 覆盖 URL | Medium | Confirmed | `src/database.py:1377` | 对敏感字段覆盖加确认/策略 |
| 硬编码本机路径 | Low | Confirmed | `_import_and_run.py:38` | 改参数化，避免暴露个人目录结构 |

没有发现硬编码通用 API key、SQL 拼接注入、远程代码执行接口或网络认证缺失问题。主要安全边界是本地密钥和导出文件共享。

## 6. Stability Concerns

| Concern | Severity | Status | Evidence | Action |
|---------|----------|--------|----------|--------|
| CLI detail 崩溃 | High | Confirmed | `src/cli.py:589` | 修属性访问并补测试 |
| schema 迁移失败继续启动 | Medium | Confirmed | `src/database.py:220` | 启动 fail-fast 或进入只读恢复模式 |
| 静默 fallback/empty catch | Medium | Confirmed | AST scan, `src/config.py:26`, `src/database.py:473` | 错误策略分级 |
| 脚本路径不存在仍保存 | Low | Confirmed | `src/ui/step_editor.py:1218` | 改为确认或持久 warning 状态 |

## 7. Performance Concerns

未发现明确的高风险性能瓶颈。当前更现实的性能风险来自可维护性结构：

| Area | Risk | Evidence | Action |
|------|------|----------|--------|
| UI full refresh | 阶段/步骤多时，整板重建可能卡顿 | `src/ui/workbench_board.py:599` 每次 `load_workflow` 清空并重建 | 先保持现状；大规模数据时引入局部刷新 |
| Step table rendering | 表格渲染函数长且样式逻辑重 | `src/ui/step_table/panel.py:458` | 拆 renderer，避免每次重复计算 |
| Engine loop | 调度和执行写在大函数中，难以局部优化 | `src/engine.py:534` | 先补 profiling hook，再优化真实热点 |

建议不要在没有 profiling 证据时提前做性能重写。

## 8. Testing Gaps

| Gap | Severity | Evidence | Suggested test |
|-----|----------|----------|----------------|
| CLI `history --detail` | High | `src/cli.py:580` 未被现有测试捕获 | 临时 DB + step log，断言 detail 输出 |
| Webhook 导出安全 | Medium | `src/database.py:1560` | 默认导出不含完整 URL |
| Migration failure | Medium | `src/database.py:220` | 迁移异常阻止业务启动 |
| Dependency/packaging | Medium | `build.spec`, `requirements.txt` | spec import smoke + dependency consistency |
| Workbench stage UX | Low | `src/ui/workbench_board.py:661` | Left/Right key selection + progress aggregation |
| Local-data test portability | Low | `tests/test_workflow_watch_config.py:22` | 改临时 fixture 或明确 manual/local |

Valuable existing tests：

| Test file | Real confidence |
|-----------|-----------------|
| `tests/test_engine_scheduling.py` | 对 DAG、阶段屏障、循环依赖和跨阶段依赖有真实保护 |
| `tests/test_executor_policies.py` | 对取消、超时、进程树终止、子工作流上下文有真实保护 |
| `tests/test_schema_guards.py` | 对 schema version、导入导出、clone dependency remap 有真实保护 |
| `tests/test_watch_engine.py` / `tests/test_watch_rules.py` | 对文件监听规则有真实保护 |

## 9. Maintainability Concerns

| Concern | Severity | Evidence | Action |
|---------|----------|----------|--------|
| 大类/大文件 | Medium | `MainWindow` 2040 行，`WorkflowEngine` 1411 行，`StepTablePanel` 1774 行 | 按功能切小，不做一次性大重写 |
| database module 混合职责 | Medium | `src/database.py` 1943 行 | 拆 schema/migration、repository、import-export、clone |
| 遗留复制函数 | Medium | `src/database.py:785` vs `src/database.py:1740` | 删除或委托给 `clone_workflow` |
| 样式和 UI 状态散落 | Low | `src/ui/main_window.py:565`, `src/ui/theme.py:193` | 逐步 token 化主题和局部样式 |

## 10. Type Safety Concerns

| Subtype | Severity | Evidence | Action |
|---------|----------|----------|--------|
| WideParameterList | Medium | `src/notifier.py:170`, `src/engine.py:534` | dataclass/options object |
| StringlyTypedStatus | Medium | `status` 字符串在 model/engine/UI 多处传递 | Enum/Literal + formatter |
| DynamicKwargsUpdate | Medium | database update functions | 允许字段白名单，未知字段报错 |
| JSONStringShape | Medium | `args`, `depends_on`, watch folders 等 JSON 字符串 | 边界解析 DTO/schema |
| ORMShapeLeak | Medium | `src/cli.py:589` | CLI view DTO，不直接依赖 ORM 属性 |

## 11. Release Concerns

| Concern | Severity | Evidence | Action |
|---------|----------|----------|--------|
| No CI | Medium | 未发现 `.github` 或等价 workflow | Windows pytest + compileall + CLI smoke |
| No lockfile | Medium | `requirements.txt` 全是 lower-bound | 固定运行时锁 |
| Packaging drift | Medium | `build.spec` hiddenimports 有 `watchdog`，requirements 无 | 依赖一致性校验 |
| Optional imports unclear | Medium | `watchdog`, `psutil` | 加入 requirements 或显式 optional extra |
| Version source manual | Low | `src/config.py:43` | 发布脚本校验版本/文件名/spec |

---

## 12. Principles Compliance

整体评价：项目有清晰领域对象和不少真实测试，说明不是无结构堆砌；但核心模块已经超过合理维护边界，fail-fast 和 contract 设计弱于业务复杂度。

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP) | 5 | Medium | `MainWindow`, `WorkflowEngine`, `database.py`, `StepEditorPanel`, `StepTablePanel` |
| File Size Limit | 8 | Medium | `src/cli.py`, `src/database.py`, `src/engine.py`, `src/ui/*` |
| Fail-Fast | 4 | Medium | migration, config load, directory creation, WAL checkpoint |
| Explicit Contracts | 5 | Medium | CLI output, update kwargs, JSON import/export, executor params, notifier params |
| DRY / Single Source of Truth | 3 | Low | clone/copy workflow, dependency manifest vs spec, theme/style |
| Release Reproducibility | 3 | Medium | requirements, PyInstaller specs, CI absence |

### Principles Respected

| Principle | Evidence |
|-----------|----------|
| Domain modeling | SQLAlchemy models cover workflow、step、stage、history、webhook 等核心实体 |
| Regression testing | 69 tests pass，调度/执行器/schema guard 测试有真实覆盖 |
| Incremental migration | schema version 和 migrations 已存在，说明项目有升级意识 |
| User-facing diagnostics | 部分 UI warning、日志面板、错误摘要已经在做可见化 |
| Compatibility awareness | watcher 对 watchdog 缺失有 mtime 方案，Power BI/COM cleanup 考虑外部进程复杂性 |

---

## 13. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 5 | 2 | 3 | 0 |
| EmptyCatch | 72+ | 35 | 20 | 17 |
| CompatibilityBranch | 3 | 3 | 0 | 0 |
| SilentCorrection | 2 | 1 | 1 | 0 |
| DefensiveGuess | 4 | 2 | 2 | 0 |

说明：数量来自 AST broad-except 扫描和重点路径人工核查；`EmptyCatch` 以全项目 broad except 中 body 仅 `pass` 的位置估计。不是所有 catch 都应删除，COM/UI cleanup 中部分 catch 可以保留，但要补上下文日志或用户可见状态。

| Finding | Fallback subtype | Current behavior | Recommended handling |
|---------|------------------|------------------|----------------------|
| `config.py` 目录创建失败 | EmptyCatch | `pass` | FailFast 或启动 warning |
| `load_user_config` JSON 异常 | SilentFallback | 返回 `{}` | KeepWithAlert，保留默认值但提示 |
| schema migration failure | SilentFallback | log 后继续 | FailFast |
| WAL checkpoint failure | EmptyCatch | `pass` | KeepWithAlert debug + metric/log context |
| watchdog ImportError | CompatibilityBranch | 回退 mtime | KeepWithAlert，UI 显示监听模式 |
| Excel COM cleanup | EmptyCatch | 多处忽略 | KeepWithAlert，debug log with workbook/process context |

## 14. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|---------------|------|--------|
| Engine scheduling | High | 复杂 DAG/stage 规则回归 | Keep |
| Executor policies | High | 超时、取消、子工作流回归 | Keep |
| Schema guards | High | 克隆/导入导出字段漂移 | Keep and extend |
| Watch rules | Medium | 规则计算可靠，但真实 watchdog 依赖环境 | Keep |
| UI logging | Medium | 部分 UI 状态有效，但缺 pytest-qt 广覆盖 | Keep and extend |
| CLI detail | None | 已有崩溃逃逸 | Add |
| Packaging | None | hiddenimports/缺依赖逃逸 | Add smoke |
| Local workflow config | Low | 依赖本地 ignored DB/export | Rewrite as fixture or mark manual |

### Valuable Tests

| Test | Why valuable |
|------|--------------|
| `tests/test_engine_scheduling.py` | 检查真实调度规则，不只是 mock |
| `tests/test_executor_policies.py` | 覆盖进程、取消、超时等高风险运行路径 |
| `tests/test_schema_guards.py` | 捕获 schema/export/clone 兼容性问题 |
| `tests/test_watch_engine.py` | 覆盖监听触发与规则边界 |

### Suspicious Tests

| Test | Concern | Recommendation |
|------|---------|----------------|
| `tests/test_workflow_watch_config.py` | 依赖本地 `workflows_export.json` 和 `data/workflows.db`，缺失即 skip | 用临时 fixture 构造，或明确归入 local/manual |

### Missing Tests

| Missing | Priority |
|---------|----------|
| CLI `history --detail` | High |
| Webhook default export masking | Medium |
| migration failure fail-fast | Medium |
| dependency/spec consistency | Medium |
| stage board progress + keyboard navigation | Low |

---

## 15. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 0 | 0 | 0 | 0 | 0 |
| InputBoundary | 4 | 0 | 0 | 4 | 0 |
| OutputLeak | 2 | 0 | 0 | 2 | 0 |
| BooleanTrap | 3 | 0 | 0 | 1 | 2 |
| StringlyTyped | 5 | 0 | 0 | 4 | 1 |
| ErrorType | 3 | 0 | 0 | 2 | 1 |

重点问题不是 Python 类型注解缺失本身，而是关键边界没有强 contract：CLI 直接读 ORM 属性、database update 接口动态接收字段、状态值和 JSON shape 以字符串在 UI/engine/database 之间传递。

## 16. Frontend State Analysis

### Summary

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 5 | `MainWindow`, `StepEditorPanel`, `StepTablePanel`, `WorkbenchBoardPanel`, `RunHistoryPanel` |
| StateDuplication | 3 | selected workflow/stage/step state across main window and panels |
| PropDrilling | 1 | theme/edit mode propagated manually |
| EffectChain | 2 | engine signals update DAG, workbench, logs, history |
| UIBusinessCoupling | 4 | run request, step validation, workflow clone, import/export |
| DOMasState | 0 | Not applicable to Qt |
| RequestState | 1 | engine run/cancel status |
| RenderPerf | 2 | full board/table rerender |

阶段卡片功能的直接上下文：

| Need | Current state | Implementation target |
|------|---------------|-----------------------|
| 阶段进度条 | `StageLane` 只维护 `_cards` 和 count label | 根据卡片 status 汇总完成数/总数 |
| 左右方向键切换阶段 | `select_stage` 只响应鼠标/signal | panel 获取 focus 后处理 Left/Right |
| 点击后键盘可用 | `StageLane.mouseReleaseEvent` 只 emit selected | click 时 board/panel set focus |

## 17. Backend API Analysis

### Summary

| Subtype | Count | Affected Endpoints |
|---------|-------|-------------------|
| ApiConsistency | 1 | CLI commands and database functions |
| Validation | 3 | JSON import, update kwargs, step editor path |
| Auth | 0 | Not applicable |
| NplusOne | 0 | No evidence found |
| Caching | 1 | schema cache |
| ErrorResponse | 2 | CLI detail, config/migration errors |
| BusinessLogic | 3 | clone/copy, run config, import/export |
| DataFlow | 2 | webhook export, workflow JSON |

项目无 HTTP backend，因此不做 endpoint 级安全/鉴权/N+1 判断。应把 CLI、JSON 文件和 database service 视为实际 API 边界。

## 18. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| `PySide6>=6.6.0` | Healthy but unpinned | Heavy | High | Qt desktop UI | Keep; pin runtime version |
| `SQLAlchemy>=2.0.0` | Healthy but unpinned | Medium | Medium | ORM/SQLite | Keep; pin |
| `pywin32>=306` | Healthy | Medium | Medium | Excel COM | Keep |
| `pywinauto>=0.6.8` | Healthy optional | Medium | Medium | Power BI automation | Keep; mark Windows-only |
| `requests>=2.31.0` | Healthy | Small | Medium | DingTalk webhook | Keep; pin |
| `networkx>=3.0` | Suspected unused in runtime | Medium | Medium | README says DAG helper | Remove if unused |
| `watchdog` | Missing from requirements | Medium | Medium | Event-driven file watching | Add or document optional |
| `psutil` | Missing from requirements | Medium | Medium | Power BI process cleanup | Add or document optional |

---

## 19. Recommended Fix Order

### Fix Immediately

| Issue | Reason | Estimated effort |
|-------|--------|------------------|
| CLI `history --detail` crash | Confirmed user-triggered crash | 30-60 min |
| `copy_workflow` legacy divergence | Small fix removes latent future bug | 30-60 min |

### Fix Before Stable Release

| Issue | Reason | Estimated effort |
|-------|--------|------------------|
| Webhook export masking | Prevent secret leakage via backup/share | 0.5-1 day |
| migration fail-fast | Avoid running on half-upgraded schema | 0.5 day |
| dependency manifest drift | Avoid missing optional runtime features | 0.5-1 day |
| CI + lockfile | Make release reproducible | 1-2 days |
| key test gaps | Prevent known class of regressions | 1-2 days |

### Schedule Later

| Issue | Reason | Estimated effort |
|-------|--------|------------------|
| MainWindow/Engine/database decomposition | Reduces long-term regression risk | staged 3-10 days |
| typed DTO/config objects | Reduces boundary bugs | staged 2-5 days |
| UI state/view model cleanup | Makes board/table/DAG features cheaper | staged 2-5 days |

### Ignore for Now

| Issue | Reason |
|-------|--------|
| Performance rewrite | No profiling evidence for severe bottleneck |
| Full UI redesign | Current request is targeted; avoid broad churn |

## 20. Quick Wins

| Quick win | Impact | Effort |
|-----------|--------|--------|
| Fix CLI detail fields | Removes confirmed crash | 30-60 min |
| Make `copy_workflow` delegate to `clone_workflow` | Removes stale implementation | 30 min |
| Add `watchdog`/`psutil` decision to requirements | Reduces install drift | 30 min |
| Remove or justify `networkx` | Reduces dependency confusion | 30 min |
| Add `python -m compileall src` + `pytest -q` script | Gives repeatable local gate | 30 min |
| Mask webhook URL in default export | Reduces secret leakage | 0.5 day |
| Add workbench stage keyboard navigation | Matches current UX request | 0.5 day |

## 21. Long-term Refactor Plan

| Refactor | Motivation | Approach | Risk | Testing strategy |
|----------|------------|----------|------|------------------|
| Database service split | `database.py` mixes CRUD, migration, import/export, clone | Extract `migration`, `workflow_repository`, `workflow_import_export`, `clone_service` | Medium, many imports | Existing schema/import/clone tests first; add compatibility imports temporarily |
| Engine run context | `_run` and executor calls pass too many params | Introduce `RunContext` and `StepExecutionContext` dataclasses | Medium, executor contracts touched | Executor policy tests + scheduling tests |
| UI controller/view model | `MainWindow` owns too many panel interactions | Move run state, selection state, and notification state into small controllers | Medium, Qt signal regressions | pytest-qt smoke for run request/selection/log update |
| Typed workflow JSON schema | import/export is critical release boundary | Define versioned schema and validation before import | Medium, old exports compatibility | Golden fixture roundtrip + invalid fixture tests |
| Error policy | Broad exceptions are inconsistent | Define fail-fast / alert / debug-cleanup categories | Low-medium | Inject failures and assert logs/UI messages |
