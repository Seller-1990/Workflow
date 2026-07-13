# Fuck My Shit Mountain Audit Report

**Project:** Workflow Manager
**Audit mode:** full
**Date:** 2026-07-13
**Reviewer:** Codex gpt-5.6-sol

---

## 1. Executive Summary

该项目不是失控型代码库。它已经具备较成熟的工程防线：Windows CI、跨平台打包工作流、集中化子进程策略、Webhook 域名与日志脱敏策略、SQLite schema 版本管理、484 项通过的自动化测试，以及风险调用、宽泛异常和模块热点基线守卫。安全边界和运行时清理明显经过多轮有针对性的加固。

当前主要风险集中在稳定发布和长期演进，而不是基础功能正确性。最重要的问题是：数据库迁移会直接修改唯一用户数据库但没有迁移前可恢复快照；tag 触发打包时没有验证 `vX.Y.Z` 与 `APP_VERSION` 一致；macOS 打包路径没有运行完整测试套件；核心 UI、引擎和数据库文件逼近 1000 行；数据库会话为保持 ORM 对象可用而在成功路径长期复用。综合判断：可以继续内部使用和候选发布，但在面向稳定公共发布前应先处理升级恢复与发布元数据一致性。

### Score Dashboard

```text
Security        ████████░░  8.1  A   外部进程和 Webhook 边界较强，但本地 Webhook token 明文存储
Stability       ███████░░░  7.0  A   测试扎实，但数据库迁移缺少自动可恢复快照
Performance     ████████░░  7.6  A   分页、索引和清理策略良好，长生命周期 session 仍有累积风险
Testing         █████████░  8.7  S   484 项通过，包含真实子进程/SQLite/Qt/监听集成测试
Maintainability ██████░░░░  6.2  B   多个 800-983 行热点模块，UI 编排职责仍高度集中
Design          ███████░░░  6.8  B   已拆出 service/core 边界，但类型与会话契约仍偏隐式
Release         ███████░░░  6.9  B   打包自检完善，但 tag/version 和 macOS 测试门禁不足
────────────────────────────────────────────────────────────────────
Overall         ███████░░░  7.3  A
```

每个维度为 0.0-10.0，分数越高越好。

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 1 | 1 | 0 |
| Medium | 6 | 6 | 0 |
| Low | 2 | 2 | 0 |
| Info | 1 | 1 | 0 |
| **Total** | **10** | **10** | **0** |

## 2. Project Map

- 入口：`src/main.py` 提供 GUI、打包后 CLI 转发和 `--self-check`；`src/cli.py` 提供管理与运行命令；`_import_and_run.py` 提供批量导入执行。
- 核心运行：`src/engine.py` 是兼容外观层，主要执行流已下沉到 `src/engine_core/`；执行器位于 `src/executors/`，子进程统一经过 `src/runtime/process_runner.py`。
- UI：`src/ui/main_window.py` 聚合工作流列表、步骤编辑、运行控制、历史、日志和工作台；子面板在 `src/ui/` 与 `src/ui/step_table/`。
- 持久化：SQLite + SQLAlchemy；`src/database.py` 负责引擎、迁移与 facade，CRUD 已部分拆到 `database_*.py`；schema 版本当前为 v8。
- 外部接口：本地脚本、Excel COM、Power BI Desktop/REST、文件系统监听、钉钉 HTTPS Webhook。
- 安全边界：禁用 `shell=True`、argv 列表执行、Webhook 可信域校验、token 日志脱敏、导出默认遮蔽 secret、导入路径风险标记。
- 测试与发布：78 个测试文件，486 项收集、484 通过、2 跳过；Windows CI 执行全量测试，Windows/macOS 打包后执行隔离 self-check 并生成 SHA256。
- 高风险区域：数据库迁移与 session 生命周期、`MainWindow`/`WorkflowEngine`/`PowerBIExecutor`、跨平台打包差异。

## 3. Top Risks

