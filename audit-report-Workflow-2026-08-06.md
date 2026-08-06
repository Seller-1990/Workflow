# Fuck My Shit Mountain Audit Report

**Project:** 工作流管理系统 (Workflow Manager)
**Audit mode:** full
**Date:** 2026-08-06
**Reviewer:** Claude Fable 5 (Opus 4.6)

---

## 1. Executive Summary

工作流管理系统 v5.0.5 是一个成熟度较高的桌面端工作流编排工具，代码量约 28,500 行（108 个源文件），配套 76 个测试文件（529 passed）。项目展示了清晰的安全意识（Webhook URL 脱敏、进程隔离、AST 扫描守卫）和良好的架构分层意愿（engine_core/ 子系统抽取、database_*.py 拆分、UI 委托模式）。

主要风险集中在三个方向：(1) **核心执行路径缺乏测试覆盖** — run_orchestration.py（730 行）和 step_execution.py（583 行）这两个最关键的运行编排模块零测试覆盖；(2) **稳定性边界条件** — 单步异常未结构化上报、force_stop 竞态写入、线程池嵌套耗尽；(3) **长期运行内存管理** — scoped_session 身份映射在桌面应用长期运行中无限增长。安全方面整体良好，无 Critical 级漏洞，仅 Power BI REST 异常中的 token 泄露和导入路径遍历仅告警两处 Medium 值得关注。

### Score Dashboard

```
Security        ████████░░  8.0  A   严格 URL 策略/进程隔离；PowerBI token 可能泄露到异常消息
Stability       ██████░░░░  6.0  B   并行取消完善；单步异常上报缺失、force_stop 竞态
Performance     ███████░░░  7.0  A   WAL/索引设计好；scoped_session 内存无上限、UI 同步查询
Testing         █████░░░░░  5.5  B   529 tests + AST 守卫；核心编排路径零覆盖
Maintainability ██████░░░░  6.0  B   分层清晰；main_window 86 方法、engine 62 方法仍为 god-class
Design          ██████░░░░  6.5  B   延迟导入打破循环但暴露边界不完整；Qt 耦合引擎
Release         ████████░░  8.0  A   CI + 自检 + schema 快照 + 版本门禁完善
─────────────────────────────────────
Overall         ██████░░░░  6.7  B
```

Each dimension scored 0.0–10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|----------|
| Critical | 0 | 0 | 0 |
| High | 6 | 5 | 1 |
| Medium | 14 | 12 | 2 |
| Low | 12 | 12 | 0 |
| Info | 3 | 3 | 0 |
| **Total** | **35** | **32** | **3** |

---

## 2. Project Map

**入口点**: `src/main.py` (GUI), `src/cli.py` (CLI), `_import_and_run.py` (批量脚本)

