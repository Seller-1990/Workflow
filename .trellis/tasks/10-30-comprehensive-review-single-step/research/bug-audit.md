# Engine / Executors / Database / CLI 只读缺陷审查

日期：2026-10-30

## 范围与方法

- `main...HEAD` 在审查域内无提交差异；实际工作树差异为 `src/cli.py`、`src/engine.py`、`src/engine_core/run_orchestration.py`、`src/engine_core/selection.py` 的区间运行实现。
- 逐行读取上述差异及其完整函数，并沿调用链审查 engine/scheduler/executor、数据库 CRUD/导入导出/迁移、CLI 参数与通知；为跨层风险确认读取了 `risk_path_review.py` 和 UI/CLI 两个入口。
- 按要求未派生 agent，依次完成 5 个正确性角度、3 个清理角度、altitude、conventions 及末轮 sweep；未修改源码，未执行会写数据库或产生缓存的测试。本报告是唯一持久化文件。
- `CONFIRMED` 表示可由代码直接给出触发输入与错误结果；`PLAUSIBLE` 表示机制确定，但需要数据库/进程异常或特定时序。未把仅有理论可能但当前生产调用不可达的候选列入结果。

## 已核实发现（按严重度排序）

### 1. CONFIRMED（高）— 启动窗口强制停止只改数据库，不停止实际执行

- 位置：`src/engine.py:263-288`，关键分支 `src/engine.py:264`。
- 证据：`_begin_run()` 已创建 running 记录、但 `_active_run_ids.add()` 尚未执行时，目标 ID 不在活动集合，`force_stop_run()` 走孤儿清理而不设置 `_cancelled`。
- 后果：数据库被写成 cancelled，工作流却继续执行，最终状态还可能被正常收尾覆盖；用户会以为副作用已停止。
- 最小修复：在 `_begin_run()` 与活动 ID 注册之间建立可识别的启动状态并传播取消，不能仅扩大 DB 强制终态写入；补启动点前后 race 回归测试。

### 2. CONFIRMED（高）— 步骤清理失败后仍写 RunHistory 终态，状态可永久分裂

- 位置：`src/database_runs.py:325-355`、`src/engine_core/run_finalization.py:54-66`。
- 证据：清理函数吞掉所有数据库异常并返回 `0`，与“确实没有待清理行”不可区分；调用方忽略结果并继续写运行终态。
- 后果：清理时 SQLite 锁/IO 失败、随后运行记录写成功时，RunHistory 为 success/failure/cancelled，关联 StepLog 仍为 running/pending。
- 最小修复：清理结果显式区分成功与失败；保持既有终态可用性策略时至少记录明确的不一致状态并提供可重试收敛，不得把失败静默当作零行。

### 3. CONFIRMED（高）— 引擎在选步前按全工作流校验，安全局部运行被无关步骤阻断

- 位置：`src/engine_core/run_orchestration.py:277-298`，关键调用 `src/engine_core/run_orchestration.py:282-286`。
- 证据：`build_run_plan(workflow, all_steps)` 和 `evaluate_run_plan()` 在 `_select_steps()` 之前执行。
- 后果：只运行无风险步骤 A，未选中的导入步骤 B 含未确认绝对路径时，A 仍无法启动；区间、单阶段同样受影响。
- 最小修复：从同一不可变快照先确定实际步骤，再评估所选范围的风险；同时保留引擎兜底与变更后确认失效。

### 4. CONFIRMED（高）— 局部确认仍写入全工作流信任，扩大后续运行授权

- 位置：`src/ui/run_dispatch.py:39-65`、`src/cli.py:528-553`、`src/database.py:741-752`。
- 证据：两个入口均从全工作流步骤构造风险计划；`confirm_risky_paths(workflow_id)` 也收集全部步骤并写全局 digest，没有运行范围或步骤集合参数。
- 后果：用户为单步/区间运行确认弹窗时，也确认了未选中的风险步骤；之后全流程运行不再提示这些路径。
- 最小修复：定义范围化确认记录及其与全局 revision/digest 的组合校验；UI 只展示所选风险，持久化授权不能暗中扩大。不能仅缩小弹窗列表而继续写全量信任。

### 5. CONFIRMED（高）— CLI 在引擎复位取消标志后判断取消，取消被通知为 failure