1. **High - 数据库迁移前没有自动快照**：迁移包含去重、重指向和删除；失败会停止启动，但不能自动恢复迁移前数据。
2. **Medium - 发布 tag 与应用版本未强校验**：`v5.0.2` 可打包出 `APP_VERSION=5.0.1` 的产物。
3. **Medium - macOS 发布门禁不运行全量测试**：macOS job 只编译和 self-check，平台条件分支缺少真实 runner 回归。
4. **Medium - 核心模块持续逼近热点阈值**：多个生产文件 800-983 行，改动影响面和审查成本较高。
5. **Medium - 成功路径数据库 session 长期复用**：为避免 detached ORM 对象而不 remove，契约依赖隐式线程清理。
6. **Medium - Webhook token 明文落盘**：默认导出安全，但 SQLite 文件被复制或本机账户被读取时 token 可直接恢复。
7. **Medium - macOS UI 暴露不可用的 Windows 执行器**：Excel/Power BI Desktop 类型仍可选，错误延迟到执行时。
8. **Low - JSON 列解析失败回退为空值**：能保持 UI 可用，但可能掩盖数据库损坏并改变运行语义。
9. **Low - 退出阶段吞掉 shutdown 异常**：关闭失败只被忽略，缺少可诊断证据。
10. **Info - 依赖较重但与产品能力匹配**：PySide6/SQLAlchemy/pywin32 等均有实质用途，没有确认的死依赖。

## 4. Detailed Findings

### Finding: 数据库迁移直接修改用户库，缺少迁移前可恢复快照

- Severity: High
- Confidence: High
- Category: Stability / Release
- Status: Confirmed
- Affected area: SQLite schema migration
- Evidence:
  - File: `src/database.py:237`
  - Function / Module: `_run_pending_migrations`
  - Relevant behavior: 逐版本调用迁移并记录版本；迁移包含 `UPDATE`、`DELETE`、去重和唯一索引建立，但调用前未创建 SQLite backup。
- Problem: 迁移失败会 fail-fast 停止应用，但数据库可能已完成部分独立事务或数据清理；当前 JSON 自动备份默认脱敏且不是数据库级快照，不能完整回滚 schema、历史和 secret。
- Why it matters: 这是单机应用唯一持久化数据源，升级故障可能要求用户手工修库或丢失配置关联。
- Realistic failure scenario: v5 迁移完成 webhook 去重并删除重复记录，后续迁移因磁盘满或锁失败；应用停止启动，用户无法一键回到升级前数据库。
- Minimal fix: 在发现 pending migration 后，先使用 SQLite backup API 生成带 schema 版本和时间戳的数据库快照；快照失败则拒绝迁移。
- Better long-term fix: 为每个迁移定义事务/可逆性元数据，并提供 CLI `db doctor`、`db restore`。
- Regression test suggestion: 构造旧版数据库，让中间迁移故意失败，验证原库可从自动快照完整恢复且版本号未误记。
- Estimated effort: 1-2 days

### Finding: 发布 tag 与 APP_VERSION 没有一致性门禁

- Severity: Medium
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: GitHub Actions packaging
- Evidence:
  - File: `.github/workflows/package.yml:19`
  - Function / Module: tag trigger / Resolve build metadata
  - Relevant behavior: 任意 `v*` tag 触发打包，artifact 版本只读取 `src/config.py`，未比较 `github.ref_name`。
- Problem: Git tag、README/代码版本和产物文件名可能不一致。
- Why it matters: 发布追踪、回滚和用户问题定位会指向不同版本。
- Realistic failure scenario: 推送 `v5.0.2` tag 时忘记更新 `APP_VERSION`，Actions 上传名为 5.0.1 的 artifact 到 5.0.2 发布流程。
- Minimal fix: tag 事件中要求 `github.ref_name == 'v' + APP_VERSION`，不一致立即失败。
- Better long-term fix: 用单一 release 命令生成版本提交、tag 和 changelog。
- Regression test suggestion: 扩展 `tests/test_release_metadata.py` 静态验证 workflow 包含 tag/version 比较逻辑。
- Estimated effort: 1-2 hours

### Finding: macOS 打包路径没有运行完整测试套件

- Severity: Medium
- Confidence: High
- Category: Testing / Release
- Status: Confirmed
- Affected area: macOS Intel package job
- Evidence:
  - File: `.github/workflows/package.yml:158`
  - Function / Module: `package-macos-intel`
  - Relevant behavior: 仅运行依赖/风险/热点检查、`compileall` 和打包后 self-check；没有 `pytest -q`。
  - File: `tests/test_main_self_check.py:12`
  - Relevant behavior: self-check 只覆盖数据目录、CA bundle、数据库初始化和窗口构造。
