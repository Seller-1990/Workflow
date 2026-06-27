# 工作流管理应用（Qt/PySide6）交接文档（2026-02-13）

> 目的：当前 AI 额度耗尽，需要切换新 AI 继续开发。本文力求让新接手的 AI **无需额外追问**即可快速掌握项目全貌、当前状态、已做改动与后续优先事项，并可按“验证→定位→改动→回归”闭环推进。

---

## 1. 项目基础说明

### 1.1 项目名称与核心用途
- **项目名称**：工作流管理（桌面端）
- **技术栈**：Python + PySide6（Qt），SQLite（本地持久化），PyInstaller（打包 exe）
- **核心用途**：为个人/内网小团队提供“可视化工作流编排 + 一键运行 + 日志/历史 + 通知 + 文件监听触发”的统一工具。

### 1.2 应用场景（简要）
- 工作流由多个步骤组成：Python 脚本、Excel PowerQuery 刷新、Power BI Desktop 刷新、子工作流等。
- 支持“全流程运行 / 从指定步骤开始 / 只运行指定步骤 / 重试失败步骤”。
- 支持文件夹变更监听自动触发工作流。
- 支持钉钉通知（Webhook 机器人）与 Webhook 管理。

### 1.3 当前优化的核心目标（本轮迭代）
1) **把“阶段”从调度批次概念中解耦**：阶段用于“用途归类 + 顺序门槛”；调度仍由依赖决定。  
2) **并行能力做减法**：并行由基础配置统一控制，不在步骤列表暴露“并行列”。  
3) **交互稳定性**：拖拽排序必须稳定落库、无 Qt invalid index 警告；取消=已取消，不与失败混淆。  
4) **新手友好**：步骤编辑器默认简化，复杂项折叠到“高级设置”；依赖摘要默认折叠，警告自动展开。  
5) **导入导出完整性**：JSON 导入导出必须包含 Webhook 管理配置，跨机器可恢复。

---

## 2. 代码结构与整体架构

### 2.1 目录结构（关键）
- `工作流管理/src/`
  - `config.py`：路径/版本/StepType、APP_DATA_DIR、DB/LOG 路径等
  - `models.py`：SQLAlchemy 模型（Workflow/WorkflowStage/Step/RunHistory/StepLog/WebhookConfig…）
  - `database.py`：SQLite 初始化、迁移补字段、CRUD、JSON 导入导出、stage 相关接口
  - `engine.py`：调度与执行真相源（`compute_batches()`）、监听触发、dry_run、日志/通知、取消语义
  - `executors/`：各类型步骤的执行器（Python/Excel/PBI/子工作流…）
  - `ui/`
    - `main_window.py`：三栏主界面、线程启动、编辑开关、工具栏、折叠控制、信号联动
    - `workflow_list.py`：工作流列表 + 新建/复制/删除
    - `workflow_config.py`：基础配置面板（折叠头部、并行开关、监听、通知等）
    - `step_table.py`：步骤列表（用途阶段分组、拖拽落库、阶段右键菜单、列宽持久化）
    - `step_editor.py`：步骤编辑器（基础区 + 依赖摘要 + 高级设置）
    - `dag_view.py`：DAG 可视化（列=用途阶段，连线=显式依赖）
    - `log_panel.py`：实时日志（工具条：清空/复制/打开/停止）
    - `run_history.py`：运行历史（可折叠）
    - `run_control.py`：运行控制（四模式 + 停止）
    - `webhook_manager.py`：Webhook 管理弹窗
    - `collapsible_section.py`：统一折叠头部组件（标题+箭头同一行）
    - `error_summary.py`：失败摘要弹窗（避免静默吞错）
- `工作流管理/tests/`：单测（重点覆盖调度语义）
- `工作流管理/build.spec`：PyInstaller 打包配置
- `工作流管理/workflows_export.json`：示例导入数据（冒烟用）

