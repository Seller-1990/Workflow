# 工作流管理系统 (Workflow Manager)

基于 Python + PySide6 的桌面端工作流编排工具，将 Python 脚本、批处理、子工作流等任务串联成自动化工作流，提供可视化管理、阶段分组、DAG 依赖、运行日志追踪、失败重试和安全脱敏的钉钉通知。当前发布版本：6.0.2。

## 6.0.2 更新日志

- **会话模型重构**：SQLAlchemy `expire_on_commit=False` + 会话块退出统一 `close()`，运行对象生命周期语义明确化（detached 只读）；删除会话过期补偿代码（fallback 复制对象 ×2、identity-map 手工 expire 循环），数据库层净减约 30 行
- **进程收尾修复**：CLI Ctrl+C 不再绕过收尾（SIGINT → 协作取消链路，运行历史正确记为 cancelled 而非 failure）；脚本输出读取线程改 daemon，孙进程持管道不再挂死应用退出；POSIX 取消改用进程组 kill（`start_new_session` + `os.killpg`），macOS/Linux 不再残留孤儿脚本进程
- **等待与超时语义**：步骤等待改用 `time.monotonic()`（系统时钟调整不再影响超时）+ 取消事件即时唤醒（取消感知延迟 0.7s → 0.2s）
- **缓存正确性**：删除与数据库脱钩的 schema 迁移缓存（还原旧库后迁移不再被跳过）；删除误解为"跨会话一致性"的 WAL checkpoint；工作流删除路径补环检测缓存失效
- **数据正确性**：并行批次结果按 `step_id` 配对（重复 order 时失败详情不再归因错位）；嵌套子工作流 `parent_run_id` 记录直接父运行（threading.local 链路透传，depth≥2 不再指向根运行）
- **安全与健壮性**：命令行参数脱敏扩展覆盖 `--api-key`/`apikey`/`auth`/`credential`/`private-key` 等命名敏感值；运行线程非 RuntimeError 异常不再静默（windowed 构建下 UI 不再卡 running）
- **质量验证**：本地全量测试 541 passed, 1 skipped；broad-except/risky-calls/hotspot 门禁全绿

## 6.0.1 更新日志

- **主题正确性**：暗色模式下步骤表、看板卡片、mini DAG 节点颜色随主题重建；切主题后按最近一次运行回放步骤状态高亮；应用级 QPalette 同步切换
- **图标修复**：修复 Python 类型图标因无效字形（fa5s.python）始终显示为空的问题（改用 brands 族）；侧栏资产按钮、运行控制面板图标随主题刷新
- **对话框统一**：6 处手工 QMessageBox 迁移至主题化助手，暗色模式不再出现系统浅色弹窗；关闭"运行进行中"弹窗现为安全的「留在当前」
- **打包瘦身**：打包图标改用多帧 ICO（省约 2.4MB）；slim 包裁剪未使用的 qtawesome 字体（约省 5.5MB）
- **代码清理**：删除重复 QSS/死信号/死常量，硬编码颜色 token 化，启动时不再重复刷新全局样式
- **质量验证**：本地全量测试 540 passed, 1 skipped。


## 6.0.0 更新日志

- **功能精简**：移除 Excel/Power BI 执行器与文件监听功能（历史数据保留、类型可诊断展示），减少维护面
- **导入安全强化**：导入含绝对路径/上级目录引用的工作流需显式确认，确认绑定路径集合摘要，路径变更自动失效
- **运行稳定性**：每次运行使用独立线程池，子工作流嵌套深度与并发预算受限，取消响应更快
- **通知可靠性**：打包版运行文件移至应用数据目录，避免系统清理临时目录导致通知失败
- **质量验证**：本地全量测试 529 passed, 1 skipped。


## 核心功能

- **多类型任务编排** — Python 脚本、批处理脚本、子工作流嵌套
- **阶段分组** — 将步骤按用途分组（如"数据导入"→"清洗"→"输出"），支持按阶段运行
- **DAG 依赖** — 步骤间可配置依赖关系，引擎自动拓扑排序、并行执行无依赖步骤
- **钉钉通知** — 运行完成/失败时推送消息，支持自定义模板变量
- **运行历史** — 记录每次运行的步骤状态、耗时、日志，支持重试失败步骤
- **CLI 接口** — 无需打开 GUI，命令行即可运行/管理工作流

## 5.0.7 更新日志

