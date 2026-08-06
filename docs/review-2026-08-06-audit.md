# Workflow Manager v5.0.4 审查报告

- 审查日期：2026-08-06
- 审查范围：`src/`（约 100 个模块 / 28k LOC）+ `tests/`（79 个文件）
- 审查角度：功能稳定性 / 效率 / 精简
- 基线版本：`5.0.4`（`src/config.py:63`）
- 方法：3 个并行评审代理分角度深读 + 人工核实关键路径 + 全量测试实测

---

## 0. 结论摘要

该代码库工程防线成熟（CI、安全脱敏、发布门禁、打包自检、schema 版本管理均在位），
**全量测试实测 522 passed / 2 skipped**（54.8s）。这不是"失控"型代码库，真正的缺陷
集中在**取消/停止、文件监听、并行边界**的少数路径，以及一批低风险可清理的重复代码。

分维度评级（相对，非硬指标）：

| 维度 | 评级 | 一句话 |
|---|---|---|
| 功能稳定性 | 7.3 | 状态机与并行编排扎实，但 force_stop 与并行取消存在真实逻辑缺陷 |
| 效率 | 7.0 | DB 批处理已优化，主要开销是 watcher 全树扫描与主线程同步 DB 读 |
| 精简 | 6.8 | 重复已大量收敛，残余 4× 引导块 / 6× 按钮体 / 多层间接等可去重 |

> 本报告聚焦三视角，与 `audit-report-Workflow-2026-07-13.md` 的
> 安全/发布/维护角度互补，不重复其已覆盖内容。

---

## 1. 功能稳定性

### P0-1（已确认为 bug）`force_stop_run` 会误杀"实时运行"

- 位置：`src/engine.py:226-241`（分支 2）
- 现象：引擎正运行工作流 A 时，用户从历史列表强制停止一条**孤儿记录 B**
  （`run_history_id` 不在 `_active_run_ids`），代码落入第二个 `if self._running:` 分支
  把 `self._cancelled = True`。
- 后果：真实在跑的 A 被取消；目标 B 的库记录根本没写终态（路径 2 被跳过）。
  两个预期目标（停 B、不伤 A）全部落空。
- 根因：该分支是 R4-#6 为闭合"`_running` 已置位但 `_active_run_ids` 尚未 add"的竞态窗口
  而设，但未区分"本 run"与"其它运行"。
- 真实触发场景：一次崩溃留下 `status=running` 孤儿记录 → 用户重新运行 A →
  顺手清理孤儿记录 B → A 被意外取消。

### P0-2（已确认为 bug）并行批次取消时结果错位 + 进度少计

- 位置：`src/engine_core/scheduler.py:76-113` + `src/engine_core/run_orchestration.py:656-660,561`
- 现象：批量并行步骤 > max_workers 时中途取消，`_cancel_not_started` 把未启动的 future
  从 `results` 丢弃，但 `batch` 长度不变；随后 `zip(batch, results)` 把后面的结果
  错配到前面被取消的步骤。
- 后果：失败步骤名被错误上报；被取消步骤无 StepLog、无 finish 信号；
  `completed_steps += len(results)` 少计，进度出现"停住不动"跳变。
- 触发场景：批量并行步骤下载期间点停止。

### 中等级（行为可解，建议后续处理）

- **watch 触发在监听线程内同步阻塞整个运行**（`engine_core/watcher.py:463`）：
  `_trigger` 直接 `engine.run_all`，长任务期间 `stop()` 的 `join(timeout=1)` 超时，
  `stop_watch` 判定 `stopped=False` 不清理 → 监听无法实时停止/重启；
  运行期间的变更被基线吞并（后者为 README 已声明的预期行为）。
- **深层子工作流 `parent_run_id` 记成最外层**（`run_orchestration.py:298-302`）：
  嵌套 ≥2 层时子-子的 `parent_run_id` 取自 `_current_run_id`（嵌套态不落实例属性），
  历史父子关联错乱，仅供追踪取证场景。
- **「停止并运行新的」早退路径悬挂**（`ui/run_dispatch.py:74-108`）：若被停止的运行
  从未发 `workflow_started`，`workflow_finished` 永不 fire → 重试回调悬挂 + 连接泄漏。
- **`session.refresh()` 与并发删除竞态**（`database_runs.py:99,163,241`）：并行 worker
  写 step_log 与 `clear_run_histories`/`force_stop` 并发时可能 `DetachedInstanceError`，
  异常被吞、个别状态落库不一致（低概率）。
- **`_ensure_default_stage_in_session` 在只读路径 flush 未提交默认阶段**
  （`database_workflows.py:359-370`）：可能污染同线程后续事务（副作用幂等，低危）。

### 已排查排除

- PySide6 6.10.1 会把普通回调排队到 GUI 线程，`run_dispatch` 跨线程信号**不构成 UI 崩溃**。
- 并行步骤写库依赖 scoped_session per-thread + WAL/busy_timeout，未发现死锁。

---

## 2. 效率

DB 层批处理整体较优（skip-on-success、日志汇总、prev-step-status 预取均到位），
主要开销集中两处：

### E-1（最高影响）watcher 事件模式下仍每 cooldown 全树扫描

