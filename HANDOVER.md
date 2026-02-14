# 工作流管理应用 — 交接文档

> 撰写时间：2026-02-12  
> 项目路径：`<AI分析根目录>\\工作流管理`（示例：`D:\\Work\\AI分析\\工作流管理`）  
> 技术栈：Python 3 + PySide6 (Qt6) + SQLAlchemy + SQLite

---

## 一、项目基础说明

### 1.1 项目名称与用途

**项目名称**：工作流管理（Workflow Manager）

**核心用途**：一个桌面端 GUI 应用，用于编排和管理数据分析工作流。用户可以将多个脚本（Python、Excel PowerQuery、Power BI Desktop 刷新、子工作流）编排为一个多步骤工作流，支持依赖控制、并行执行、文件监听自动触发、钉钉通知、运行历史回溯等。

**典型应用场景**：
- 每日数据刷新（Excel → Python 计算 → Power BI 刷新 → 钉钉通知）
- 多步骤报表生成管线（带依赖和并行）
- 文件变更触发自动执行

### 1.2 整体架构

```
src/
├── config.py               # 应用配置（路径、步骤类型枚举）
├── models.py               # SQLAlchemy ORM 模型（6 张表）
├── database.py             # 数据库 CRUD + 迁移逻辑（729 行）
├── engine.py               # 工作流编排引擎（925 行，核心）
├── notifier.py             # 钉钉消息通知
├── main.py                 # 应用入口
├── executors/              # 步骤执行器（Python/Excel/PowerBI/子工作流）
└── ui/                     # PySide6 GUI 组件（13 个文件）
    ├── main_window.py      # 主窗口（信号路由中枢，575 行）
    ├── workflow_list.py    # 左侧工作流列表
    ├── workflow_config.py  # 工作流基础配置面板（可折叠）
    ├── run_control.py      # 运行控制按钮面板
    ├── step_table.py       # 步骤列表表格（含 ReorderableTable，528 行）
    ├── step_editor.py      # 步骤详情编辑器（537 行）
    ├── dag_view.py         # DAG 可视化面板（泳道布局）
    ├── log_panel.py        # 实时日志面板
    ├── run_history.py      # 运行历史面板
    ├── error_summary.py    # 错误汇总弹窗 [新建]
    ├── webhook_manager.py  # Webhook 管理对话框
    └── theme.py            # 主题样式
```

### 1.3 数据模型（models.py，6 张表）

| 模型 | 表名 | 说明 |
|------|------|------|
| `Workflow` | `workflows` | 工作流主表（名称、并行设置、通知、监听目录、日志保留天数等） |
| `Step` | `steps` | 步骤表（类型、脚本路径、依赖、并行、前置、超时、重试、`skip_on_success`） |
| `RunHistory` | `run_histories` | 运行历史（运行编号、模式、状态、开始/结束时间） |
| `StepLog` | `step_logs` | 步骤日志（stdout/stderr 路径、状态、耗时） |
| `RecentWorkflow` | `recent_workflows` | 最近使用的子工作流 UID |
| `WebhookConfig` | `webhook_configs` | Webhook 配置（钉钉） |

### 1.4 引擎核心机制（engine.py）

- **`WorkflowEngine`** 继承 `QObject`，在 `QThread` 中运行
- **Qt 信号**：`workflow_started`、`workflow_finished`、`step_started`、`step_finished`、`log_output`、`progress_updated`、`error_details`
- **运行模式**：`full`（全流程）、`from_step`（从指定步骤）、`only_step`（仅运行一步）、`retry_failed`（重试失败）
- **分批计算**：`compute_batches(workflow, steps)` 静态方法，根据依赖、并行、Gate 步骤自动计算执行批次
- **执行流程**：`_run()` → `_execute_steps()` → 串行 `_execute_single_step()` 或并行 `_execute_parallel_steps()`
- **文件监听**：`start_watch()` / `stop_watch()` / `_watch_loop()` 基于轮询目录 mtime

### 1.5 主窗口信号路由（main_window.py）

`_connect_signals()` 方法是信号路由中枢，关键连接：

| 信号源 | 信号 | 目标槽函数 |
|--------|------|-----------|
| `workflow_list` | `workflow_selected` | `_on_workflow_selected` |
| `step_table` | `step_selected` / `steps_changed` | `_on_step_selected` / `_on_steps_changed` |
| `step_editor` | `step_saved` | `_on_step_saved` |
| `workflow_config` | `workflow_updated` | `_on_workflow_updated` |
| `run_control` | `run_requested` / `dry_run_clicked` | `_on_run_requested` / `_on_dry_run` |
| `engine` | `workflow_started/finished` / `step_started/finished` / `log_output` / `error_details` | 对应 `_on_*` 槽函数 |

---

## 二、本次优化已完成的功能改动

### 2.1 Phase 1：数据模型扩展