- **新增批处理步骤类型**：支持 `.bat` / `.cmd` 批处理脚本作为工作流步骤执行，通过 `cmd.exe /c` 运行，支持参数传递、日志捕获、超时控制和取消操作。仅 Windows 平台可见。
- **默认超时**：批处理步骤默认超时 3600 秒（1 小时），可在步骤配置中自定义。
- **质量验证**：本地全量测试为 538 passed, 2 skipped。

## 5.0.6 更新日志

- **安全加固**：Power BI REST 异常消息中的 Bearer token 自动脱敏；workspace_id/dataset_id 增加路径遍历防护；导入含绝对路径或上级目录引用的工作流首次运行前需用户确认。
- **稳定性修复**：子进程默认 `stdin=DEVNULL` 防止 `input()` 永挂；force_stop 使用条件 UPDATE 消除与正常终态的竞态覆盖；单步执行异常时保证结构化错误上报（不再只显示"未知错误"）。
- **监听健壮性**：watch_manager 加 RLock 保护并发操作；mtime 扫描支持 stop_event 协作取消，停止响应从 10s 降至 <1s；watchdog observer 部分调度失败时正确清理不再泄露。
- **性能优化**：日志清理增加数量(500个)/容量(500MB)双上限；identity map 精确 expire 避免长期运行内存增长；运行历史表格渲染加 `setUpdatesEnabled` 批量刷新；`clear_run_histories` 改用 subquery 消除大 IN 子句；历史面板同步加载全部替换为异步。
- **通知可靠性**：通知提交前检查 executor 是否已关闭，日志清理改用引擎线程池避免 shutdown 竞态。
- **质量验证**：本地全量测试为 529 passed, 2 skipped。

## 5.0.5 更新日志

- **强制停止修复**：从历史列表停止一条"孤儿"运行记录不再误伤正在运行的其它任务——只在目标是当前活动运行时真正取消引擎，孤儿记录只做数据库终态清理。
- **并行取消修复**：并行批次中途取消时为被取消/未提交的步骤补齐 cancelled 占位，结果与进度不再错位、不再少计（进度不再"停住"）。
- **监听效率**：文件监听（watchdog observer 模式）空闲时不再每冷却周期全树扫描，仅真实文件事件触发扫描。
- **切换工作流提速**：合并切换工作流时步骤/阶段/工作流的重复数据库读取（get_steps_by_workflow 3 次→1 次）。
- **历史加载异步化**：运行完成后的运行历史重载移至后台线程，仅在查询结果就绪后回 GUI 线程渲染，减少主线程卡顿。
- **精简重构**：执行器日志目录引导统一为 `BaseExecutor.build_log_dir()`；运行按钮收敛为统一入口；运行 ID 复用全局唯一 ID。
- **质量验证**：本地全量测试为 529 passed, 2 skipped。

## 5.0.4 更新日志

- **步骤运行参数保存**：步骤可独立保存常用运行参数；无本次覆盖时自动复用，有覆盖时仅替换保存参数层，固定参数始终保留。
- **运行与持久化兼容**：保存参数覆盖完整运行、阶段运行、监听、CLI 和子工作流，并随迁移、复制、克隆、导入导出和版本快照保留。
- **复制链路修复**：步骤复制和工作流克隆会继续保留显式输出路径。
- **质量验证**：本地全量测试为 522 passed, 2 skipped。

## 5.0.3 更新日志

- **运行参数交互优化**：临时运行参数仅在“只运行此步骤”时主动收集；全流程、阶段、从步骤开始、文件监听、重试和子工作流保持直接运行。
- **品牌信息完善**：左侧品牌区增加弱化层级的开发者信息，并优化本次运行参数确认按钮文案。
- **质量验证**：本地全量测试为 501 passed, 2 skipped。

## 5.0.2 更新日志

- **TLS CA 打包修复**：钉钉通知显式解析并校验可用 CA bundle，避免 PyInstaller 临时目录中的 `certifi/cacert.pem` 路径失效。
- **升级恢复加固**：执行数据库 schema 迁移前自动创建并校验 SQLite 快照，保留最近 5 份。
- **发布门禁补强**：发布 tag 必须与 `APP_VERSION` 一致，macOS 打包前运行完整测试套件。
- **平台与稳定性修复**：macOS 隐藏 Windows-only 桌面自动化步骤；损坏的步骤依赖配置会明确阻止执行；退出清理失败写入日志。
- **质量验证**：本地全量测试为 491 passed, 2 skipped。