### 2.2 数据持久化与运行数据位置
见 `工作流管理/src/config.py`：
- 开发态：`APP_DATA_DIR = ROOT_DIR`（即 `工作流管理/`）
  - DB：`工作流管理/data/workflows.db`
  - Logs：`工作流管理/logs/`
- 打包 exe：`APP_DATA_DIR = %LOCALAPPDATA%/工作流管理`
  - DB/Logs 都会写到用户目录（避免写入 _MEIPASS）。

---

## 3. 核心概念与规则（必须先理解）

### 3.1 用途阶段（Purpose Stage） vs 执行组（Execution Group）
**用途阶段（人为归类）**
- 数据来源：`WorkflowStage` 表，每个工作流独立管理。
- 用途：步骤列表按阶段“框住”分组显示；阶段有顺序、可插入/重命名/删除。
- **执行门槛（stage barrier）**：阶段顺序影响执行；后续阶段默认等待前一阶段完成（引擎层实现）。

**执行组（自动调度分组）**
- 数据来源：`WorkflowEngine.compute_batches()` 输出的 batches（同阶段内按依赖层分组）。
- 用途：解释真实调度结构（同依赖层并行、Gate 单独）。
- UI/日志：默认弱化，仅在阶段内存在多组时显示“执行组 i/n”。

### 3.2 依赖（depends_on）与 Gate（前置/检查点）
- **依赖**：显式 DAG 边，决定同阶段内的执行先后与并行分组。
- **Gate（`is_gate=True`）**：检查点/闸门，若 runnable 中存在 Gate，优先单独执行（不与同层并行混跑）。
- 关键约束：**禁止“依赖未来用途阶段”**（严格规则），否则抛 `DependencyError`。

### 3.3 并行语义（做减法后的规则）
见 `工作流管理/src/engine.py:WorkflowEngine.compute_batches()`：
- `workflow.parallel_enabled == False`：每批只跑 1 个步骤（串行）。
- `workflow.parallel_enabled == True`：
  - 若 runnable 存在 Gate：本轮 batch = `[gate_steps[0]]`
  - 否则：本轮 batch = 同依赖层 `same_level`（按 `order` 升序），**不再使用 `Step.is_parallel` 过滤**（字段保留用于兼容旧数据/JSON）。

### 3.4 编辑模式（防误操作）
见 `工作流管理/src/ui/main_window.py` 与各 panel：
- 默认 **编辑关闭**：所有写操作（拖拽、增删改等）应禁止，并提示“需要先开启编辑”。
- 编辑开启：写操作可用，变更落库并可追溯（RunHistory/Logs/DB）。

---

## 4. 已完成的功能改动详情（按模块）

> 以下为“已落地到代码”的改动（可直接在对应文件中查阅）。

### 4.1 数据模型：用途阶段 + Step 绑定（DB 迁移与兼容）
**文件**：`工作流管理/src/models.py`, `工作流管理/src/database.py`
- 新增 `WorkflowStage` 表（用途阶段）。
- `steps` 表新增 `stage_uid` 字段（兼容迁移见 `_ensure_step_columns()`）。
- 启动时自动补齐默认阶段与旧步骤 stage_uid：
  - `database._ensure_stage_data()`：为每个 workflow 创建“默认阶段”，并为旧 steps 填充 `stage_uid`。
- Stage CRUD：
  - `list_stages/create_stage/update_stage/delete_stage/get_stage_order_map` 等（`database.py` 中实现）。

### 4.2 引擎：stage barrier + 自动并行 + 取消语义一致
**文件**：`工作流管理/src/engine.py`
- `compute_batches(workflow, steps, stage_order_by_uid)`：
  - **用途阶段门槛**：只在当前最早 stage 中挑 runnable。
  - **禁止依赖未来阶段**：发现则 `DependencyError`。
  - **自动并行**：并行开关打开后，同依赖层默认并行（不再依赖 `is_parallel`）。
- `dry_run()` 与运行时日志术语统一：
  - 按“阶段 S# 阶段名”分段，必要时出现“执行组 i/n”，不再强调“批次/Bx”。