- Problem: macOS 特有导入、路径、watchdog、Qt 事件和平台条件逻辑只能由很浅的构造检查覆盖。
- Why it matters: Windows 全绿不能证明 macOS 行为，发布 job 可能上传功能受损但能启动的 app。
- Realistic failure scenario: 某个 `sys.platform` 分支或 macOS 文件监听行为回归，窗口仍能构造，artifact 仍被上传。
- Minimal fix: macOS job 在打包前运行适用的 `pytest -q`；明确 marker 跳过 Windows COM 用例。
- Better long-term fix: 建立 Windows/macOS CI 矩阵和平台能力契约测试。
- Regression test suggestion: 增加 workflow guard，断言两个 package job 均运行测试门禁。
- Estimated effort: 0.5-1 day

### Finding: 核心生产模块持续接近 1000 行阈值

- Severity: Medium
- Confidence: High
- Category: Maintainability / Design
- Status: Confirmed
- Affected area: UI、engine、database、CLI
- Evidence:
  - File: `src/ui/main_window.py:29`，983 行/86 个函数
  - File: `src/ui/theme.py:1`，968 行
  - File: `src/engine.py:146`，950 行/62 个函数
  - File: `src/database.py:1`，928 行/44 个函数
  - File: `src/ui/step_editor.py:54`，917 行/52 个函数
  - File: `src/cli.py:1`，833 行
- Problem: 已有拆分工作，但 facade 和 UI 控制器继续承担大量代理、状态协调、生命周期和业务规则。
- Why it matters: 高耦合热点增加冲突、误改和测试选择成本；当前 CI 阈值是 1000 行，更多是在阻止继续恶化而非说明结构健康。
- Realistic failure scenario: 一次运行态或选择同步修改同时影响 MainWindow、engine facade 和多个 controller，局部测试通过但组合行为回归。
- Minimal fix: 把 1000 行硬阈值降到 900，并为新增函数数/复杂度设置预算；优先拆 `MainWindow` 选择协调和 `database.py` migration facade。
- Better long-term fix: 以用例为边界形成 application services，UI 仅持有 view state 和 command dispatch。
- Regression test suggestion: hotspot 守卫同时检查文件行数、单函数长度和类方法数，不允许基线增长。
- Estimated effort: 分阶段 3-10 days

### Finding: 数据库 session 成功路径不释放，返回 ORM 对象依赖隐式生命周期

- Severity: Medium
- Confidence: High
- Category: Stability / Performance / Design
- Status: Confirmed
- Affected area: SQLAlchemy session management
- Evidence:
  - File: `src/database.py:635`
  - Function / Module: `get_session`
  - Relevant behavior: 成功路径不调用 `scoped_session.remove()`，以保证返回 ORM 对象不 detached；清理由 worker 显式调用 `cleanup_session()`。
- Problem: 数据访问层把持久化对象直接泄露给 UI/engine，迫使 session 跨多个调用长期存在；遗漏 cleanup 时 identity map、事务状态和连接占用难以推断。
- Why it matters: 长时间 GUI 会话与后台线程较多，隐式 session 所有权会放大陈旧数据和资源累积风险。
- Realistic failure scenario: 新增后台线程查询后忘记调用 cleanup；线程池复用线程时沿用旧 session，读取陈旧对象或持有连接更久。
- Minimal fix: 为所有线程入口建立统一 `try/finally cleanup_session()` 模板和守卫测试，记录活跃 session 诊断信息。
- Better long-term fix: repository 返回不可变 DTO，session 在 repository 方法内结束；写操作显式 Unit of Work。
- Regression test suggestion: 重复在线程池执行数据库读写，断言每个任务结束后 registry 无 session、连接池 checked-out 为 0。
- Estimated effort: 最小 1 day；结构修复 1-2 weeks

### Finding: Webhook access_token 以明文存入 SQLite

- Severity: Medium
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Notification secret storage
- Evidence:
  - File: `src/models.py:372`
  - Function / Module: `WebhookConfig.webhook_url`
  - Relevant behavior: 完整 URL 作为 `Text` 明文持久化；导出默认脱敏，但本地数据库未加密。