## 5.0.1 更新日志

- **运行参数弹窗修复**：修复长中文步骤名在“本次运行参数”弹窗中与脚本路径重叠、看起来像乱码的问题。
- **UI 回归覆盖**：新增离屏 Qt 回归测试，覆盖长中文标题换行、不重叠、手动参数和 argparse 参数收集行为。
- **质量守卫补强**：本地全量测试为 484 passed, 2 skipped。

## 5.0.0 更新日志

- **脚本临时参数**：Python 步骤运行前可填写本次运行专用的附加命令行参数，固定参数与临时参数按顺序合并且不写回工作流配置。
- **argparse 静态识别**：应用可读取脚本中的 `argparse` 定义并生成参数填写界面；无法识别时回退到手动命令行参数输入。
- **参数安全与追溯**：运行日志展示实际参数摘要，并对 token、secret、password 和 `access_token=` 等明显敏感参数脱敏。
- **运行链路加固**：临时参数随本次运行上下文显式下传，避免并行步骤和子工作流共享状态污染。
- **质量守卫补强**：新增脚本参数解析、运行入口、运行链路、脱敏和 Windows 路径参数回归测试；本地全量测试为 481 passed, 2 skipped。

## 4.1.3 更新日志

- **删除稳定性优化**：工作流删除改为批量清理关联阶段、步骤、运行历史、步骤日志、版本和最近使用记录，避免 ORM 级联加载大量对象。
- **运行态边界收敛**：新增后台运行适配层，集中处理运行线程生命周期和 Qt queued 日志回传。
- **运行历史性能优化**：分页加载更多时只汇总新增历史记录的步骤状态，避免重复查询已加载页。
- **发布卫生加固**：`dist/` 产物不再进入 Git 仓库，安装包通过 GitHub Release/Actions artifact 分发；版本号统一升级到 `4.1.3`。
- **质量守卫补强**：新增 release metadata、批量删除、运行历史分页和运行 worker 回归测试；本地全量测试为 449 passed, 2 skipped。

## 近期更新

- **安全通知加固**：统一钉钉 Webhook URL 策略，发送前校验可信域名，错误消息和异常链路默认脱敏 access_token。
- **执行运行时治理**：补强子进程/执行器清理策略、结果状态策略和日志清理边界，降低孤儿进程与残留文件风险。
- **UI 架构优化**：步骤表格样式拆分复用，Webhook 管理界面复用统一策略，减少重复实现。
- **工程质量提升**：新增仓库卫生、CI、依赖一致性、风险调用、宽泛异常和打包自检守卫；全量测试覆盖提升到 446 项。
- **发布流程改进**：GitHub Actions 打包工作流支持手动/标签触发，产物附带 sha256，并执行隔离自检。

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| UI 框架 | PySide6 (Qt for Python) |
| 数据存储 | SQLite + SQLAlchemy (scoped_session) |
| 自动化 | 子进程执行（subprocess） |
| 并行执行 | concurrent.futures.ThreadPoolExecutor |
| 打包 | PyInstaller |

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动 GUI

```bash
python src/main.py
```

### 打包构建

```bash
pip install -r requirements-release.txt
pyinstaller build_slim2.spec
# 输出: dist/工作流管理_<APP_VERSION>_slim2.exe
```

### 质量验证

开发/CI 验证请先安装测试依赖：

```bash
pip install -r requirements-ci.txt
```

运行 `python tools/repo_hygiene.py --strict` 前，请先清理本地运行产物和导出残留，例如 `build/`、`dist/`、`data/`、`logs/`、`__pycache__/`、`.pytest_cache/`、`audit_export.json`、`tmp_export.json`、`workflows_export*.json`。

```bash
python tools/repo_hygiene.py --strict
python -m compileall src tests _import_and_run.py
python -m pytest -q
python src/cli.py --help
python src/cli.py export --help
python _import_and_run.py --help
```

本地强制执行（推荐）：执行 `python tools/install_hooks.py` 启用提交/推送前质量门（`git config core.hooksPath .githooks`）。
提交前自动运行风险调用/宽泛异常/热点基线审计与编译检查，推送前额外运行 `python -m pytest -q`；
跳过方式与远端分支保护说明见 `docs/development_guardrails.md` 的「本地强制：git hooks」一节。