- 位置：`src/cli.py:428-444`，复位点 `src/engine_core/run_orchestration.py:182-192`。
- 证据：每次顶层运行收尾都会恢复 `_running=False` 并将 `_cancelled=False`；同步 `engine.run()` 返回后，`self.engine.is_cancelled` 因而必为 False。
- 后果：SIGINT/协作取消后跳过 cancelled 分支，发送 `success=False, cancelled=False` 的通知，状态变成 failure，且不打印该分支的“运行已取消”。
- 最小修复：从本次运行的 `workflow_finished` 状态或 RunHistory 终态决定通知，不读取已复位的瞬时取消标志。

### 6. CONFIRMED（中高）— 运行初始化失败遗留无人持有的 pending RunHistory

- 位置：`src/engine_core/lifecycle.py:68-93`、`src/engine_core/run_orchestration.py:319-321`。
- 证据：RunHistory 先以 pending 提交，再创建日志目录、更新 running；若 `mkdir()` 或 running 更新失败，`ctx` 未返回，编排层的 `run_history_id` 仍为 None，收尾函数直接跳过。
- 后果：磁盘满/权限失败或 DB 写失败时留下永久 pending 记录，且当前收尾不知道该记录 ID。
- 最小修复：让初始化失败返回/携带已创建记录 ID，并在同一受控收尾中取消它；或在创建 running 记录前完成可失败的目录准备。

### 7. PLAUSIBLE（中高）— StepLog 创建会重试结果未知的 commit，可能重复记录同一步骤

- 位置：`src/database_runs.py:190-230`，关键 `src/database_runs.py:211-218`。
- 证据：所有 commit 异常都进入最多三次的新行创建，没有先按运行/步骤检查是否已提交。
- 触发确认：需要连接异常发生在数据库已接受 commit、客户端却收到失败的结果未知窗口。
- 后果：同一 run/step 出现多条 pending/running 日志，重试后状态覆盖与历史统计失真。
- 最小修复：对提交结果不确定的异常先重读/协调，使用唯一执行标识或幂等 upsert；不要对所有异常盲目重新 INSERT。

### 8. PLAUSIBLE（中高）— 超时/取消清理存在无超时 `proc.wait()`，可永久卡住

- 位置：`src/executors/python_executor.py:186-199`、`src/executors/bat_executor.py:105-118`。
- 证据：`communicate(timeout=3)` 超时后两个实现都直接调用无 timeout 的 `proc.wait()`；`kill_process_tree()` 自身吞掉终止失败，并不保证进程已退出。
- 触发确认：需要 taskkill/kill 失败、权限不足或进程/管道异常导致终止未完成。
- 后果：原本的超时或取消路径反而无限等待，运行无法收尾。
- 最小修复：清理全程使用有界等待；超时后返回带后台风险的 non-retryable 结果，不得在兜底中退化为无限阻塞。

### 9. CONFIRMED（中）— 后台孙进程持有管道超过 10 秒时，日志线程仍在写而文件被关闭

- 位置：`src/executors/python_executor.py:381-401`、`src/executors/bat_executor.py:249-269`。
- 证据：主进程退出后仅 `join(timeout=10)`；孙进程继承 stdout/stderr 写端可让读取线程继续存活。随后 `with open(...)` 退出关闭文件，读取线程之后的写入失败或丢失。
- 后果：脚本启动长寿命子进程并正常退出时，后续输出丢失，ExecutorResult 却仍按主进程退出码报告成功；代码注释所述“进程即将退出”在这一场景不成立。
- 最小修复：明确进程树/输出所有权；超时后安全关闭读取端或继续由受管线程持有文件，避免关闭仍被使用的句柄。

### 10. CONFIRMED（中）— `CLIEngine.close()` 是空操作，辅助线程池从不关闭

- 位置：`src/cli.py:498-499`，资源创建点 `src/engine.py:191`。
- 证据：每个 CLIEngine 都创建带 ThreadPoolExecutor 的 WorkflowEngine；`cmd_run()`、`cmd_retry()`、`cmd_dry_run()` 均调用空的 `close()`，没有 `engine.shutdown()`。
- 后果：后台日志清理仍在运行时，解释器退出阶段需等待线程池任务，可能延迟 CLI 退出；长寿命调用方重复创建引擎还会累积线程资源。
- 最小修复：`close()` 幂等地调用 `engine.shutdown()` 并清理会话；等待策略须先让已提交收尾任务有序结束。

### 11. CONFIRMED（中）— pending 孤儿运行无法被强制取消，却被报告为已终态