- Problem: 应用级日志和导出保护不能覆盖数据库文件复制、云盘同步、备份软件或同账户恶意进程读取。
- Why it matters: access_token 可用于向组织机器人发送消息，泄露后需轮换机器人凭据。
- Realistic failure scenario: 用户将 `%LOCALAPPDATA%/工作流管理/data/workflows.db` 连同故障包发给他人，token 可直接从表中读取。
- Minimal fix: 文档明确数据库包含 secret，并在“导出诊断包”中排除 DB；提供一键 token 轮换提示。
- Better long-term fix: Windows Credential Manager/macOS Keychain 存储 secret，数据库仅保存 credential reference；迁移旧明文值。
- Regression test suggestion: 验证新建 webhook 后数据库中不存在 `access_token=`，且 keychain mock 能恢复完整 URL。
- Estimated effort: 2-4 days

### Finding: macOS UI 仍展示不可用的 Windows Desktop 执行器

- Severity: Medium
- Confidence: High
- Category: Maintainability / Frontend State / Release
- Status: Confirmed
- Affected area: Step editor capability model
- Evidence:
  - File: `src/config.py:115`
  - Function / Module: `StepType.choices`
  - File: `src/ui/step_editor_build.py:182`
  - Relevant behavior: 下拉框无条件显示 Python、Excel、Power BI、子工作流；Excel 运行时才导入 `win32com`。
- Problem: 平台能力没有在 UI 和执行器注册层显式建模。
- Why it matters: macOS 是正式打包目标，用户可创建当前平台必然失败的步骤。
- Realistic failure scenario: macOS 用户配置 Excel 刷新，保存成功，运行后才得到“缺少 pywin32”。
- Minimal fix: 执行器注册元数据增加 `supported_platforms`，UI 禁用并解释不可用类型。
- Better long-term fix: capability service 统一驱动 UI、CLI validate、导入告警和运行前检查。
- Regression test suggestion: monkeypatch `sys.platform='darwin'`，断言 Windows-only 类型不可新建但已有配置仍可查看。
- Estimated effort: 1 day

### Finding: JSON 配置字段损坏时静默回退为空语义

- Severity: Low
- Confidence: High
- Category: Stability / Type Safety / Fallback
- Status: Confirmed
- Affected area: ORM JSON text fields
- Evidence:
  - File: `src/models.py:84`
  - Function / Module: `get_notify_config`, `get_watch_folders`, `get_single_args`, `Step.get_args` 等
  - Relevant behavior: `JSONDecodeError` 记录 warning 后返回 `{}` 或 `[]`。
- Problem: 读取损坏数据后继续运行，会把“数据损坏”解释为“用户未配置”。
- Why it matters: 通知、监听、参数或依赖可能被悄然禁用，用户看到的是功能行为变化而不是明确修复指引。
- Realistic failure scenario: `depends_on` JSON 被截断，步骤被视为无依赖并提前并行运行。
- Minimal fix: 对影响执行语义的字段抛出专用 `CorruptConfigurationError`；UI 只读展示并提供修复/重置按钮。
- Better long-term fix: 使用结构化列或带 schema 的配置 value object，在写入边界验证。
- Regression test suggestion: 注入损坏 `depends_on`，断言运行预检失败而不是返回空依赖。
- Estimated effort: 1-2 days

### Finding: 主窗口退出时吞掉 engine shutdown 异常

- Severity: Low
- Confidence: High
- Category: Stability / Observability / Fallback
- Status: Confirmed
- Affected area: GUI shutdown
- Evidence:
  - File: `src/ui/main_window.py:945`
  - Function / Module: `closeEvent`
  - Relevant behavior: `engine.shutdown()` 的任意异常被 `except Exception: pass` 忽略，随后接受关闭事件。
- Problem: watcher、执行线程或资源清理失败没有日志或用户提示。
- Why it matters: 偶发孤儿进程、文件锁或未完成清理难以定位。
- Realistic failure scenario: watcher observer 关闭失败，窗口退出但后台进程仍存活；下次启动遇到锁问题，日志中没有根因。
- Minimal fix: `logger.exception` 并记录 shutdown_wait、活跃线程和 watcher 状态；必要时提示退出不完整。
- Better long-term fix: shutdown 返回结构化结果，UI 根据未关闭资源决定重试、强制退出或取消。
- Regression test suggestion: 让 `engine.shutdown` 抛错，断言日志包含异常和资源状态。
- Estimated effort: 1-2 hours

### Finding: 直接依赖均有实质用途，未发现确认的死依赖