- 取消=已取消（cancelled）贯穿：
  - `RunStatus.CANCELLED`
  - `workflow_finished = Signal(int, str, str)`，第三参为 `success|failure|cancelled`
  - `_run()` 采用 finally 收尾：无论异常/取消，都会落库 run_history + emit finished +（若启用）通知。
- 原子启动、防双启动：
  - `_run()` 开头把 `_running` 检查移入 `with self._lock:` 原子区，避免 UI/监听同时启动双 run。
- 文件监听线程：`threading.Thread`（守护线程）轮询触发。

### 4.3 JSON 导入导出：包含 stages 与 webhooks（跨机器恢复）
**文件**：`工作流管理/src/database.py`
- `export_to_json()` 顶层包含 `webhooks: [...]`（按 name 排序）。
- `import_from_json()`：
  - 先导入/合并 webhooks，建立 `name -> id` 映射，再导入 workflows/steps，修正 notify_config 的 webhook 引用。
- workflow 内新增 `stages: [{uid,name,order,color}]`；step 增加 `stage_uid`。

### 4.4 步骤列表：用途阶段“框住”分组 + 稳定拖拽落库 + 阶段操作
**文件**：`工作流管理/src/ui/step_table.py`
- 关键类：
  - `ReorderableTable(QTableWidget)`：自定义拖拽，避免 Qt 内部 InternalMove 造成 `dataChanged invalid index`。
    - 信号：`rows_dragged(from_row, to_row)`
    - `dropEvent()`：**不调用** `super().dropEvent()`，仅发信号。
  - `StepTablePanel`：以“落库→reload”实现最终一致。
- 用途阶段显示：
  - 在表格中插入“阶段标题条行”（整行 span），阶段标题 + 右侧操作按钮（上移/下移/插入/更多）。
  - `_row_meta` 维护 UI 行类型：`stage_header` vs `step`。
  - 表格背景绘制：`paintEvent()` 画“框住感”卡片，hover 高亮目标阶段。
- 拖拽行为（默认改归类与顺序）：
  - `_on_rows_dragged()`：根据落点行推断目标 `stage_uid`，然后 `_apply_orders_and_stage_update()` 做事务写库：
    - 更新全量 step.order
    - 覆盖 moved_step.stage_uid
    - `WorkflowEngine.compute_batches()` 预校验；失败回滚并提示
- 阶段右键菜单：
  - 重命名、插入新阶段、删除阶段（含迁移向导）等。
- 列宽可拖拽与持久化：
  - `QHeaderView.Interactive` + `QSettings(APP_NAME,"ui")` 保存 `StepTable/column_widths`（有 debounce timer）。

### 4.5 步骤编辑器：默认极简 + 依赖摘要折叠 + 高级设置
**文件**：`工作流管理/src/ui/step_editor.py`
- 使用 `CollapsibleSection`：
  - `依赖摘要（只读）` 默认折叠：`collapsed=True`
  - 有警告时自动展开（依赖/循环/未来阶段等提示）
  - 高级设置默认折叠；Gate 放在高级设置中，避免与“依赖”心智混淆。
- 当前代码状态说明（很重要）：
  - 代码里“步骤名称”与“脚本/文件路径”仍是两行（主界面 Pencil 目标是同一行，**尚未落地到 Qt**；见后续任务）。

### 4.6 DAG 可视化：列=用途阶段，连线=显式依赖
**文件**：`工作流管理/src/ui/dag_view.py`
- DAG 泳道列按用途阶段 `S1/S2...` 展示，弱化“批次”概念。
- 连线只画显式依赖，避免“无显式依赖时满屏连线”。

### 4.7 主窗口与运行控制：停止入口统一、运行时 UI 解锁可靠
**文件**：`工作流管理/src/ui/main_window.py`, `工作流管理/src/ui/run_control.py`, `工作流管理/src/ui/log_panel.py`
- 主窗口三栏结构 + 中区可滚动（避免控件堆叠）。
- 编辑开关放左侧（工作流列表与运行控制之间），默认关闭。
- 右侧日志工具条提供“停止”兜底；运行中右侧自动展开（避免用户找不到停止入口）。
- 引擎 finished 信号携带 status，UI 按 success/failure/cancelled 更新状态栏与按钮 enable 状态。