#### models.py
- `Workflow` 新增字段 `log_retention_days: Mapped[int] = mapped_column(Integer, default=30)` — 日志保留天数
- `Step` 新增字段 `skip_on_success: Mapped[bool] = mapped_column(Boolean, default=False)` — 上次成功则跳过

#### database.py
- `init_db()` 中依次调用 `_ensure_workflow_columns()` 和 `_ensure_step_columns()` 进行旧库兼容迁移
- `_ensure_workflow_columns()` 新增 `log_retention_days` 列检查和 ALTER TABLE 逻辑
- `_ensure_step_columns()` 新建函数，检查并添加 `skip_on_success` 列
- `copy_workflow()` 更新为复制 `log_retention_days` 和 `skip_on_success` 字段

### 2.2 Phase 2：引擎层增强

#### engine.py
1. **`error_details` 信号**（`Signal(list)`）：工作流失败时发射 `[{"step_id", "step_name", "error_message"}, ...]`
2. **`compute_batches()` 提取为公开静态方法**：供 `dry_run()`、`step_table.py`、`dag_view.py` 复用
3. **`dry_run()` 预演方法**：调用 `compute_batches()` 输出分批计划到日志，不实际执行
4. **`skip_on_success` 逻辑**：在 `_execute_single_step()` 开头检查上次运行结果，满足条件则跳过
5. **`_cleanup_old_logs()` 日志清理**：在 `_run()` 开头调用，根据 `workflow.log_retention_days` 删除过期日志目录
6. **失败摘要收集**：`_execute_steps()` 收集 `failed_details` 列表，最后通过 `error_details` 信号发射

#### notifier.py
- `TEMPLATE_VARIABLES` 新增 `{失败摘要}` 模板变量
- `format_message()` 支持替换 `{失败摘要}`
- `send_workflow_notification()` 接受 `failure_summary` 参数

### 2.3 Phase 3 + 缺陷修复：步骤表格增强

#### step_table.py（完全重写，528 行）

**核心改动**：
1. **创建 `ReorderableTable(QTableWidget)` 子类**（第 28-38 行）
   - 解决问题：标准 `QTableWidget.model().rowsMoved` 信号从不触发
   - 方案：重写 `dropEvent()`，在 `super().dropEvent()` 后发射自定义 `rows_reordered` 信号
   - `StepTablePanel` 连接 `self.table.rows_reordered.connect(self._on_rows_reordered)`

2. **去掉阶段标签行，改用行背景色区分阶段**
   - 旧方案：`setSpan()` 插入标签行 → 导致跨阶段拖拽失败
   - 新方案：`STAGE_COLORS = [QColor("#F5F5F5"), QColor("#FFFFFF")]` 交替色带
   - `_step_stage_map: Dict[int, int]` 缓存每个 step_id 对应的 stage 索引
   - `_set_row_data()` 中为每个 cell 设置 `setBackground(bg)`

3. **右键菜单新增"⬆ 与上一阶段合并"**（`_merge_with_prev_stage()` 方法）
   - 逻辑：将步骤设为 `is_parallel=True` + 复制上一阶段首步骤的依赖
   - 仅在 `stage_idx > 0` 且 `_edit_enabled` 且 `_parallel_available` 时显示

4. **`reset_all_status()` 恢复阶段色带**而非固定白色
5. **`_on_selection_changed()` 增加 `step_id` 空值检查**避免发射无效信号

### 2.4 Phase 4：错误处理 UX

#### error_summary.py [新建文件]
- `ErrorSummaryDialog(QDialog)`：接收 `error_details` 数据，表格展示失败步骤名称 + 错误信息

#### log_panel.py
- 新增 `append_error_details(error_list)` 方法：以红色 HTML 文本在日志面板内联展示失败摘要

### 2.5 Phase 5：UI 组件完善

#### run_control.py（完全重写）
- 保留原有 `run_requested` 信号
- 新增 `dry_run_clicked` 信号和"👁 预演"按钮（`setToolTip("预览分批执行计划，不实际执行")`）
- 新增"取消"按钮（发射 `run_requested.emit("cancel", None)`）

#### workflow_config.py
- `__init__` 中 `self._is_collapsed = True`（原 `False`）
- `btn_toggle` 初始文字改为"展开"
- `content_widget.setVisible(False)` — 默认折叠基础配置区域

#### step_editor.py
1. 在"并行执行"旁新增"上次成功跳过" `QCheckBox`（`check_skip_on_success`）
   - label: "启用（自动化运行时跳过已成功步骤）"
   - tooltip: "勾选后，若上次运行该步骤成功，本次将自动跳过"
2. `load_step()` 加载 `skip_on_success` 字段
3. `save_step()` 传递 `skip_on_success` 到 `update_step()`
4. `save_step()` 新增脚本路径存在性校验（非阻塞，`QMessageBox.warning` 可选择继续保存）