**核心架构**:
- **WorkflowEngine** (`src/engine.py`) — QObject，编排引擎；通过委托模式下沉到 `engine_core/` 子系统
- **engine_core/** — 7 个模块：scheduler (并行调度)、run_orchestration (运行主流程)、step_execution (单步生命周期)、watcher (文件监听)、watch_manager (多 watcher 管理)、cancel、batch、lifecycle、stages、preview、log_cleanup、notification、force_stop
- **database.py** 门面 + `database_*.py` 拆分模块 — SQLAlchemy ORM + SQLite WAL
- **executors/** — Python/Excel/PowerBI/子工作流执行器；`runtime/process_runner.py` 为进程边界
- **ui/** — PySide6 GUI 委托模式（main_window_setup, run_dispatch, panel_controller 等）

**数据流**: UI/CLI → Engine.run_*() → run_orchestration → batch → step_execution → executor → process_runner → subprocess

**安全边界**: webhook_url_policy (URL 白名单)、import_export_security (秘密扫描)、process_runner (shell=True 禁止)、python_executor (env 清洗)

---

## 3. Top Risks

| # | 标题 | 严重度 | 摘要 |
|---|------|--------|------|
| 1 | 核心运行编排模块零测试覆盖 | High | run_orchestration.py + step_execution.py 共 1313 行无任何测试 |
| 2 | 单步异常导致运行无结构化错误上报 | High | execute_steps 中无 try/except 包裹单步调用 |
| 3 | 线程池嵌套耗尽可致吞吐退化 | High | 3+ 层子工作流嵌套可耗尽共享线程池 |
| 4 | force_stop 竞态写入覆盖正常终态 | Medium | 无条件 UPDATE 可将 success 覆盖为 cancelled |
| 5 | scoped_session 身份映射长期无限增长 | Medium | 桌面应用连续运行数日后内存稳步上升 |
| 6 | 导入路径遍历仅告警不阻止执行 | Medium | 恶意 JSON 可引用任意路径脚本被执行 |
| 7 | Power BI REST 异常可暴露 Bearer token | Medium | 异常消息未脱敏即展示到 UI/日志 |
| 8 | 子进程无 stdin 策略致 input() 永挂 | Medium | 用户脚本调用 input() 阻塞至超时 |
| 9 | UI 同步 DB 查询阻塞主线程 | Medium | 切换工作流时 load_history 同步查询冻结 UI |
| 10 | 日志清理无磁盘容量上限 | Medium | 高频触发工作流 30 天可积累数百 MB 日志 |

---

## 4. Detailed Findings

### Finding: 核心运行编排模块零测试覆盖

- Severity: High
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: engine_core/run_orchestration.py, engine_core/step_execution.py
- Evidence:
  - File: src/engine_core/run_orchestration.py (730 行, 21 个函数)
  - File: src/engine_core/step_execution.py (583 行)
  - Relevant behavior: 工作流运行的完整编排生命周期和单步执行重试逻辑
- Problem: 这两个模块是工作流执行的核心路径，任何 bug 都会直接影响所有用户。当前无任何专门测试文件覆盖它们。
- Why it matters: 未测试的代码在重构时极易引入回归，且已发现 Finding #2 的异常传播 bug 正是因为无测试才留存。
- Realistic failure scenario: 重构 execute_steps 的批次逻辑后引入异常吞没 bug，所有并行步骤失败但 UI 显示成功。
- Minimal fix: 为 run_orchestration 和 step_execution 各写 10-15 个 pytest 用例覆盖正常/取消/异常路径。
- Better long-term fix: 引入覆盖率门禁（如 pytest-cov --fail-under=60%）并标注关键模块。
- Regression test suggestion: 测试 execute_steps 在 mkdir 失败时是否正确汇报 failed_details。
- Estimated effort: 2-3 天

---

### Finding: 单步异常导致运行无结构化错误上报

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: engine_core/run_orchestration.py:537
- Evidence:
  - File: src/engine_core/run_orchestration.py:537-543
  - Function: execute_steps (单步串行路径)
  - Relevant behavior: _execute_single_step 抛出异常时直接传播
- Problem: 如果 _execute_single_step 因 step_log_id 为 None（如磁盘满）抛异常，execute_steps 无 try/except 捕获。异常传播到 run_workflow 的 except 分支仅打印 "未知错误"，不触发 _emit_failed_details 也不递增 completed_steps。
- Why it matters: 用户在 UI 中看不到结构化的失败步骤摘要，只有一行模糊的 "未知错误" 日志。
- Realistic failure scenario: 磁盘满导致 mkdir 失败 → step_log_id=None → 异常传播 → run_workflow except → 用户仅看到 "未知错误" 无法定位是哪个步骤出了什么问题。
- Minimal fix: 在 execute_steps 的单步调用处加 try/except，构造 failure StepResult 并走正常 append_failed_detail 路径。
- Regression test suggestion: Mock mkdir 抛 OSError，验证 error_details signal 包含步骤名和错误摘要。
- Estimated effort: 30 分钟

---

### Finding: 线程池嵌套耗尽可致吞吐退化

- Severity: High
- Confidence: Medium
- Category: Stability
- Status: Confirmed
- Affected area: engine.py:184-185, engine_core/scheduler.py
- Evidence:
  - File: src/engine.py:184-185 (pool size = min(32, cpu_count + 4))
  - File: src/engine_core/scheduler.py:112 (sliding window)
  - Relevant behavior: 父工作流步骤占用池线程调用 run_sub_workflow，子工作流再需要池线程
- Problem: 滑动窗口解决了步骤内阻塞问题（M6），但父工作流步骤本身仍占据一个池线程。3+ 层嵌套 + 每层多并行步骤可耗尽池（如 4 核机器 pool=8，3 层×3 并行=9 线程）。
- Why it matters: 不会死锁（滑动窗口保证），但吞吐退化为近串行，用户感知到并行"失效"。
- Realistic failure scenario: 用户配置月度报表工作流调用 3 个子工作流，每个子工作流有 4 个并行步骤 → 池全满 → 吞吐从预期 12 并行降至实际 2-3 并行。
- Minimal fix: 在 run_sub_workflow 中设 max_workers = max(1, pool_remaining / 2) 限制子工作流并行度。
- Better long-term fix: 按工作流层级动态分配并行度配额，或使用 per-workflow-level 池。
- Regression test suggestion: Mock 3 层嵌套运行，验证所有步骤最终完成（无超时）。
- Estimated effort: 2 小时

---

### Finding: force_stop 竞态写入覆盖正常终态

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: engine_core/force_stop.py:72-77
- Evidence:
  - File: src/engine_core/force_stop.py:72-77
  - Relevant behavior: 无条件 UPDATE 将 status 写为 cancelled
- Problem: force_cancel_run_record 读取 status 为 running 后执行 UPDATE，但正常 finalization 可能在读取与写入之间已将 status 改为 success。无条件 UPDATE 覆盖了合法终态。
- Realistic failure scenario: 运行刚好成功的瞬间用户点击 "强制停止" → status 被改为 cancelled → UI 显示"已取消"但实际脚本已成功执行。
- Minimal fix: 使用条件 UPDATE: `UPDATE run_histories SET status='cancelled' WHERE id=? AND status='running'`，检查 affected rows。
- Regression test suggestion: 并发调用 finalize_run(success) 和 force_cancel_run_record，验证最终 status 为 success。
- Estimated effort: 30 分钟

---

### Finding: scoped_session 身份映射长期无限增长

- Severity: Medium
- Confidence: High
- Category: Performance
- Status: Confirmed
- Affected area: src/database.py:650-678
- Evidence:
  - File: src/database.py:650-678 (get_session 注释明确不调 remove)
  - Relevant behavior: 桌面应用中 scoped_session 在正常路径不 remove()
- Problem: 用户可能连续数天不关闭应用，期间所有查询过的 ORM 对象（RunHistory、StepLog 等）累积在 session identity map 中，导致内存稳步增长。
- Realistic failure scenario: 应用运行 7 天，每日运行 20 个工作流（各 10 步）→ ~1400 RunHistory + 14000 StepLog 对象常驻内存 → 约 50-100MB 额外内存占用。
- Minimal fix: 在 UI 线程的批量读取后（如 load_history 完成）调用 `session.expire_all()` 释放引用。
- Better long-term fix: 只读查询使用短生命周期 session（with get_readonly_session()），写操作保持当前 scoped_session。
- Regression test suggestion: 循环创建 1000 个 RunHistory 后检查 session.identity_map 大小未超预期阈值。
- Estimated effort: 2 小时

---

### Finding: 导入路径遍历仅告警不阻止执行

- Severity: Medium
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: src/database_import_validation.py:65-73
- Evidence:
  - File: src/database_import_validation.py:65-73 (mark_risky_import_paths)
  - Relevant behavior: 绝对路径或 `..` 路径仅追加告警到 description，不阻止导入或执行
- Problem: 攻击者可制作恶意 workflow JSON，指定 script_path 为系统任意位置的脚本。导入后应用会在执行时运行该脚本，获得当前用户完整权限。
- Realistic failure scenario: 攻击者分享包含 `"script_path": "C:\\tools\\keylogger.py"` 的 workflow JSON → 用户导入 → 运行该工作流 → 恶意脚本以用户权限执行。
- Minimal fix: 首次运行含 risky path 的导入工作流时弹出确认对话框，明确列出被标记的路径。
- Better long-term fix: 限制 script_path 只能在指定工作区目录内或用户显式授权的目录列表内。
- Regression test suggestion: 导入含 `../../etc/passwd` 路径的 JSON，验证执行时被拒绝或需确认。
- Estimated effort: 1 小时

---

### Finding: Power BI REST 异常可暴露 Bearer token

- Severity: Medium
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: src/executors/powerbi_rest.py:145,160
- Evidence:
  - File: src/executors/powerbi_rest.py:145
  - Relevant behavior: RequestException 转 PowerBIRestError 时直接嵌入异常字符串
- Problem: requests 库在某些连接错误场景（如重定向链）可能在异常消息中包含完整的 Authorization 头。此处无脱敏直接传递到 error_message，最终显示在 UI 和日志中。
- Realistic failure scenario: Power BI API 返回 302 重定向 → requests 跟随时失败 → 异常消息包含 `Bearer eyJ...` → token 出现在步骤日志和运行历史中。
- Minimal fix: 在构造 PowerBIRestError 前用 `re.sub(r'Bearer\s+[^\s]+', 'Bearer <redacted>', str(exc))` 脱敏。
- Regression test suggestion: Mock 一个包含 Bearer token 的 RequestException，验证错误消息不含原始 token。
- Estimated effort: 15 分钟

---

### Finding: 子进程无 stdin 策略致 input() 永挂

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: src/runtime/process_runner.py:83-87
- Evidence:
  - File: src/runtime/process_runner.py:83-87 (start_process)
  - Relevant behavior: 未设置 stdin=DEVNULL，子进程可从 stdin 读取
- Problem: 如果用户脚本中调用了 `input()` 或 `sys.stdin.readline()`，子进程将永久阻塞等待输入（因为没有终端连接），直到超时才能结束。
- Realistic failure scenario: 用户调试时在脚本中留了 `input("按回车继续")` → 步骤挂 7200 秒后才超时报错 → 用户以为系统卡死。
- Minimal fix: 在 `build_subprocess_kwargs` 中默认设置 `stdin=subprocess.DEVNULL`。
- Regression test suggestion: 运行一个包含 `input()` 的脚本，验证进程立即收到 EOF 而非永挂。
- Estimated effort: 10 分钟

---

### Finding: UI 同步 DB 查询阻塞主线程

- Severity: Medium
- Confidence: High
- Category: Performance
- Status: Confirmed
- Affected area: src/ui/run_history.py:186-192
- Evidence:
  - File: src/ui/run_history.py:186-192 (load_history 同步路径)
  - Relevant behavior: 切换工作流时在 UI 线程执行 DB 查询
- Problem: load_history() 在 UI 线程同步执行 get_run_histories_by_workflow + get_step_log_summary_by_runs。async 版本存在但部分调用点仍使用同步路径。
- Realistic failure scenario: 用户点击含 100 条运行历史的工作流 → UI 冻结 50-200ms（磁盘 IO 延迟时更长）。
- Minimal fix: 将所有 load_history() 调用替换为已有的 load_history_async()。
- Regression test suggestion: Mock DB 延迟 500ms，验证 UI 主循环未阻塞（event processing 正常）。
- Estimated effort: 30 分钟

---

### Finding: 日志清理无磁盘容量上限

- Severity: Medium
- Confidence: High
- Category: Performance
- Status: Confirmed
- Affected area: src/engine_core/log_cleanup.py
- Evidence:
  - File: src/engine_core/log_cleanup.py:15-58
  - Relevant behavior: 仅按时间（log_retention_days=30）清理，无数量/大小上限
- Problem: 高频触发的工作流（如文件监听每 5 分钟触发一次）30 天内可积累 8640 个日志目录，每个含 stdout/stderr 文件。
- Realistic failure scenario: 文件监听工作流每 5 分钟触发，每次产生 100KB 日志 → 30 天 = 8640 × 100KB ≈ 864MB 磁盘占用，无上限。
- Minimal fix: 添加次级清理规则：单工作流日志目录超过 500 个或 500MB 时删除最旧的。
- Regression test suggestion: 创建 600 个假日志目录，验证清理后不超过 500 个。
- Estimated effort: 1 小时

---

### Finding: Engine 耦合 PySide6.QObject

- Severity: Medium
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: src/engine.py:65
- Evidence:
  - File: src/engine.py:65 (`from PySide6.QtCore import QObject, Signal, Slot`)
  - Relevant behavior: WorkflowEngine 继承 QObject，CLI 模式也需要安装 PySide6
- Problem: 引擎与 Qt 框架紧密耦合，无法在无 Qt 环境下单独测试或运行 CLI。
- Realistic failure scenario: 无——功能性正常；但阻碍了未来将引擎提取为独立库或添加 Web API 的可能。
- Minimal fix: 暂不修，标记为长期重构目标。
- Better long-term fix: 抽取 callback 协议接口，Qt Signal 层作为薄包装。
- Regression test suggestion: 验证 engine 核心逻辑可在无 QApplication 下执行（mock QObject）。
- Estimated effort: 3-5 天（重构）

---

### Finding: Watchdog observer 部分调度失败时泄露

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: src/engine_core/watcher.py:304-312
- Evidence:
  - File: src/engine_core/watcher.py:304-312
  - Relevant behavior: 部分 folder schedule 成功后另一个失败，observer 设为 None 但未 stop
- Problem: 已创建的 Observer 对象和已调度的 watch 泄露在内存中，不被回收也不响应停止。
- Minimal fix: 在 `self._observer = None` 之前调用 `observer.unschedule_all()` 并 `observer.stop()`。
- Regression test suggestion: Mock 第二个 folder 的 schedule 抛异常，验证 observer 被正确清理。
- Estimated effort: 15 分钟

---

### Finding: watch_manager 无锁保护 watchers 字典

- Severity: Medium
- Confidence: Medium
- Category: Stability
- Status: Suspected
- Affected area: src/engine_core/watch_manager.py:115-118
- Evidence:
  - File: src/engine_core/watch_manager.py:115-118
  - Relevant behavior: start_watch 中 stop → check → create 序列无原子保护
- Problem: 并发调用 start_watch（如配置保存 + restore_watches 同时发生）可能导致 watchers 字典状态不一致。
- Realistic failure scenario: 应用启动时 restore_watches 遍历所有工作流，同时用户快速编辑并保存某个工作流的监听配置 → 两个线程竞争同一 workflow_id 的 watcher 条目。
- Minimal fix: 添加 threading.Lock 保护 watchers 字典的读写。
- Regression test suggestion: 两个线程并发调用 start_watch 同一 workflow_id，验证最终只有一个 watcher 存活。
- Estimated effort: 30 分钟

---

### Finding: 通知提交在 executor 关闭后静默失败

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: src/engine_core/run_orchestration.py:150-161
- Evidence:
  - File: src/engine_core/run_orchestration.py:150-161
  - Relevant behavior: executor.submit 在 shutdown 后抛 RuntimeError 被 except 吞掉
- Problem: 用户在工作流完成瞬间关闭应用 → 通知未发送且无任何提示。
- Minimal fix: 检查 `engine._executor is not None` 后再 submit，或在 shutdown 前同步发送待处理通知。
- Regression test suggestion: Mock executor=None，验证 emit_run_completion 不抛异常且记录 warning。
- Estimated effort: 15 分钟

---

### Finding: mtime 扫描无深度限制阻塞 stop

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: src/engine_core/watcher.py:24
- Evidence:
  - File: src/engine_core/watcher.py:24 (`MTIME_SCAN_MAX_DEPTH: int | None = None`)
  - Relevant behavior: 扫描深目录树（如 node_modules）可耗时 10 秒
- Problem: 扫描期间 watcher 线程阻塞，无法响应 stop 事件。stop_watch 的 1 秒 join timeout 会超时。
- Minimal fix: 在扫描循环中检查 `self._stop.is_set()`，或设置合理默认 max_depth=10。
- Regression test suggestion: 监听含 10000 个子目录的路径，验证 stop 在 2 秒内返回。
- Estimated effort: 30 分钟

---

## 5. Security Concerns

| # | Issue | Severity | File |
|---|-------|----------|------|
| S1 | Power BI REST 异常暴露 Bearer token | Medium | powerbi_rest.py:145 |
| S2 | 导入路径遍历仅告警不阻止 | Medium | database_import_validation.py:65 |
| S3 | 网络异常可能泄露内部拓扑信息 | Low | notifier.py:229 |
| S4 | 环境变量可控 CA bundle 路径 | Low | tls_ca.py:35-38 |
| S5 | workspace_id/dataset_id 无 GUID 格式验证 | Low | powerbi_rest.py:134 |
| S6 | 无通知速率限制 | Low | notifier.py:282-284 |

**安全亮点**: webhook_url_policy 严格白名单、process_runner 禁止 shell=True、python_executor 清洗 PYTHON* 环境变量、import_export_security 递归扫描泄露秘密。

---

## 6. Stability Concerns

| # | Issue | Severity | File |
|---|-------|----------|------|
| ST1 | 单步异常未结构化上报 | High | run_orchestration.py:537 |
| ST2 | 线程池嵌套耗尽 | High | engine.py:184, scheduler.py |
| ST3 | force_stop 竞态覆盖终态 | Medium | force_stop.py:72 |
| ST4 | 子进程无 stdin=DEVNULL | Medium | process_runner.py:83 |
| ST5 | watchdog observer 泄露 | Medium | watcher.py:304 |
| ST6 | watch_manager 无锁 | Medium | watch_manager.py:115 |
| ST7 | 通知提交静默失败 | Medium | run_orchestration.py:150 |
| ST8 | mtime 扫描阻塞 stop | Medium | watcher.py:24 |
| ST9 | 清理线程与 shutdown 竞态 | Medium | run_orchestration.py:671 |

---

## 7. Performance Concerns

| # | Issue | Severity | File |
|---|-------|----------|------|
| P1 | scoped_session 身份映射无限增长 | Medium | database.py:650 |
| P2 | UI 同步 DB 查询 | Medium | run_history.py:186 |
| P3 | 日志清理无容量上限 | Medium | log_cleanup.py |
| P4 | 表格渲染无 setUpdatesEnabled | Low | run_history.py:301 |
| P5 | error_message 全文加载仅为计数 | Low | database_runs.py:313 |
| P6 | 循环检测加载全量 ORM 对象 | Low | database.py:745 |
| P7 | clear_run_histories 大 IN 子句 | Low | database_runs.py:178 |

---

## 8. Testing Gaps

| # | Issue | Severity | File |
|---|-------|----------|------|
| T1 | run_orchestration.py 零覆盖 | High | engine_core/run_orchestration.py |
| T2 | step_execution.py 零覆盖 | High | engine_core/step_execution.py |
| T3 | lifecycle.py 零覆盖 | High | engine_core/lifecycle.py |
| T4 | main_window.py 48+ 方法未测试 | Medium | ui/main_window.py |
| T5 | step_editor.py (949 行) 未测试 | Medium | ui/step_editor.py |
| T6 | run_history.py (590 行) 未测试 | Medium | ui/run_history.py |
| T7 | PowerBI COM 执行器未测试 | Medium | executors/powerbi_executor.py |

**测试亮点**: AST 扫描守卫测试（test_audit_risky_calls.py）、架构约束测试（test_dependency_manifest.py）、真实子进程 CLI 测试（test_cli_contracts.py）。

---

## 9. Maintainability Concerns

| # | Issue | Severity | File |
|---|-------|----------|------|
| MA1 | main_window.py 86 方法 991 行 | High | ui/main_window.py |
| MA2 | engine.py 62 方法（仍为 god-class 壳） | Medium | engine.py |
| MA3 | step_table/panel.py 71 方法 807 行 | Medium | ui/step_table/panel.py |
| MA4 | engine 耦合 PySide6.QObject | Medium | engine.py:65 |
| MA5 | 延迟导入暴露模块边界问题 | Low | engine_core/run_orchestration.py:46 |
| MA6 | 测试中重复 Dummy 类 | Low | tests/ |
| MA7 | 冗余 sys.path.insert | Low | ~70% 测试文件 |

---

## 10. Principles Compliance

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| File Size Limit (1.2) | 19 files >500 lines | Medium | main_window, engine, step_editor, cli |
| Single Responsibility (1.1) | 3 | Medium | MainWindow (86 methods), WorkflowEngine (62), StepTablePanel (71) |
| Dependency Inversion (2.4) | 1 | Medium | engine.py inherits QObject |
| No Timeout on External Call (10.4) | 1 | Medium | process_runner stdin hang |
| No Shared Mutable State Without Sync (5.4) | 1 | Medium | watch_manager.watchers dict |
| Fail-Fast (4.4) | 1 | Medium | import validation warns instead of rejecting |
| DRY (4.1) | 3 | Low | Test Dummy classes, executor DummyProc |

### Principles Respected

- **进程安全边界** — process_runner.py 严格禁止 shell=True、验证参数类型，是优秀的 fail-fast 实现
- **配置原子写入** — config.py 使用 tmp+replace 原子写入，避免崩溃时损坏配置
- **Schema 迁移快照** — database_migration_backup.py 在迁移前自动创建 SQLite 快照
- **WAL checkpoint** — 终态写入后主动 checkpoint，保证跨线程一致性
- **安全脱敏** — webhook_url_policy + import_export_security 共同确保 access_token 不泄露
- **架构约束测试** — AST 扫描禁止 shell=True / eval / 危险 subprocess 调用

---

## 11. Recommended Fix Order

### Fix Immediately (可在 1 天内完成，消除真实风险)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 1 | 单步异常加 try/except + failed_detail | 30min | 消除 silent failure |
| 2 | force_stop 条件 UPDATE | 30min | 消除竞态数据损坏 |
| 3 | powerbi_rest token 脱敏 | 15min | 消除凭证泄露 |
| 4 | stdin=DEVNULL 默认策略 | 10min | 消除脚本永挂 |
| 5 | watchdog observer 清理 | 15min | 消除资源泄露 |

### Fix Before Stable Release

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 6 | run_orchestration + step_execution 测试 | 2-3 天 | 核心路径覆盖 |
| 7 | load_history 改用 async | 30min | UI 流畅性 |
| 8 | 导入路径确认对话框 | 1h | 安全加固 |
| 9 | 日志清理加容量上限 | 1h | 磁盘保护 |
| 10 | watch_manager 加锁 | 30min | 并发安全 |
| 11 | session.expire_all() 策略 | 2h | 内存管理 |

### Schedule Later

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 12 | Engine 去 QObject 化 | 3-5 天 | 架构健康 |
| 13 | main_window 拆分 | 2-3 天 | 可维护性 |
| 14 | 通知速率限制 / 断路器 | 2h | 防止 API 封禁 |
| 15 | mtime 扫描可中断 + max_depth | 30min | 停止响应性 |

### Ignore for Now

- 网络异常内部信息泄露（Low，无外部攻击面）
- 环境变量可控 CA bundle（运维层面，非代码问题）
- pywinauto 包体积（功能需要，lazy import 已足够）
- 测试中冗余 sys.path.insert（不影响正确性）

---

## 12. Quick Wins

| Fix | 耗时 | 效果 |
|-----|------|------|
| `stdin=subprocess.DEVNULL` 加到 build_subprocess_kwargs | 10min | 杜绝 input() 永挂 |
| powerbi_rest.py 异常字符串 Bearer 脱敏 | 15min | 杜绝 token 泄露 |
| watcher.py observer 部分失败时 stop+unschedule_all | 15min | 杜绝 OS 句柄泄露 |
| force_stop.py UPDATE 加 WHERE status='running' | 30min | 杜绝竞态数据损坏 |
| run_orchestration.py:537 加 try/except 构造 failure result | 30min | 用户看到具体哪步失败 |
| run_history.py 所有 load_history() 改 load_history_async() | 30min | UI 不再冻结 |

---

## 13. Long-term Refactor Plan

### 1. Engine 去 Qt 化 (优先级: 长期)

- **动机**: 引擎继承 QObject 阻止了纯 CLI 测试、无 GUI 部署、和未来 Web API 扩展
- **方案**: 定义 `EngineCallbacks` 协议（on_started, on_finished, on_log, on_progress），WorkflowEngine 变为纯 Python 类；新增 `QtEngineAdapter(QObject)` 桥接 Signal/Slot
- **风险**: 大量测试使用 monkeypatch.setattr(engine, signal, ...) 需迁移
- **测试策略**: 逐步迁移，先添加 callback 并行路径，稳定后删除 Signal

### 2. God-class 拆分 (优先级: 中期)

- **动机**: main_window 86 方法 / engine 62 方法使导航和修改成本高
- **方案**: engine.py 已在进行中（engine_core/ 抽取）；main_window 可进一步将 workflow_selection、action_dispatch、state_sync 抽为独立 controller
- **风险**: 低——现有委托模式已验证可行
- **测试策略**: 每抽取一个 controller 即补充对应 unit test

### 3. 运行编排测试覆盖 (优先级: 高)

- **动机**: 1313 行核心代码零测试，重构信心为零
- **方案**: 使用 monkeypatch 替换 DB 和 executor 依赖，测试 run_workflow 的 success/failure/cancel/nested/timeout 路径
- **风险**: 延迟导入模式增加 mock 设置复杂度
- **测试策略**: 先写 integration-style 测试（真实 DB + mock executor），再补 unit 测试