仓库包含 GitHub Actions 工作流 `.github/workflows/ci.yml`，在 Windows runner 上执行依赖安装、编译检查、仓库卫生检查、测试和 CLI smoke；`.github/workflows/package.yml` 可手动触发 PyInstaller 打包验证，默认使用 `build_slim2.spec`，会在隔离的 `WORKFLOW_APP_DATA_DIR` 下对生成的 exe 执行 `--self-check`，并随 exe 上传 `.sha256` 校验文件。

### Release / Rollback

`.github/workflows/package.yml` 同时支持 `workflow_dispatch` 和发布 tag `v*` 触发。手动触发时可指定 PyInstaller spec；tag 触发默认使用 `build_slim2.spec`。打包前会先执行 `python tools/repo_hygiene.py --strict`，随后执行 clean-tree release gate（`git status --porcelain --untracked-files=all`），避免在脏工作区继续打包。

artifact 名称格式固定为 `workflow-manager-<APP_VERSION>-<specName>-<shortSha>`；其中 `APP_VERSION` 直接从 `src/config.py` 读取，产物会附带 `.sha256` 校验文件，且 exe 会在隔离的 `WORKFLOW_APP_DATA_DIR` 下执行 `--self-check`。

回滚时优先下载并校验目标版本 tag 对应的历史 artifact；如需重建旧版本，则手动运行 `Package` workflow，选择目标 tag 作为 ref，并保持与原发布一致的 spec。

## CLI 接口

CLI 位于 `src/cli.py`，所有工作流和步骤参数均支持**名称**（精确/模糊匹配）和**数字 ID**。

### 运行工作流

```bash
# 运行整个工作流
python src/cli.py run "月度报表"

# 按阶段运行
python src/cli.py run "月度报表" --stage "数据导入"        # 只运行某个阶段
python src/cli.py run "月度报表" --from-stage "数据清洗"   # 从某个阶段开始（含之后所有阶段）

# 按步骤运行
python src/cli.py run "月度报表" --only "清洗数据"         # 只运行某个步骤
python src/cli.py run "月度报表" --from "清洗数据"         # 从某个步骤开始

# 重试上次失败的步骤
python src/cli.py retry "月度报表"
```

### 查询与管理

```bash
python src/cli.py list                    # 列出所有工作流
python src/cli.py stages "月度报表"       # 查看阶段列表
python src/cli.py steps "月度报表"        # 查看步骤列表（含所属阶段）
python src/cli.py history "月度报表"      # 查看运行历史
python src/cli.py history "月度报表" --detail  # 含步骤级详情

python src/cli.py dry-run "月度报表"      # 预览执行计划（不实际运行）
python src/cli.py export "月度报表"       # 导出为 JSON（Webhook URL 默认脱敏）
python src/cli.py export "月度报表" --include-secrets  # 显式导出完整 Webhook URL
python src/cli.py import workflow.json    # 从 JSON 导入
python src/cli.py backup                  # 自动备份（Webhook URL 默认脱敏）
python src/cli.py backup --include-secrets # 显式备份完整 Webhook URL，便于本机恢复
python src/cli.py clone "月度报表"        # 克隆工作流
python src/cli.py delete "月度报表"       # 删除工作流
```

### 名称解析规则

| 输入 | 匹配方式 |
|------|---------|
| 纯数字 | 直接作为数据库 ID |
| 精确名称 | 完全匹配 |
| 部分关键词 | 模糊匹配，唯一结果自动选择；多个结果列出供选择 |

## 通知模板

在 GUI 的「Webhook 管理」中配置钉钉机器人后，工作流配置中可自定义通知模板。
Webhook URL 在管理界面默认遮蔽，普通导出和自动备份默认脱敏；只有显式使用 `--include-secrets` 时才会保留完整 URL。

### 可用变量

| 变量 | 说明 |
|------|------|
| `{工作流名称}` | 工作流名称 |
| `{状态}` | 运行状态（成功/失败/已取消） |
| `{运行编号}` | 本次运行的 Run ID |
| `{原因}` | 触发原因（manual/cli/watch/sub_workflow） |
| `{开始时间}` | 运行开始时间 |
| `{耗时}` | 总耗时 |
| `{失败摘要}` | 失败步骤的错误信息 |

模板示例：`【通知】{工作流名称} {运行编号} {状态}`

## 超时默认值

步骤超时留空（0）时按步骤类型应用默认超时：

| 步骤类型 | 默认超时 |
|------|------|
| Python | 7200 秒 |
| 子工作流 | 3600 秒 |