- 位置：`src/engine_core/force_stop.py:43-80`，关键条件 `src/engine_core/force_stop.py:76`。
- 证据：pending/读取失败状态会先清理步骤，再仅以 `_condition_status="running"` 更新；pending 不匹配返回 None，随后被当成“正常流程已写终态”。
- 后果：启动失败或崩溃留下的 pending 记录保持 pending，调用方却收到 already_terminal 语义。
- 最小修复：对 pending 使用合法的条件迁移（pending/running → cancelled）；不存在或已是真正终态应分别返回，不能混为一类。

### 12. CONFIRMED（中）— “最近 20 次”步骤日志仍按 start_time 选集，可能漏掉真正最新运行

- 位置：`src/database_runs.py:242-264`，关键 `src/database_runs.py:252`。
- 证据：主运行历史契约已统一按 id DESC，但该辅助查询仍按 `start_time DESC, id DESC` 限制最近 20 个 run。
- 后果：系统时钟回拨或修复时间戳后，最新插入运行被排到 20 名之外，`open_step_log()` 会从旧运行打开日志。
- 最小修复：子查询按 `RunHistory.id DESC` 选最近 N 个，再按 run_history_id/id 明确排序；补逆序时间戳回归测试。

### 13. CONFIRMED（中）— 导入不校验 retry/timeout 数值范围，负 retry_count 让步骤一次也不执行

- 位置：`src/database_import_validation.py:198-216`，消费点 `src/engine_core/step_execution.py:380-420`。
- 证据：导入只检查整数，不限制非负值或合理上限；执行时 `range(step.retry_count + 1)` 对 `retry_count=-1` 是空循环，直接生成失败结果，`last_error=None`。
- 后果：合法通过导入校验的 JSON 可让步骤不调用执行器就失败；负 timeout 也会变成异常的即时超时语义。
- 最小修复：导入和数据库更新边界统一校验 retry_count ≥ 0、timeout 为正或表示默认的 None，并给具体字段错误。

### 14. CONFIRMED（中低）— 未创建新 RunHistory 的 CLI 调用会复用上一次运行的通知元数据

- 位置：`src/cli.py:435-444`、辅助函数 `src/cli.py:463-477`。
- 证据：无论本次是否产生 run_id，都读取工作流最新历史并覆盖 `_last_run_id/_last_start_time/...`；风险拦截、启动失败或“重试但没有失败步骤”都可能没有新运行。
- 后果：本次失败/空操作通知携带历史运行的编号、起止时间和耗时，误导追踪。
- 最小修复：仅当元数据能对应本次 run_id 时补充；没有本次运行时明确标记“未启动/无步骤”，不要回退到任意最新历史。

### 15. CONFIRMED（中低）— CLI 互斥运行模式可叠加并静默按优先级改义

- 位置：`src/cli.py:570-587`、参数声明 `src/cli.py:835-844`。
- 证据：stage/from-stage/from-step/only-step 是独立参数，没有 argparse mutually exclusive group。
- 后果：`run wf --only A --from B` 实际从 B 运行到末尾而非只运行 A；再加 `--stage S` 又静默改成单阶段，自动化传参错误不会失败。
- 最小修复：将互斥模式参数放入同一 argparse 组，并保留 `--to` 必须搭配 `--from` 的校验。

## 末轮排除 / 未采信候选

- **并行结果缺失可被判成功（needs production evidence，未列入正式结果）**：`handle_batch_results()` 确有 `continue`，但当前 scheduler 对取消补占位，异常也转换或抛出；正常生产路径没有已证实的缺项来源。不能仅凭测试替身可构造就宣称现行运行会误成功。
- **CLI notify_on_complete/notify_on_error 被调用方丢弃（REFUTED）**：这些参数在 CLIEngine 内部会传递；当前命令行没有对应输入参数，不存在“用户提供的值被丢弃”的可复现路径。
- **子工作流 0.2 秒宽限后返回后台风险（REFUTED 作为单独缺陷）**：代码显式设置 cancelled/non_retryable/orphan_risk/background_risk，符合现有风险可见契约；真正的问题是父终态与子后台执行的展示/重试策略，不应误报为无标记泄漏。
- **纯 cleanup/复用项未挤占缺陷名额**：区间选步存在与其他模式的映射重复，但参数兼容分支有测试替身契约依据，不能为“简化”删除。无适用仓库级 CLAUDE.md 的明确规则违例可引用。
- 全量 pytest 未运行：本任务是只读审查且只能持久化指定报告；未把历史通过记录当成本轮验证结果。