### 2.6 Phase 6：主窗口集成 + DAG 泳道布局

#### main_window.py
- `import ErrorSummaryDialog`
- `_connect_signals()` 新增：
  - `self.engine.error_details.connect(self._on_error_details)`
  - `self.run_control.dry_run_clicked.connect(self._on_dry_run)`
- `_on_workflow_started()` 新增 `self.step_table.reset_all_status()`
- `_on_run_requested()` 新增 `cancel` 模式处理
- 新增 `_on_error_details()` 槽：调用 `log_panel.append_error_details()` + 弹出 `ErrorSummaryDialog`
- 新增 `_on_dry_run()` 槽：调用 `self.engine.dry_run(workflow_id)`

#### dag_view.py（完全重写，泳道布局）
1. **泳道布局**：调用 `WorkflowEngine.compute_batches()` 获取分批，阶段为列（x 轴）、同阶段步骤纵向排列（y 轴）
2. **阶段背景矩形**：`LANE_COLORS = ["#F8FAFC", "#F1F5F9"]` 交替色，`QGraphicsRectItem` 置于 `zValue=-1`
3. **阶段标签**：`QGraphicsSimpleTextItem` 显示"阶段 N (并行/串行/Gate)"
4. **带箭头连线**：`_draw_connection()` 在连线终点绘制三角箭头
5. **视图高度自适应**：`self.view.setFixedHeight(max(120, min(scene_h + 30, 400)))`
6. **import 变更**：新增 `get_workflow_by_id`、`QGraphicsSimpleTextItem`

---

## 三、当前进度总结

### 3.1 已完成工作

| # | 工作项 | 状态 | 涉及文件 |
|---|--------|------|---------|
| 1 | 数据模型扩展（`skip_on_success` + `log_retention_days`） | ✅ 完成 | models.py, database.py |
| 2 | 引擎：`compute_batches` 公开方法 | ✅ 完成 | engine.py |
| 3 | 引擎：`dry_run()` 预演 | ✅ 完成 | engine.py |
| 4 | 引擎：`error_details` 信号 + 失败摘要收集 | ✅ 完成 | engine.py |
| 5 | 引擎：`skip_on_success` 跳过逻辑 | ✅ 完成 | engine.py |
| 6 | 引擎：`_cleanup_old_logs()` 自动日志清理 | ✅ 完成 | engine.py |
| 7 | 通知：`{失败摘要}` 模板变量 | ✅ 完成 | notifier.py |
| 8 | 步骤表格：拖拽修复（ReorderableTable） | ✅ 完成 | step_table.py |
| 9 | 步骤表格：阶段色带（去掉标签行） | ✅ 完成 | step_table.py |
| 10 | 步骤表格：右键"合并阶段"操作 | ✅ 完成 | step_table.py |
| 11 | DAG：泳道布局 + 阶段标签 + 箭头 | ✅ 完成 | dag_view.py |
| 12 | 错误汇总弹窗 | ✅ 完成 | error_summary.py [新建], log_panel.py |
| 13 | UI：预演按钮 | ✅ 完成 | run_control.py |
| 14 | UI：基础配置默认折叠 | ✅ 完成 | workflow_config.py |
| 15 | UI：skip_on_success 开关 + 脚本校验 | ✅ 完成 | step_editor.py |
| 16 | 主窗口信号集成 | ✅ 完成 | main_window.py |

### 3.2 已解决的关键问题

| 问题 | 根因 | 解决方式 |
|------|------|---------|
| 拖拽后列表渲染异常 | `QTableWidget.model().rowsMoved` 从不触发 | 创建 `ReorderableTable` 子类重写 `dropEvent` |
| 跨阶段拖拽失效 | 阶段标签行 `setSpan` 干扰 `InternalMove` | 去掉标签行，改用行背景色交替 |
| DAG 未按阶段分组 | 所有节点在同一行 y=15 水平排列 | 泳道布局（`compute_batches` + 阶段列 + 纵向排列） |
| `run_control.py` 文件被编辑工具破坏 | multi_replace 匹配不精确 | 完全重写恢复 |

### 3.3 编译验证

所有修改均已通过 `python -m compileall src -q` 编译验证，无语法或导入错误。

### 3.4 未进行的测试

> **重要提示**：以下模块/功能仅通过编译验证，**尚未进行运行时测试**。新 AI 接手后应优先进行冒烟测试。

- 拖拽排序实际操作效果
- DAG 泳道布局的渲染效果（多阶段、多并行步骤场景）
- "与上一阶段合并"右键操作的实际效果
- `dry_run()` 预演按钮的日志输出
- `skip_on_success` 在自动运行时的跳过行为
- `ErrorSummaryDialog` 弹窗在工作流失败时的显示
- `_cleanup_old_logs()` 的实际清理行为
- `{失败摘要}` 钉钉通知模板