## 目录结构

```
Workflow/
├── src/                        # 源代码
│   ├── main.py                 # GUI 入口
│   ├── cli.py                  # CLI 入口
│   ├── engine.py               # 工作流引擎入口（运行生命周期、信号、执行编排）
│   ├── engine_core/            # 引擎子模块（调度、通知、阶段预览、日志清理）
│   ├── database.py             # 数据库操作入口（CRUD、会话管理）
│   ├── database_import_export.py # 工作流 JSON 导入导出
│   ├── database_clone.py       # 工作流克隆
│   ├── database_backup.py      # 自动备份文件管理
│   ├── database_field_guards.py # update_* 字段白名单
│   ├── models.py               # SQLAlchemy 数据模型
│   ├── config.py               # 应用配置（路径、数据目录）
│   ├── notifier.py             # 钉钉通知（模板渲染、发送）
│   ├── exceptions.py           # 自定义异常
│   ├── diagnostics.py          # 错误诊断
│   ├── ui/                     # 界面模块
│   │   ├── main_window.py      # 主窗口
│   │   ├── json_actions.py     # JSON 导入导出 UI 动作
│   │   ├── panel_layout.py     # 面板折叠和 splitter 尺寸规则
│   │   ├── run_actions.py      # 运行模式到引擎方法的分发
│   │   ├── run_state.py        # 运行态面板锁定和后台运行提示
│   │   ├── workflow_list.py    # 工作流列表面板
│   │   ├── workflow_config.py  # 工作流配置面板
│   │   ├── step_table/         # 步骤表格（拖拽排序）
│   │   ├── step_editor.py      # 步骤编辑器
│   │   ├── run_control.py      # 运行控制面板
│   │   ├── run_history.py      # 运行历史面板
│   │   ├── log_panel.py        # 日志面板
│   │   ├── webhook_manager.py  # Webhook 管理
│   │   └── theme.py            # 主题样式
│   └── executors/              # 任务执行器
│       ├── base.py             # 执行器基类
│       ├── python_executor.py  # Python 脚本执行器
│       ├── bat_executor.py     # 批处理脚本执行器
│       └── sub_workflow_executor.py  # 子工作流执行器
├── data/                       # SQLite 数据库（自动创建）
├── logs/                       # 运行日志（按工作流/运行批次/步骤分级）
├── docs/                       # 维护与安全文档
├── build.spec                  # PyInstaller 打包配置（完整包）
├── build_slim2.spec            # 默认发布用 PyInstaller spec
├── requirements.txt            # Python 依赖
├── requirements-release.txt    # 发布打包依赖与 PyInstaller 版本锁定
├── requirements-ci.txt         # CI 测试依赖锁定
└── _import_and_run.py          # 月度批量运行脚本（导入 + 运行 + 通知）
```

## 月度批量运行

每月定期运行时使用 `_import_and_run.py`，一个脚本搞定导入 + 运行 + 钉钉通知：

```bash
# 导入最新工作流备份 + 运行月度数据处理 + 运行人员数据处理分析
python _import_and_run.py --auto
python _import_and_run.py --workflows-json "D:/path/workflows_export.json" --auto

# 分步执行
python _import_and_run.py import                        # 从 workflows_export.json 导入
python _import_and_run.py --workflows-json "D:/path/workflows_export.json" import
python _import_and_run.py run "月度数据处理"             # 运行月度数据处理
python _import_and_run.py run "人员数据处理分析"         # 运行人员数据处理

# 通过 ID 运行
python _import_and_run.py run 5
python _import_and_run.py run 7

# 工作流名称支持模糊匹配
python _import_and_run.py run "月度"

# 查看所有可用工作流
python src/cli.py list
```

> **注意**：`_import_and_run.py` 默认读取项目根目录的 `workflows_export.json`；如文件在其他位置，请使用 `--workflows-json` 指定。

## 数据存储

- 数据库文件：`data/workflows.db`（SQLite）
- 运行日志：`logs/{workflow_uid}/{run_id}/step_{order}_{step_uid}/stdout.txt`
- 打包后数据目录：`%LOCALAPPDATA%/工作流管理/`

## 日志

GUI 运行日志会写入 `%LOCALAPPDATA%/工作流管理/logs/app.log`（开发模式为项目 `logs/app.log`），排障时优先查看该文件；步骤级输出日志位置见上方「数据存储」。

## License

MIT