---

## 5. 当前进度（已完成 / 未完成 / 卡点）

### 5.1 已完成（代码层）
- 用途阶段（DB/引擎/UI）双层模型已落地：阶段归类 + stage barrier 执行门槛 + 禁止依赖未来阶段。
- 自动并行语义已落地：并行由 workflow.parallel_enabled 控制，不依赖 step.is_parallel。
- 拖拽排序稳定落库：不再触发 Qt internal move 的 invalid index 警告。
- JSON 导入导出包含 webhooks + stages + step.stage_uid，跨机器可恢复。
- 取消语义统一为 `cancelled`：状态栏/运行历史/通知（引擎层）一致。

### 5.2 未完成（主要在 UI 视觉稿与“落地实现”之间）
1) **Pencil 视觉稿（`.pen`）持久化异常**
   - 现状：`工作流管理/designs/ios_minimal_focus.pen` 在磁盘上是 **0 字节**，但通过 Pencil MCP 工具可以打开并看到内容。
   - 结论：需要新 AI **优先解决“Pencil 文档如何落盘/导出到 repo”**，否则示意稿无法交付/无法版本化。
2) **Pencil icon library（矢量图标）质量未达用户预期**
   - 用户反馈“完全不合格”，主要问题来自旋转锚点/对齐导致图标变形或像临时符号。
   - 已尝试重画与微调，但用户仍不满意（需要继续迭代或换绘制策略：尽量减少 rotation、用纯水平/垂直段组合）。
3) **步骤编辑器排版落地**
   - 用户期望：步骤名称+脚本路径同一行、依赖+依赖提示同一行（Pencil 已示意），但 `step_editor.py` 尚未按此重排。

---

## 6. 后续实施任务规划（按优先级）

### P0（最高优先）：交付不可阻塞项
1) **解决 Pencil `.pen` 落盘/导出问题**
   - 目标：`工作流管理/designs/ios_minimal_focus.pen` 不再是 0 字节，能在 git 中真实版本化。
   - 建议路径：
     - 调查 Pencil MCP 是否将文档存储在内存/缓存；尝试用 MCP 工具导出完整 JSON（若工具不支持，需实现“从 batch_get 的 document tree 生成 .pen JSON”并写入文件）。
2) **重做 Icon Library（矢量图标）到可交付质量**
   - 目标：一眼“像 iOS/SF Symbols 的细线图标”，对齐/中心/比例一致；并在日志/阶段按钮/删除等处复用。
   - 建议策略（避免旋转锚点坑）：
     - Chevron/箭头尽量用水平/垂直段 + 45° rotation 但通过定位补偿；
     - 或直接用 `path`（若 Pencil 支持且稳定）做固定几何；
     - 建立 icon token：`16x16`、线宽 `1.5`、圆角 `0.75`、色 `#334155`（danger `#B42318`）。
3) **把 Pencil 确认过的布局落地到 Qt**
   - StepEditor：两行合并为一行（Name+Path）、依赖与提示同一行；Gate 保持在高级设置。
   - DAG：节点更紧凑、标题/按钮文字居中、圆角统一（结合 theme.py）。

### P1（中优先）：体验与一致性提升
1) UI 圆角 token 全局统一（theme.py + 各面板局部样式收敛）。
2) 步骤列表列宽持久化的“重置入口”补齐（右键/更多菜单）。
3) 阶段标题条操作按钮（Qt）进一步 iOS 化（pill 容器、hover/disabled 状态一致）。

### P2（低优先）：功能增强与可维护性
1) DAG 交互增强：双击节点定位步骤、右键打开日志目录/运行此步骤（仍受编辑/运行状态约束）。
2) 运行历史增强：成功/失败步骤统计、打开 log_dir、清除历史。
3) 产物管理/资源管理（用户已表示当前不紧迫）。

---

## 7. 重点风险点与踩坑记录（避免重复踩）

