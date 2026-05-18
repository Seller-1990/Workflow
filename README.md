# 工作流管理系统 (Workflow Manager)

基于 Python + PySide6 的桌面端工作流编排工具，将 Python 脚本、Excel 刷新、Power BI 刷新等异构任务串联成自动化工作流，提供可视化管理、阶段分组、日志追踪和钉钉通知。

## 核心功能

- **多类型任务编排** — Python 脚本、Excel 自动刷新（Win32 COM）、Power BI 数据集刷新、子工作流嵌套
- **阶段分组** — 将步骤按用途分组（如"数据导入"→"清洗"→"输出"），支持按阶段运行
- **DAG 依赖** — 步骤间可配置依赖关系，引擎自动拓扑排序、并行执行无依赖步骤
- **文件监听** — 监控指定文件夹，文件变化时自动触发工作流
- **钉钉通知** — 运行完成/失败时推送消息，支持自定义模板变量
- **运行历史** — 记录每次运行的步骤状态、耗时、日志，支持重试失败步骤
- **CLI 接口** — 无需打开 GUI，命令行即可运行/管理工作流

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| UI 框架 | PySide6 (Qt for Python) |
| 数据存储 | SQLite + SQLAlchemy (scoped_session) |
| 自动化 | pywin32 (Excel COM) / pywinauto (Power BI) |
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
pyinstaller build.spec
# 输出: dist/工作流管理.exe
```

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
python src/cli.py export "月度报表"       # 导出为 JSON
python src/cli.py import workflow.json    # 从 JSON 导入
python src/cli.py backup                  # 自动备份
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

## 目录结构

```
Workflow/
├── src/                        # 源代码
│   ├── main.py                 # GUI 入口
│   ├── cli.py                  # CLI 入口
│   ├── engine.py               # 工作流引擎（调度、并行、阶段）
│   ├── database.py             # 数据库操作（CRUD、会话管理）
│   ├── models.py               # SQLAlchemy 数据模型
│   ├── config.py               # 应用配置（路径、数据目录）
│   ├── notifier.py             # 钉钉通知（模板渲染、发送）
│   ├── exceptions.py           # 自定义异常
│   ├── diagnostics.py          # 错误诊断
│   ├── ui/                     # 界面模块
│   │   ├── main_window.py      # 主窗口
│   │   ├── workflow_list.py    # 工作流列表面板
│   │   ├── workflow_config.py  # 工作流配置面板
│   │   ├── step_table/         # 步骤表格（拖拽排序）
│   │   ├── step_editor.py      # 步骤编辑器
│   │   ├── dag_view.py         # DAG 依赖视图
│   │   ├── run_control.py      # 运行控制面板
│   │   ├── run_history.py      # 运行历史面板
│   │   ├── log_panel.py        # 日志面板
│   │   ├── webhook_manager.py  # Webhook 管理
│   │   └── theme.py            # 主题样式
│   └── executors/              # 任务执行器
│       ├── base.py             # 执行器基类
│       ├── python_executor.py  # Python 脚本执行器
│       ├── excel_executor.py   # Excel 刷新执行器
│       ├── powerbi_executor.py # Power BI 刷新执行器
│       └── sub_workflow_executor.py  # 子工作流执行器
├── data/                       # SQLite 数据库（自动创建）
├── logs/                       # 运行日志（按工作流/运行批次/步骤分级）
├── docs/                       # 项目设计文档
├── build.spec                  # PyInstaller 打包配置
├── requirements.txt            # Python 依赖
├── _import_and_run.py          # 月度批量运行脚本（导入 + 运行 + 通知）
└── _tmp_check.py               # 调试用临时脚本
```

## 月度批量运行

每月定期运行时使用 `_import_and_run.py`，一个脚本搞定导入 + 运行 + 钉钉通知：

```bash
# 导入最新工作流备份 + 运行月度数据处理 + 运行人员数据处理分析
python _import_and_run.py --auto

# 分步执行
python _import_and_run.py import                        # 从 workflows_export.json 导入
python _import_and_run.py run "月度数据处理"             # 运行月度数据处理
python _import_and_run.py run "人员数据处理分析"         # 运行人员数据处理

# 通过 ID 运行
python _import_and_run.py run 5
python _import_and_run.py run 7

# 工作流名称支持模糊匹配
python _import_and_run.py run "月度"

# 查看所有可用工作流
python _import_and_run.py import
```

> **注意**：脚本中的 `WORKFLOWS_JSON` 指向 `D:\OneDrive - PowerBI学谦\Data Analysis\workflows_export.json`，如路径变更需同步修改脚本顶部常量。

## 数据存储

- 数据库文件：`data/workflow.db`（SQLite）
- 运行日志：`logs/{workflow_uid}/{run_id}/step_{order}_{step_uid}/stdout.txt`
- 打包后数据目录：`%LOCALAPPDATA%/工作流管理/`

## License

MIT