- 位置：`src/engine_core/watcher.py:375-385`
- 现象：observer（watchdog）模式下 `self._dirty.wait(timeout=cooldown)` 超时后，
  循环**无条件**执行 `scan_folder_mtimes_result` —— 对整棵监听树递归 `os.scandir` +
  逐文件 `stat`。即使没有任何文件事件，空闲时也每 cooldown（默认 8s）全树扫一次；
  每个启用的监听各有一个该线程。
- 影响：高频写输出时近乎持续全树扫描，重磁盘/CPU。observer 模式下 watchdog 本身已给
  出具体变更路径，mtime 扫描应仅在真实事件后触发。

### E-2 切换工作流在主线程做 6+ 次同步 SQLite 读

- 位置：`src/ui/main_window.py:228-241,435` + `step_table/panel.py:181-183` +
  `workbench_board.py:521`
- 现象：一次切换触发 `get_steps_by_workflow` **3 次**、`get_workflow_by_id` 2 次、
  `list_stages` 2 次等，重复 `SELECT` 同一张 steps 表。
- 影响：每次切换 UI 冻结与步骤数成正比。

### E-3 运行完成后的历史重载仍在主线程

- 位置：`src/ui/run_lifecycle_controller.py:224-226`
- 现象：`_async_load_history` 仅用 `QTimer.singleShot(0)` 延迟，实际仍在主线程执行
  `load_history` + `get_step_log_summary_by_runs`（~30-80ms）。
- 影响：监听频繁触发时反复出现间歇卡顿。

### E-4 其余（低优先）

- **历史分页排序用不上索引**（`database_runs.py:120-121,145`）：`ORDER BY id` 匹配不上
  `(workflow_id, start_time, id)` 复合索引，每页 scan+sort，随历史深度变贵。
- **`_all_histories` 无界增长**（`ui/run_history.py:186,233-245`）：长会话多历史时
  每次筛选/搜索全串遍历。
- **`has_cross_workflow_cycle` 每 run 全表扫两个表**（`database.py:745-760`）。
- **`_repair_legacy_watch_configurations` 启动 N+1**（`database.py:277-284`）。

---

## 3. 精简

### S-1 4× 相同 log-dir 引导块

- 位置：`executors/excel_executor.py:162-167`、`powerbi_executor.py:174-178` 与
  `:330-336`、`python_executor.py:264-271`
- 内容：lazy-import `LOG_DIR` + 时间戳目录 + `mkdir` + stdout/stderr 路径推导，完全一致。
- 建议：提取为 `BaseExecutor.build_log_dir()`。

### S-2 阶段元信息 3 层间接

- 位置：纯逻辑在 `engine_core/stages.py`；`run_orchestration.py:572,599` 再包一层
  又调回 engine；`engine.py:664,678` 再薄代理（wrapper 套 wrapper 调同一函数）。
- 建议：删除 `run_orchestration` 那层，调用方直接指向 `stages.*` 或 engine 方法。

### S-3 6 个近相同运行按钮

- 位置：`ui/run_control.py:181-206`（`_run_all/_run_from/_run_only/_run_stage/
  _run_from_stage/_retry_failed`）。
- 建议：收敛为一个 `_run(mode, param)`。

### S-4 其余

- `msg_information/_warning/_critical` 三个 helper（`ui/theme.py:885-909`）只差图标常量。
- `database_runs.py:70` 内联复刻 `generate_uid`（`database.py:697`）。
- 主题色值在 COLORS/DARK 与 STATUS/TYPE/LOG_LEVEL 6 组 dict 手写同步（已漂移过一次）。
- `engine.py:488-489` 残留引用已删方法的 checklist 注释。
- `engine.py` ~35 个薄委托 + `run_orchestration` 双跳：**有意保留**（monkeypatch 语义），
  仅提示双跳可收敛，非紧急。

---

## 4. 修复优先级（P0–P3）

| 优先级 | 事项 | 角度 | 预计 |
|---|---|---|---|
| P0 | force_stop 误杀实时运行 + 回归测试 | 稳定性 | ~0.5d |
| P0 | 并行取消 zip 错位 / 进度少计 + 回归测试 | 稳定性 | ~0.5d |
| P1 | watcher observer 模式空闲不扫描（E-1） | 效率 | ~0.25d |
| P1 | 合并切换工作流重复 DB 读（E-2） | 效率 | ~0.25d |
| P1 | 历史重载移后台线程（E-3） | 效率 | ~0.25d |
| P2 | log-dir 引导块提取 / 按钮收敛 / generate_uid 复用 | 精简 | ~0.25d |
| P3 | E-4 索引对齐 / _all_histories / 注释清理 | 效率/整洁 | 分散 |

## 5. 本版本暂缓（记录原因）

- **theme 色值派生重构**：视觉回归风险高且难自动断言，属"降漂移"投资，不在 5.0.5 引入。
- **watch 触发改独立线程**：涉及触发语义/并发取消/嵌套运行，行为面大，建议单独迭代。
- **深层子工作流 parent_run_id 修正**：数据准确性场景，随子工作流追踪需求一并处理。

## 6. 测试与发布

- 全量测试：`python -m pytest -q` → 522 passed, 2 skipped。
- 发布要求：P0–P3 修复后 code review 无问题 → 版本 `5.0.5`（patch，无破坏性变更）→
  `build_slim2.spec` 重新打包 + `--self-check` → commit + push。