- Severity: Info
- Confidence: High
- Category: Performance / Release
- Status: Confirmed
- Affected area: Dependency manifest
- Evidence:
  - File: `requirements.txt:1`
  - Relevant behavior: PySide6、SQLAlchemy、pywin32、pywinauto、watchdog、psutil、requests、certifi、qtawesome 均有对应代码调用。
- Problem: 无确认问题。PySide6 体积大，但它承载完整桌面 UI；Windows 自动化依赖通过平台 marker 隔离。
- Why it matters: 不应为“减依赖数量”而重写成熟能力。
- Realistic failure scenario: 不适用。
- Minimal fix: 保持 release/CI 精确 pin 和 requirements 一致性守卫。
- Better long-term fix: 记录季度依赖升级与 CVE 检查，而不是临时升级。
- Regression test suggestion: 保留 `test_dependency_manifest.py` 和 `check_requirements_consistency.py`。
- Estimated effort: none

## 5. Security Concerns

做得较好：运行时禁止 `shell=True`，参数必须为 argv；Webhook 只允许可信 HTTPS 域名；通知错误和运行参数均脱敏；普通导出/备份默认不包含 secret；Power BI token 来自环境变量且不记录。

待改进：本地 Webhook secret 明文存储；仓库未发现依赖漏洞扫描工作流。后者建议加入 `pip-audit` 或 Dependabot，但本次未在线核验当前锁定版本 CVE，因此不作为确认漏洞计数。

## 6. Stability Concerns

主要风险是升级恢复能力和隐式 session 生命周期。迁移本身会 fail-fast、按版本记录，且大量迁移测试通过，这是优点；但 fail-fast 不等于可恢复。执行器对取消、超时、进程树清理和日志落盘覆盖较完整。

## 7. Performance Concerns

- 运行历史使用 limit/offset 分页并有组合索引。
- 日志有保留期和异步清理。
- DAG 并行度有限制，文件监听有 cooldown/settle。
- 风险集中在长期 `scoped_session` 和高耦合 UI 刷新，而不是已确认的热路径瓶颈。
- 未执行基准测试或 profiler，因此不对启动时间、超大工作流和内存峰值做无证据结论。

## 8. Testing Gaps

测试真实性整体高：真实 SQLite migration、CLI 子进程、Qt offscreen、watchdog observer、线程取消、运行历史分页、导入导出和打包 self-check 均有覆盖。测试不是单纯 mock 绿灯。

关键缺口：迁移失败后的数据库恢复、长生命周期 session/连接池释放、macOS 全套测试、真实 Excel/Power BI Desktop 自动化仍无法在普通 CI 中验证。

## 9. Maintainability Concerns

代码已从单体 `engine.py`、`database.py` 和 UI 中拆出多个 core/service/controller，这是积极趋势。但 facade 仍然大，模块间存在较多代理方法和共享可变状态。下一阶段应减少“继续加 helper 到大类”的做法，按用例迁移状态所有权。

## 10. Type Safety Concerns

项目使用 SQLAlchemy `Mapped`、dataclass 和部分 `Optional` 标注，但没有 mypy/pyright 门禁。主要弱点是字符串化 JSON 列、字符串状态码、动态 Qt 属性和大量 `Callable`/`object` 边界。建议先对纯逻辑模块启用渐进式 pyright/mypy，不要一次覆盖 Qt UI 全仓库。

## 11. Release Concerns

Windows 发布路径较强：依赖锁定、质量守卫、clean tree、PyInstaller、隔离 self-check、SHA256。发布前阻塞项是 tag/version 一致性和迁移快照。macOS job 需要补全测试门禁，并在产品文档中明确平台功能矩阵。

---

## 12. Principles Compliance

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility | 5 | Medium | MainWindow, WorkflowEngine, database facade, StepEditor, CLI |
| File Size Limit | 6 | Medium | 800-983 行核心文件 |
| Fail-Fast | 1 | Low | 损坏 JSON 配置回退空值 |
| Explicit Ownership | 1 | Medium | scoped_session 生命周期 |
| Type Safety | 2 | Low | JSON Text、字符串状态/动态边界 |
| Observability | 1 | Low | shutdown 异常吞掉 |

### Principles Respected

- 子进程、Webhook URL、结果策略、阶段变更等关键策略已集中化。
- 外部 I/O 大多有 timeout、取消和明确错误传播。
- 导入数据有 schema 验证，SQL 使用参数化语句。
- 高风险修改配有回归测试和 CI 守卫。
- 没有为了抽象而引入大型框架，依赖与实际能力匹配。