---

## 四、后续任务规划（按优先级排序）

### P0：冒烟测试 + 运行时验证（最高优先级）

**目标**：确保所有已改动功能在运行时正常工作

**执行要点**：
1. 启动应用 `python src/main.py`
2. 选择一个有多步骤的工作流，验证：
   - 步骤列表是否正确显示阶段色带
   - DAG 是否按泳道布局（多阶段纵向分列）
   - 拖拽步骤后列表是否正确刷新（不再需要切换工作流）
   - 跨阶段拖拽是否顺畅
   - 右键菜单"与上一阶段合并"是否正常
   - "预演"按钮点击后日志面板是否输出分批计划
   - 基础配置面板是否默认折叠
3. 若发现运行时 bug，按"根因分析 → 修复 → 编译验证"流程处理

### P1：拖拽功能深度验证（高优先级）

**目标**：确保 `ReorderableTable.dropEvent()` 在所有边界场景下工作正常

**重点关注**：
- 拖拽到顶部/底部边界
- 单步骤工作流的拖拽（应无操作）
- 拖拽后阶段色带是否正确刷新（因为 `_on_rows_reordered` 会调用 `load_steps` 重新渲染）
- 拖拽操作与编辑模式开关的交互（编辑关闭时应禁止拖拽）

**实施要点**：若发现拖拽仍有问题，检查 `ReorderableTable.dropEvent` 是否需要过滤非数据行的事件，或检查 `setDragEnabled` 是否需要与编辑模式联动。

### P2：DAG 连线优化（中优先级）

**目标**：优化复杂工作流的 DAG 连线显示

**当前状态**：连线使用直线（`QGraphicsLineItem`），跨列连线可能交叉重叠

**建议改进**：
- 改用折线（Manhattan routing）或贝塞尔曲线避免交叉
- 为连线添加不同颜色区分依赖类型
- 节点点击高亮其上下游连线

**关键文件**：`dag_view.py` 第 309-343 行 `_draw_connection()` 方法

### P3：步骤模板 / 复制功能（中优先级）

**目标**：允许用户将常用步骤配置保存为模板，或复制现有步骤

**实施要点**：
- `database.py` 新增 `copy_step(step_id)` 函数
- `step_table.py` 右键菜单添加"复制步骤"操作
- 可选：新建 `step_template` 表存储模板

### P4：运行历史增强（低优先级）

**目标**：在运行历史面板中展示更多上下文信息

**建议改进**：
- 每条历史记录展示失败步骤数 / 成功步骤数
- 点击历史记录可回溯查看当时的步骤日志
- 添加"清除历史"按钮（`clear_run_histories()` 已在 database.py 中实现）

### P5：DAG 交互增强（低优先级）

**目标**：让 DAG 支持交互操作

**建议改进**：
- 节点双击打开步骤编辑器
- 节点右键菜单（运行此步骤、查看日志等）
- 拖拽 DAG 节点调整步骤顺序

---

## 五、关键注意事项

### 5.1 文件损坏风险

在本次开发中，`run_control.py` 曾因 `multi_replace_file_content` 工具匹配不精确而被破坏（文件内容重复、缩进错乱）。**建议**：
- 对于小文件（<100 行），优先使用 `write_to_file(Overwrite=true)` 完全重写
- 修改后立即运行 `python -m compileall src -q` 验证

### 5.2 数据库迁移兼容

`database.py` 中的 `_ensure_workflow_columns()` 和 `_ensure_step_columns()` 负责旧库字段迁移。新增模型字段时**必须**同步在这两个函数中添加 ALTER TABLE 逻辑，否则旧数据库文件会报列不存在错误。

### 5.3 信号线程安全

`WorkflowEngine` 在 `QThread` 中运行，所有信号（如 `error_details`、`log_output`）通过 Qt 的线程安全信号机制传递到主线程 UI。在 `_on_run_requested` 中，工作流执行函数被封装在 `QThread` 中：

```python
self._run_thread = QThread()
self._run_thread.run = run_in_thread
self._run_thread.start()
```

### 5.4 compute_batches 的关键地位

`WorkflowEngine.compute_batches()` 是阶段计算的唯一真相源（single source of truth），被以下三处调用：
1. `engine.py` → `_execute_steps()` 和 `dry_run()` — 运行时分批
2. `step_table.py` → `load_steps()` — 阶段色带
3. `dag_view.py` → `update_dag()` — 泳道布局

任何对分批逻辑的修改都会影响这三处。

### 5.5 编辑模式防误操作

应用有"编辑开关"机制（`_edit_mode`），默认关闭。所有增删改操作（新建/删除工作流、保存步骤、拖拽排序等）都需要先开启编辑模式。接手后注意测试时先开启左侧"编辑 → 开启"复选框。