1) **Qt 表格拖拽**：不要用 `InternalMove + super().dropEvent()`；会触发 invalid index 与 setCellWidget 不稳定。当前方案是“拖拽手势识别→落库→reload”。
2) **并行语义**：不要再把 `Step.is_parallel` 当作执行筛选条件；它只保留兼容。真实规则见 `engine.compute_batches()`。
3) **跨阶段依赖**：严格禁止“依赖未来阶段”，否则 `DependencyError`；这不是 UI 限制，而是引擎真相源。
4) **通知编码/跨机恢复**：导入导出必须带 `webhooks` 顶层字段；notify_config 以 `webhook_name` 映射恢复 id。
5) **技能工具输出编码**：运行 `.agent/skills/ui-ux-pro-max-skill` 的 `search.py` 时需要：
   - PowerShell：`$env:PYTHONIOENCODING='utf-8'`
   - 否则会 `UnicodeEncodeError: gbk`。

---

## 8. 验证与验收（新 AI 必跑）

### 8.1 自动验证（每次改动后）
```bash
python -m compileall 工作流管理/src -q
python -m pytest -q 工作流管理/tests
```

### 8.2 手工冒烟（最短闭环）
1) 启动：`python 工作流管理/src/main.py`
2) 导入样例：选择 `工作流管理/workflows_export.json`
3) 开启编辑：左侧“编辑→开启”
4) 步骤拖拽：
   - 同阶段内拖拽排序
   - 跨阶段拖拽到另一个阶段框（应改归类 + 顺序落库）
   - 重启确认顺序与阶段归类持久化
5) 并行：
   - 勾选基础配置“启用并行”，无依赖同层应自动并行（Gate 单独）
6) 取消：
   - 运行中点击“停止运行”，状态栏/历史/通知（若启用）显示“已取消”
7) 依赖错误：
   - 制造未来阶段依赖，确认弹出/提示明确，且不会静默吞错

---

## 9. Pencil/UI 视觉稿说明（给新 AI）

### 9.1 Pencil MCP 文档节点（便于快速定位）
> 通过 MCP Pencil 工具可看到这些 nodeId（用于截图/比对）。
- 主界面整屏：`2WMJp`
- 步骤列表（阶段框）：`pwKPf`
- DAG 细节：`M1hsw`
- 步骤编辑器细节：`sfxu1`
- 日志与历史细节：`njpSd`
- Icon Library：`KN0zf`

### 9.2 严重问题：`.pen` 文件落盘为 0 字节
- 磁盘现状：`工作流管理/designs/ios_minimal_focus.pen` 为 0 bytes（不可版本化）。
- 但 MCP 工具能正常打开/截图，说明文档可能存储在工具侧缓存/内存。
- 新 AI 必须优先解决导出/落盘，否则视觉稿无法交付到 repo。

---

## 10. 新 AI 上手清单（一步到位）
1) 先跑 `compileall + pytest` 确认基线健康。
2) 读 `工作流管理/HANDOVER.md`（旧版交接）与 `工作流管理/05_整体Review与改进建议.md`（评审与建议）。
3) 复核以下关键文件（理解真相源）：
   - `工作流管理/src/engine.py`（compute_batches / dry_run / cancel）
   - `工作流管理/src/ui/step_table.py`（拖拽落库 / stage header / stage CRUD）
   - `工作流管理/src/database.py`（stages + export/import webhooks）
4) 处理 P0：
   - `.pen` 落盘
   - icon library 重做
   - Pencil→Qt 落地（StepEditor 行布局等）

---

## 11. 附：UI/UX 辅助工具（本地技能库）

### 11.1 ui-ux-pro-max-skill 本地路径
- `.agent/skills/ui-ux-pro-max-skill`
- 搜索命令（记得编码）：
```powershell
$env:PYTHONIOENCODING='utf-8'
python ".agent/skills/ui-ux-pro-max-skill/src/ui-ux-pro-max/scripts/search.py" "iOS minimal" --domain style -n 5
```