---

## 13. Fallback / Defensive Code Analysis

### Fallback Summary

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 2 | 1 | 1 | 0 |
| EmptyCatch | 1 | 0 | 0 | 1 |
| CompatibilityBranch | 3 | 3 | 0 | 0 |
| SilentCorrection | 1 | 1 | 0 | 0 |
| DefensiveGuess | 1 | 0 | 1 | 0 |

- 保留：图标降级、控制台附加失败、旧 schema cache 格式兼容、watch 配置自动修复；这些路径应有日志或 UI 提示。
- Fail-fast：执行语义相关 JSON 损坏、数据库迁移前快照失败。
- 移除：`MainWindow.closeEvent` 对 shutdown 的空 catch，替换为结构化日志。

## 14. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | Risk | Action |
|-----------|-----------------|------|--------|
| SQLite schema/CRUD | High | 缺迁移恢复演练 | Keep + add recovery test |
| Engine scheduling/cancel | High | 极端长跑资源累积 | Keep |
| CLI/import/export | High | 打包 exe CLI 只做 smoke | Keep |
| Qt UI state | Medium-High | offscreen 与真实窗口管理器差异 | Keep |
| File watching | High | 平台差异仍存在 | Keep |
| Excel/Power BI Desktop | Medium-Low | COM/UI automation 难在 CI 真实执行 | Add manual release matrix |
| macOS package | Low-Medium | 仅 self-check | Add full pytest |

### Valuable Tests

- schema 迁移、唯一约束与数据重指向测试
- 真实 CLI subprocess 测试
- watchdog observer 集成测试
- Qt 选择同步、关闭和运行生命周期测试
- 子进程清理、超时和取消测试

### Suspicious Tests

未发现系统性“只测 mock 调用次数”的假覆盖。部分大型 UI 测试使用 `SimpleNamespace` 和 monkeypatch，但同时存在 offscreen 构造与真实事件测试，风险可接受。

### Missing Tests

- migration 前快照与失败恢复
- session registry/连接池长期释放
- macOS runner 全量测试
- tag/version 不一致发布失败
- secret 从明文 DB 迁移到系统凭据库

---

## 15. Type Safety Analysis

### Summary

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 0 | 0 | 0 | 0 | 0 |
| InputBoundary | 1 | 0 | 0 | 0 | 1 |
| OutputLeak | 1 | 0 | 0 | 1 | 0 |
| BooleanTrap | 0 | 0 | 0 | 0 | 0 |
| StringlyTyped | 2 | 0 | 0 | 0 | 2 |
| ErrorType | 1 | 0 | 0 | 0 | 1 |

重点不是 Python “不够静态”，而是 ORM 对象/session 共同泄露和 JSON 文本列失败语义不明确。适合从 `engine_core`、`database_*`、`runtime` 纯逻辑模块渐进启用检查。

## 16. Frontend State Analysis

### Summary

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 4 | MainWindow, StepEditorPanel, StepTablePanel, WorkbenchBoard |
| StateDuplication | 1 | table/board/editor selection coordination |
| PropDrilling | 0 | - |
| EffectChain | 1 | workflow/step selection reload chain |
| UIBusinessCoupling | 2 | MainWindow, WorkflowConfigPanel |
| DOMasState | 0 | - |
| RequestState | 1 | webhook background test thread |
| RenderPerf | 0 | 无确认瓶颈 |

UI 有明确 controller 拆分和大量状态回归测试，因此不是无序状态管理；问题是 `MainWindow` 仍是过大的协调中心，选择状态在 table、board、editor 间同步成本高。

## 17. Backend API Analysis

本项目没有网络服务端 API，本节按本地 CLI/数据库 facade 评估。

| Subtype | Count | Affected Endpoints |
|---------|-------|-------------------|
| ApiConsistency | 1 | database facade 返回 ORM 对象 |
| Validation | 1 | JSON Text 读取边界 |
| Auth | 0 | 不适用，本地桌面应用 |
| NplusOne | 0 | 未确认；关键查询已有 eager load/聚合 |
| Caching | 0 | schema/cycle cache 有显式失效策略 |
| ErrorResponse | 1 | CLI 部分路径使用 `sys.exit` |
| BusinessLogic | 1 | MainWindow/CLI orchestration |
| DataFlow | 1 | session ownership |

## 18. Dependency Weight Analysis

### Dependency Scoreboard

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| PySide6 6.10.1 | Healthy | Heavy | High | 完整桌面 UI | Keep |
| SQLAlchemy 2.0.46 | Healthy | Medium | Low | ORM、迁移、查询 | Keep |
| pywin32 311 | Healthy/platform | Medium | Native | Excel COM | Keep |
| pywinauto 0.6.9 | Healthy/platform | Medium | Native | Power BI Desktop UI automation | Keep |
| watchdog 6.0.0 | Healthy | Light | Low | 文件监听 | Keep |
| psutil 7.2.2 | Healthy | Medium | Native | 进程树清理 | Keep |
| requests 2.32.5 | Healthy | Light | Medium | DingTalk/Power BI REST | Keep |
| certifi 2026.1.4 | Healthy | Light | Low | 打包 CA bundle | Keep |
| qtawesome 1.4.2 | Healthy | Medium | QtPy/icons | UI 图标体系 | Keep |
| PyInstaller 6.11.1 | Healthy/build | Heavy | High | 发布打包 | Keep, scheduled upgrades |

未发现确认的未使用直接依赖。`requirements-ci.txt` 与 `requirements-release.txt` 精确 pin，并有一致性守卫。当前宿主环境 `pip check` 的 requests 冲突来自 hermes-agent 共享环境，不属于项目锁文件缺陷；建议审计/发布始终使用隔离 venv。

---

## 19. Recommended Fix Order

### Fix Immediately

1. 数据库 pending migration 前创建并验证可恢复 SQLite 快照。

### Fix Before Stable Release

1. 强制 tag 与 `APP_VERSION` 一致。
2. macOS package job 运行适用的全量测试。
3. 明确 macOS 平台能力，禁用 Excel/Power BI Desktop 新建入口。
4. 明确数据库包含 Webhook secret，规划系统凭据库迁移。

### Schedule Later

1. repository 返回 DTO，收紧 session 生命周期。
2. 继续拆分 MainWindow、engine/database facade。
3. 对纯逻辑层启用渐进式类型检查。
4. 增加性能基准：1000 步 DAG、10000 条历史、24 小时 watcher soak。

### Ignore for Now

1. 不为减少依赖而替换 PySide6/SQLAlchemy。
2. 不对所有兼容 fallback 一刀切；保留有日志、有边界的降级路径。

## 20. Quick Wins

- 1-2 小时：tag/version workflow gate。
- 1-2 小时：shutdown 异常改为 `logger.exception`。
- 2-4 小时：macOS workflow 增加 pytest 与静态 guard。
- 2-4 小时：平台能力元数据与 UI 禁用提示。
- 0.5-1 天：新增 migration 快照原型和失败回归测试。

## 21. Long-term Refactor Plan

1. **持久化边界**：先新增 DTO/repository，不一次重写；从 run history 和 webhook 查询开始，逐步消除 detached ORM 需求。风险是 UI 依赖关系属性，需契约测试保护。
2. **应用服务层**：把 workflow selection、run dispatch、save/delete 等用例从 MainWindow/CLI 抽成共享 service。风险是信号时序变化，需保留现有 Qt 生命周期测试。
3. **能力模型**：执行器注册表加入平台、依赖、无人值守能力；UI、CLI、导入校验共用。风险低，适合作为独立迭代。
4. **发布恢复**：形成 version gate、DB snapshot、artifact checksum、restore drill 的完整发布清单；每个发布候选至少执行一次旧库升级测试。
---

## 22. Remediation Status (2026-07-13)

- Fixed: packaged TLS CA resolution now validates and explicitly supplies a usable bundle to DingTalk requests.
- Fixed: schema migrations create a verified SQLite snapshot before the first pending migration.
- Fixed: release tags must match `APP_VERSION`; macOS packaging runs the full test suite.
- Fixed: macOS hides Windows-only desktop automation step types.
- Fixed: corrupted step dependency JSON fails explicitly; shutdown errors are logged; GUI/CLI cleanup session boundaries were added.
- Accepted risk: Webhook access tokens remain stored in SQLite by explicit user decision and are excluded from remediation scoring.
- Deferred structural work: broad decomposition of large core modules remains a scheduled refactor, not part of this release fix.