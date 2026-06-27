# Fuck My Shit Mountain Audit Report

**Project:** Workflow（工作流管理系统 4.1.0）
**Audit mode:** full（全部 19 维度）
**Date:** 2026-06-10
**Reviewer:** Claude (Fable 5) — fuck-my-shit-mountain skill

---

## 1. Executive Summary

本项目是一个 ~32k 行 Python/PySide6 桌面工作流编排工具（120 个 .py 文件），整体工程化程度高于典型个人项目：有 CI、质量门（risky-call/broad-except 审计）、schema 版本化迁移、330 项测试、发布 sha256 与打包自检。安全面（webhook 脱敏、subprocess 边界、导入校验）做得扎实。**但用户报告的两类生产 bug（钉钉通知失败、监听导致不停运行）在当前 HEAD 上依然存在明确的代码级根因**，且昨日（2026-06-09）的 deep-fix 报告宣称 PASS 的同时，仓库 HEAD 实测 `1 failed, 329 passed`——最近一次 watcher 修复提交自身没有过质量门。

核心问题集中在三条链路：(1) **监听子系统**存在 settle 窗口竞态（运行尾部的输出变更在运行结束后到期 → 立即重跑）、扫描中止时"保守触发"（没有任何变更也会启动工作流）、输出目录推断对 Excel/PBIX 原地写回完全失明、watcher 线程死亡后无法恢复且 UI 仍显示监听中；(2) **通知子系统**有 4 处静默失败点叠加（无重试、CLI 失败不打印、批量脚本退出前丢弃队列信号、脱敏导入产生 enabled=True 但 webhook_id=None 的半失效配置）；(3) **可观测性**——三个入口均未配置 logging，全仓库散布的 `logger.warning/info` 兜底在打包 exe 中全部不可见，大量"已记录日志"的降级实际等于静默。

亮点：进程边界统一（禁 shell=True）、access_token 全链路脱敏且有测试锁定、SQLite WAL+busy_timeout+版本化迁移、日志目录清理有严格正则与活跃保护。该项目不是屎山，是一座**装修过半但承重梁（watch/notify）有裂缝**的房子。

### Score Dashboard

```
Security        ████████░░  7.5  B+  脱敏/进程边界/导入校验扎实；旧行未迁移校验、明文存储可接受
Stability       ████░░░░░░  4.5  C   watch 三处竞态/降级触发、通知静默失败族、步骤默认无超时
Performance     ███████░░░  6.5  B   扫描 2s 预算对大目录树过紧；信号量占池；其余健康
Testing         █████░░░░░  5.0  C+  330 项但 settle>0 零覆盖、~28% 为元测试、HEAD 自身红灯
Maintainability ██████░░░░  5.5  C+  三个 1600-2200 行巨型文件；engine_core 拆分方向正确
Design          █████░░░░░  5.0  C+  业务规则硬编码进引擎、通知双实现、启动期静默改配置
Release         ███████░░░  6.5  B   CI/sha256/自检完备；HEAD 红灯、生产无日志、UPX 误报风险
─────────────────────────────────────
Overall         ██████░░░░  5.8  C+
```

各维度 0.0–10.0，**分数越高越好**。评分为基于证据的综合判断，非机械扣分。

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 0 | 0 | 0 |
| High | 7 | 7 | 0 |
| Medium | 12 | 9 | 3 |
| Low | 5 | 5 | 0 |
| Info | 2 | 2 | 0 |
| **Total** | **26** | **23** | **3** |

## 2. Project Map

| 层 | 组件 | 职责 |
|---|---|---|
| 入口 | `src/main.py`（GUI）、`src/cli.py`（CLI，868 行）、`_import_and_run.py`（月度批量：导入+运行+通知） | 三入口共享引擎与 DB 层；**均未配置 logging** |
| 引擎 | `src/engine.py`（1613 行，QObject）+ `src/engine_core/*`（watcher/scheduler/lifecycle/notification/cancel/force_stop/log_cleanup/selection/stages/preview/batch） | 运行生命周期、DAG 分批、并行调度、监听、通知 |
| 执行器 | `executors/`：python（subprocess 流式）、excel（win32com 原地刷新保存）、powerbi（启动进程+pywinauto F5+mtime 证明）、sub_workflow（嵌套运行） | 统一走 `runtime/process_runner.py`（禁 shell=True） |
| 持久化 | `src/database.py`（1686 行）+ models + 版本化迁移（v1-v5）+ schema 缓存；SQLite WAL | `init_db()` 启动时还会**静默修复监听配置** |
| UI | `src/ui/main_window.py`（2154 行）+ 18 个面板模块 | 手动运行在 `threading.Thread`；引擎信号跨线程 queued 投递 |
| 通知 | `notifier.py`（模板+发送）+ `engine_core/notification.py`（封装）+ `webhook_url_policy.py`（信任边界） | 引擎路径 fire-and-forget 提交线程池；CLI 另有一套同步实现 |
| 监听 | `engine_core/watcher.py`（单实例 FileWatcher）+ `watch_rules.py`（输出冲突推断） | **trigger 回调 = 在 watcher 线程内同步跑完整个工作流** |

**关键数据流（watch 触发）**：watchdog 事件/轮询 → dirty → 扫描 mtime → settle 等待 → `trigger_cb` = `engine.run_all()`（同步）→ 运行 → 触发后重扫刷新基线。
**风险集中区**：watcher 状态机（5 个状态变量手工管理）、通知的 3 个并发上下文（GUI 队列信号 / 线程池 / CLI 同步）、`init_db` 启动副作用。

## 3. Top Risks

| # | Finding | Severity | 一句话摘要 |
|---|---------|----------|-----------|
| H1 | watch settle 竞态：运行尾部变更在运行结束后到期 | High | 最后一步写完输出 ≤settle+cooldown 秒内运行结束 → watch 立即重跑，**几乎确定性复现"跑完又自动跑"** |
| H2 | 扫描中止 → "保守触发" | High | 大目录/OneDrive 慢盘扫描超 2s 即中止 → **无任何变更也启动工作流**，交替中止可反复触发 |
| H3 | watch_rules 输出推断失明 + 业务规则硬编码 | High | Excel/PBIX 原地写回不可见 → 监听含被刷新工作簿的目录 = 死循环；引擎模块硬编码"月度数据处理" |
| H4 | watcher 线程死亡不可恢复且 UI 仍显示监听中 | High | `start_watch` 幂等守卫只查 `_thread is not None` 不查 `is_alive()` |
| H5 | 通知静默失败族（4 处叠加） | High | 无重试 / CLI 失败不打印 / 批量脚本退出丢队列信号 / 关停丢弃通知 future |
| H6 | 生产环境零 logging 配置 | High | 打包 exe 中全仓库 `logger.*` 不可见，几十处"已记日志"兜底实际静默 |
| H7 | HEAD 质量门红灯 | High | `test_audit_broad_except` 失败（watcher.py 5→7 未批准）；最新修复未跑自家测试 |
| M2 | 脱敏导出→导入 → 半失效通知配置 | Medium | 新机导入后 notify.enabled=True 但 webhook_id=None，只剩一条看不到的日志 |
| M1 | 单 watcher 架构：切换工作流即停监听 | Medium | UI 选中另一工作流 → 原工作流监听静默停止 |
| M7 | `init_db` 启动期静默改写监听配置 | Medium | 自动"修复"可静默清空目录/关闭监听，仅 logger.info |

## 4. Detailed Findings

### Finding H1: watch settle 窗口竞态——运行尾部的输出变更在运行结束后到期并触发重跑

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: `engine_core/watcher.py` `_loop`
- Evidence:
  - File: `src/engine_core/watcher.py:375-401`
  - Function: `FileWatcher._loop`
  - Relevant behavior: 变更检测后进入 settle 等待（默认 15s）；到期时仅当 `self._is_running()` **当时为 True** 才吞并刷新基线（ef8f316 引入）。若变更在运行中检测到、但 settle 在运行结束后才到期，`is_running()` 已为 False → 直接 `trigger`。
  - 触发条件：工作流最后阶段向被监听目录写文件（极常见：最后一步产出结果），随后 ≤settle+cooldown（默认 23s）内运行结束。
- Problem: 吞并逻辑只覆盖"到期时刻仍在运行"的窗口，没有覆盖"pending 窗口与运行重叠但到期晚于运行结束"的窗口。
- Why it matters: 手动/CLI 运行一结束就被 watch 原因重跑一遍；与 H3 叠加（监听目录含输出）时形成持续循环。这正是用户报告的"不停的运行"。
- Realistic failure scenario: 10:00 手动运行；10:07:50 最后一步写出 Excel；10:08:00 运行结束；10:08:05（settle 到期）watcher 检查 `is_running()`=False → 以 reason=watch 重跑。
- Minimal fix: pending 期间记录 `run_active_during_pending |= is_running()`；到期时若该标志为真且当前未运行 → 按"运行期变更"吞并（刷新基线、清 pending），不触发。
- Better long-term fix: 引擎在每次运行收尾时显式通知 watcher 刷新基线（事件驱动取代轮询推断）。
- Regression test suggestion: 脚本化扫描序列——变更在 `is_running()=True` 期间出现，settle 到期时 `is_running()=False`，断言 `trigger_calls == []` 且基线已刷新。
- Estimated effort: 2-3 小时（含测试）。

### Finding H2: mtime 扫描中止时"保守触发"——无变更也启动工作流

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed（行为被测试固化：`tests/test_watch_engine.py:255-287` 断言中止后必须触发）
- Affected area: `engine_core/watcher.py`
- Evidence:
  - File: `src/engine_core/watcher.py:24-25`（`MTIME_SCAN_MAX_DIRECTORIES=20000`、`MTIME_SCAN_MAX_SECONDS=2.0`）；`:352-358`（中止→`conservative_trigger=True`）；`:322-331`（初始扫描中止→`last_mtime=-1.0`，任何后续完整扫描必 `current > -1` 触发）
  - Relevant behavior: 单轮扫描超 2 秒或超 2 万目录即中止；首次中止直接置 triggered；`degraded_triggered` 在扫描恢复完整后复位，交替"中止/完整"可重复触发。
- Problem: "不能确认无变更"被实现为"当作有变更并运行工作流"。本项目数据放在 OneDrive（云同步盘，stat 慢），2 秒预算极易击穿。
- Why it matters: 工作流可能耗时数十分钟、产生真实业务输出与钉钉通知；以"扫描太慢"为由启动它是高成本误报，且初始中止后必有一次启动即触发。
- Realistic failure scenario: 监听目录指向 OneDrive 大目录树 → 启动监听 → 初始扫描 2s 中止 → 下一轮完整扫描 max_mtime>-1 → 立即跑一遍；之后磁盘忙时再次中止 → 又跑一遍。
- Minimal fix: (1) 中止时**不触发**，记录告警并提示缩小监听范围；(2) 无有效基线时，首个完整扫描只建立基线不触发；(3) `MTIME_SCAN_MAX_SECONDS` 提高到 10s。同步修改被固化的测试断言。
- Better long-term fix: 以 watchdog 事件集（具体路径）为一级信号，mtime 全量扫描仅作兜底校验。
- Regression test suggestion: 序列 [完整, 中止, 中止, 完整(无变化)] → 断言零触发且出现"无法确认变更"告警；序列 [中止(初始), 完整] → 断言只建基线不触发。
- Estimated effort: 3-4 小时（含测试与告警文案）。

### Finding H3: watch_rules 输出目录推断失明 + 引擎层硬编码业务规则

- Severity: High
- Confidence: High
- Category: Stability / Design
- Status: Confirmed
- Affected area: `src/watch_rules.py`
- Evidence:
  - File: `src/watch_rules.py:10-11`（`MONTHLY_WORKFLOW_NAME = "月度数据处理"`、`MONTHLY_REFRESH_SCRIPT_SUFFIX` 硬编码）；`:40-67`（`collect_workflow_output_roots` 只识别 `--out` 参数与该硬编码脚本）；`src/executors/excel_executor.py:209-210`（`workbook.Save()` 原地写回）
  - Relevant behavior: Excel 步骤的 script_path 即输出文件、PBIX 同理，但冲突检测完全看不到；防自触发闭环（5f90c3a）只对一个具名工作流生效。
- Problem: `detect_watch_output_conflicts` 给出假阴性——监听"含被刷新工作簿的目录"通过校验；同时通用引擎模块内嵌具体业务名与路径深度假设（`parents[3]`）。
- Why it matters: 与 H1 叠加构成最典型死循环：watch 触发 → Excel 刷新原地保存 → mtime 变化 → 再触发。换工作流名/挪目录后"自修复"全部失效。
- Realistic failure scenario: 用户监听 `D:/报表/`，工作流内有刷新 `D:/报表/月报.xlsx` 的 Excel 步骤 → 校验通过 → 永动机。
- Minimal fix: `collect_workflow_output_roots` 把 `excel_powerquery`/`powerbi_refresh` 步骤的 `script_path` 父目录加入输出根。
- Better long-term fix: 步骤模型显式声明 `output_paths`，由 UI 录入/执行器上报，替代推断与硬编码。
- Regression test suggestion: excel 步骤 script_path 位于监听目录内 → `detect_watch_output_conflicts` 必须报冲突；python 步骤不受影响。
- Estimated effort: 1-2 小时。

### Finding H4: watcher 线程死亡后无法恢复，UI 永久显示"监听中"

- Severity: High
- Confidence: High
- Category: Stability / Frontend-State
- Status: Confirmed
- Affected area: `src/engine.py` `start_watch` 幂等守卫
- Evidence:
  - File: `src/engine.py:351-360`（守卫条件 `getattr(self._watcher, "_thread", None) is not None` 不检查 `is_alive()`）；`src/engine_core/watcher.py:438-440`（`_loop` 致命异常仅记日志，不发 `watch_stopped`、不清 `_thread`）
- Problem: 线程对象死亡后仍非 None；同参数重启请求被守卫短路返回 True，状态栏甚至提示"已开始监听"。
- Why it matters: 监听静默失效（驱动器拔出、未知异常）后，用户重新保存配置/重选工作流都无法恢复，指示灯仍为绿色——监听不可信。
- Realistic failure scenario: 网络盘抖动导致 `_loop` 抛出未捕获异常 → 线程退出 → 此后所有文件变更不再触发，UI 显示"▶ 监听中"。
- Minimal fix: 守卫加 `and thread.is_alive()`；`_loop` 致命异常路径补发 `watch_stopped` 语义（通过回调）。
- Better long-term fix: watcher 心跳 + UI 周期健康检查。
- Regression test suggestion: 人工结束 `_loop` 线程后调用 `start_watch(同参数)`，断言返回新线程且旧线程被替换。
- Estimated effort: 1 小时。

### Finding H5: 钉钉通知静默失败族（无重试 × CLI 不打印失败 × 批量脚本丢队列信号 × 关停丢 future）

- Severity: High
- Confidence: High
- Category: Stability / Fallback
- Status: Confirmed
- Affected area: `notifier.py`、`cli.py`、`_import_and_run.py`、`engine.py`
- Evidence:
  - `src/notifier.py:185-221`：单次 `requests.post`，超时/网络错误直接返回失败，无重试。
  - `src/cli.py:482-483`：`if success_send: print(...)`——**失败时无任何输出**。
  - `_import_and_run.py:130-150`：通知由引擎提交到线程池异步执行（`engine.py:579-590`），脚本在 `processEvents` 循环（引擎一停就 break）后 `sys.exit`，**通知结果的队列日志信号永远不会投递**。
  - `src/engine.py:414-425` + `src/ui/main_window.py:2131-2150`：运行 >10s 时关闭窗口 → `shutdown(wait=False, cancel_futures=True)` 丢弃待发通知。
  - `src/engine_core/notification.py:44-87`：所有异常吞并降级为 log_cb（文档自述"兼容原行为：所有异常都被吞并"）。
- Problem: 每一处单看都"有日志"，叠加后用户感知就是"通知有时没来，不知道为什么"。
- Why it matters: 通知是无人值守批量运行的唯一反馈通道；月度脚本场景下失败完全不可见。
- Realistic failure scenario: 月度 `_import_and_run.py --auto` 在网络抖动时运行 → 通知超时失败 → 脚本正常退出码 0，无任何失败痕迹。
- Minimal fix: `send_workflow_notification` 对超时/网络/5xx 重试一次；CLI 失败分支打印；批量脚本退出前 `engine.shutdown(wait=True)`+冲刷事件；配合 H6 的 logging。
- Better long-term fix: 通知结果落库（run_history 增加 notify_status），UI 历史面板可见。
- Regression test suggestion: monkeypatch send_dingtalk_message 先超时后成功 → 断言重试成功且调用 2 次；CLI 失败路径断言 stdout 含"发送失败"。
- Estimated effort: 3-4 小时。

### Finding H6: 三个入口均未配置 logging——生产环境全部 logger 输出丢失

- Severity: High
- Confidence: High
- Category: Observability / Fallback
- Status: Confirmed
- Affected area: `src/main.py`、`src/cli.py`、`_import_and_run.py`
- Evidence: 全仓库 `grep basicConfig|addHandler|FileHandler` 为空；`build_slim2.spec` `console=False`（打包 GUI 无 stderr）。
- Problem: 代码中至少 60 处 `logger.warning/info/exception` 承担"静默降级的最后可见性"职责（导入跳过脱敏 webhook、监听配置自动修复、watchdog 回退、迁移日志……），生产环境全部进入黑洞。
- Why it matters: 本审查发现的多数"有日志兜底"在用户机器上等价于无兜底；排障只能靠复现。
- Realistic failure scenario: 用户问"为什么通知没发？"——答案在一条从未写到任何地方的 `logger.info` 里。
- Minimal fix: GUI 入口配置 `RotatingFileHandler(LOG_DIR/"app.log")`；CLI/批量入口 `basicConfig(WARNING)` 到 stderr。
- Better long-term fix: 统一诊断日志 + UI"打开日志目录"入口。
- Regression test suggestion: 启动入口后断言 root logger 有 handler；写一条 warning 断言落盘。
- Estimated effort: 1-2 小时。

### Finding H7: 仓库 HEAD 质量门红灯——最新 watcher 修复未通过自家 broad-except 审计

- Severity: High
- Confidence: High
- Category: Release / Testing
- Status: Confirmed（实测 `python -m pytest -q` → `1 failed, 329 passed`）
- Evidence: `tests/test_audit_broad_except.py::test_current_repository_broad_excepts_are_approved_by_policy` 失败：`('src/engine_core/watcher.py', 385, 'broad-except count increased from 5 to 7')`；对应 ef8f316（2026-06-09 23:28）新增两个 `except Exception`。
- Problem: 提交修复时未运行测试套件；CI 若在 push 后运行也已经红。前一日审查报告"全量通过"的叙事与 HEAD 状态矛盾。
- Why it matters: 质量门红灯期间所有后续变更失去守卫基线；"316 passed"成为不可信口径。
- Minimal fix: 更新 `tools/audit_broad_except.py` allowlist（带 reason）或将新增 except 收窄为具体异常。
- Regression test suggestion: 即该守卫测试本身；流程上提交前本地跑 `pytest -q`。
- Estimated effort: 0.5 小时。

### Finding M1: 单 FileWatcher 架构——切换选中工作流即静默停止原监听

- Severity: Medium · Confidence: High · Category: Design / Frontend-State · Status: Confirmed
- Evidence: `src/engine.py:178-182`（引擎仅一个 `FileWatcher`）；`src/engine.py:363`（`start_watch` 先 `stop_watch()`）；`src/ui/main_window.py:851,1702`（选中/保存即 `_sync_engine_watch`）。
- Problem: watch_enabled 是按工作流持久化的配置，但运行时全局只有一个监听槽位，跟随 UI 选中走。用户在工作流 A 配好监听后点开 B 查看 → A 的监听停止（仅指示灯变灰）。
- Realistic failure scenario: 用户晚上把窗口停在工作流 B，A 的源文件更新无任何触发。
- Minimal fix: 切走时状态栏明确提示"已停止对「A」的监听"；README 说明"仅监听当前选中工作流"。
- Better long-term fix: `dict[workflow_id, FileWatcher]` 多实例 + 应用启动时恢复所有 watch_enabled 工作流。
- Regression test: 选中 B 后断言 A 的 watcher 已停且有可见提示。 · Effort: 提示 1h / 多实例 1-2 天。

### Finding M2: 脱敏导出 → 导入产生"启用了通知但没有机器人"的半失效配置

- Severity: Medium · Confidence: High(机制)/Medium(命中) · Category: Stability / Backend-Data · Status: Confirmed
- Evidence: `src/database_import_export.py:463-469`（脱敏且本机无同名 → 跳过创建，仅 logger.info）；`:587-602`（绑定失败 → `webhook_id=None` 但 `enabled` 保留）；运行时 `engine_core/notification.py:49-52` 仅 log_cb"通知未配置机器人"。
- Problem: 导出默认脱敏（README 如此引导），换机/重置 DB 后按月度流程导入，通知静默消失；结合 H5/H6，提示链路全黑。
- Minimal fix: 绑定失败且 enabled=True 时 `logger.warning` 升级 + 导入完成后向调用方返回告警摘要（CLI 打印）。
- Regression test: 导入含脱敏 webhook 的 JSON 到空库 → 断言告警输出包含工作流名。 · Effort: 2h。

### Finding M3: 4.1.0 新增发送前 URL 严校验可能拒绝历史合法配置

- Severity: Medium · Confidence: Medium · Category: Stability · Status: Suspected
- Evidence: `src/webhook_url_policy.py:38`（`netloc.lower() != "oapi.dingtalk.com"`——显式端口 `:443`、专属/政务域名变体、代理网关全部拒绝）；`notifier.py:162-164` 发送前校验；DB 旧行无迁移期校验或 UI 巡检。
- Problem: 4.1.0 之前能发的 URL 升级后可能在发送时刻才被拒，错误只出现在运行日志面板。
- Minimal fix: Webhook 管理界面打开时对存量行跑校验并标红；拒绝消息附"如确为钉钉地址请检查端口/域名写法"。
- Regression test: 端口显式 URL 校验结果断言 + 管理界面标红逻辑单测。 · Effort: 2h。

### Finding M4: Excel 刷新等待的状态探针双重吞异常——可能把"未完成"当"完成"保存

- Severity: Medium · Confidence: Medium · Category: Fallback / 数据正确性 · Status: Confirmed(代码路径)/Suspected(频率)
- Evidence: `src/executors/excel_executor.py:76-91`（`CalculationState`、`workbook.Refreshing` 两个探针均 `except Exception: pass`，双失败即 `return` 视为完成）；`:194-198`（仅 OLEDB 连接关后台刷新，ODBC/模型连接仍异步）。
- Problem: COM 失效/忙碌时探针恒抛 → 提前判定完成 → `Save()` 可能保存未刷新完的数据为"成功"。注意 RPC_E_CALL_REJECTED 在刷新中正当出现，不能简单 fail-fast。
- Minimal fix: 连续双失败计数 ≥N 时写入告警日志（可见性），保持控制流；由后续 Save 暴露真实 COM 错误。
- Better long-term fix: 用 `RefreshAll` 前逐连接同步化 + 完成事件检测替代轮询。
- Regression test: 模拟探针恒抛 → 断言日志含"无法读取 Excel 刷新状态"。 · Effort: 1-2h。

### Finding M5: Power BI "自动刷新"实为交互式流程，无人值守必然超时失败

- Severity: Medium · Confidence: High · Category: Design / Docs · Status: Confirmed
- Evidence: `src/executors/powerbi_executor.py:528-552`（pywinauto `set_focus`+`type_keys("{F5}")`）；`:359-384`（auto_close=True 实际是"等用户手动关闭 PBI 进程，否则超时 taskkill"）；README 宣称"Power BI 数据集刷新"为核心功能。
- Problem: 没有任何代码触发保存/关闭；mtime 证明依赖人工保存。无人值守场景下该步骤 ≈ 必败（600s 超时），还会抢键盘焦点。
- Minimal fix: README/步骤编辑器明示"需要人工保存并关闭"；超时错误消息指向该事实。
- Better long-term fix: 改用 Power BI REST API（Service 端刷新）或 pbixray/外部刷新工具。 · Effort: 文档 1h / 替代方案数天。

### Finding M6: 并行调度信号量占满线程池槽位 + 嵌套子工作流共享池——饥饿/死锁风险

- Severity: Medium · Confidence: Medium · Category: Stability / Performance · Status: Suspected
- Evidence: `src/engine_core/scheduler.py:43-50`（一次性 submit 全部步骤，未拿到信号量的任务**占着池线程等待**）；`src/engine.py:175-176`（池 = cpu+4）；子工作流的步骤再次提交到同一池，父步骤线程阻塞等待子完成。
- Realistic failure scenario: 大批并行步骤 + 多级子工作流时池被"等待者"占满，运行永久卡住。
- Minimal fix: scheduler 改为按信号量许可逐个 submit（生产者侧限流）。
- Regression test: max_workers=1、池上限 2、批 5 步 + 嵌套子工作流，断言可完成。 · Effort: 2-3h。

### Finding M7: `init_db()` 启动期静默改写用户监听配置

- Severity: Medium · Confidence: High · Category: Configuration / Fallback · Status: Confirmed
- Evidence: `src/database.py:251-276`（`_repair_legacy_watch_configurations`：冲突即替换目录或直接 watch_enabled=False，仅 logger.info）；`src/watch_rules.py:106-124`。
- Problem: 数据层启动副作用悄改用户意图；与 H6 叠加后用户完全无感知，只觉得"监听自己关了"。
- Minimal fix: 修复动作升级为 `logger.warning` 并在 UI 启动后通过状态栏/对话框提示一次。 · Effort: 1-2h。

### Finding M8: Webhook 测试发送阻塞 GUI 线程最长 10 秒

- Severity: Medium · Confidence: High · Category: Frontend-State · Status: Confirmed
- Evidence: `src/ui/webhook_manager.py:492-496`（`_on_test` 在主线程同步 `requests.post`，timeout=10）。
- Minimal fix: 测试发送放入 `QThreadPool`/线程，期间禁用按钮。 · Effort: 1-2h。

### Finding M9: 步骤默认无超时——挂死脚本导致运行永不结束

- Severity: Medium · Confidence: High · Category: Stability · Status: Confirmed
- Evidence: `src/executors/python_executor.py:323-348`（timeout=None → `wait_with_cancel(proc, 0)` 永等）；excel/powerbi/sub_workflow 有常量默认，python 步骤没有。
- Realistic failure scenario: 用户脚本死循环/等输入 → 运行卡住，需手动取消；watch 模式下监听线程同时被占死（同步触发）。
- Minimal fix: python 步骤引入默认超时常量（如 3600s），UI 显示默认值。 · Effort: 1-2h。

### Finding M10: `config.json` 非原子写入 + 损坏后静默回退默认

- Severity: Medium · Confidence: High · Category: Configuration · Status: Confirmed
- Evidence: `src/config.py:93-96`（直接 open(w) 写）；`:82-90`（损坏时 logger.warning 后回退 `{}`）。
- Minimal fix: temp+`os.replace` 原子写。 · Effort: 0.5h。

### Finding M11: 冻结环境 Python 解释器"盲猜 PATH"

- Severity: Medium · Confidence: High · Category: Configuration / Stability · Status: Confirmed
- Evidence: `src/executors/python_executor.py:17-44`（打包后依次 which python/python3/py → 硬编码路径 → **裸返回 'python'**；不记录选中了哪个解释器）。
- Problem: 步骤在开发机与打包机行为不同（依赖包缺失、版本不符）；彻底找不到时报"系统找不到指定的文件"无指向。
- Minimal fix: 找不到返回 None → 明确错误"未找到系统 Python 解释器"；把选中的解释器写入步骤 stdout 日志首行。 · Effort: 1h。

### Finding M12: Webhook 对话框「关闭」按钮绕过未保存确认

- Severity: Medium · Confidence: High · Category: Frontend-State · Status: Confirmed
- Evidence: `src/ui/webhook_manager.py:177`（`btn_close.clicked.connect(self.accept)`——`accept()` 不经 `closeEvent`，而未保存确认在 `closeEvent:518-525`）；窗口 X 按钮有确认、关闭按钮没有。
- Minimal fix: 改 connect `self.close`。 · Effort: 10 分钟。

### Finding L1: 巨型文件（main_window 2154 / database 1686 / engine 1613 行）

- Severity: Low · Confidence: High · Category: Maintainability · Status: Confirmed · Principle: File Size Limit (1.2)
- 说明: 超 1000 行阈值；但 engine_core/step_table 等拆分已在正确方向上。继续按既有模式拆（main_window 的 watch/run/close 区块）。 · Effort: 持续性。

### Finding L2: 通知双实现（引擎路径 vs CLI 路径）

- Severity: Low · Confidence: High · Category: Maintainability · Status: Confirmed · Principle: DRY (4.1)
- Evidence: `engine_core/notification.py` 与 `cli.py:415-483` 两套组装逻辑，字段语义已现漂移（reason、failure_summary 截断规则）。 · Effort: 2-3h 合并。

### Finding L3: cooldown/settle 默认值三处重复定义

- Severity: Low · Confidence: High · Category: Maintainability · Status: Confirmed
- Evidence: `constants.py:6-7`、`config.py:65-66`、`engine.py:348-349` 各自硬编码 8/15。 · Effort: 0.5h 收敛到 constants。

### Finding L4: 仓库内残留历史交接/审查文档与大体积图片

- Severity: Low · Confidence: High · Category: Release / Docs · Status: Confirmed
- Evidence: 跟踪文件含 `HANDOVER_AI_SWITCH_2026-02-13.md`、`V7_iOS_Minimal_Handover.md`、`05_整体Review与改进建议.md`、`audit-report-*.md`、2.5MB `图标.png`。 · Effort: 0.5h 归档清理。

### Finding L5: Excel 异步等待线程跨 COM 套间调用

- Severity: Low · Confidence: Medium · Category: Stability · Status: Confirmed(结构)/Suspected(影响)
- Evidence: `excel_executor.py:16-66`：`CalculateUntilAsyncQueriesDone` 在新线程调用主线程创建的 COM 对象（未 marshal），实际多半抛错走轮询回退——等待线程形同虚设但有误导日志。 · Effort: 文档化或删除该分支 1h。

### Finding I1: 测试构成与覆盖空洞（信息）

- ~28%（约 90/330）为元/守卫测试（repo hygiene、CI 文本、docs 关键词、审计工具、依赖清单）；watcher 全部循环测试 settle=0，**settle>0 的时序行为零覆盖**；observer(watchdog) 模式零覆盖；通知重试/限流场景零覆盖。"330 tests passed"对产品行为的保证显著低于字面。

### Finding I2: UPX 压缩的杀软误报风险（信息）

- `build_slim2.spec:upx=True`；国内桌面环境（360/火绒）对 UPX 壳 PyInstaller exe 误报率较高，可评估关闭换取分发顺畅。

## 5. Security Concerns

| 项 | 状态 |
|---|---|
| Webhook access_token 脱敏 | ✅ 发送错误/响应摘要/日志/导出多路径统一 redact，且有 6 项测试锁定（test_notifier.py） |
| URL 信任边界 | ✅ 仅 https://oapi.dingtalk.com/robot/send 放行（SSRF 面收窄）；⚠ 代价是 M3 的误拒风险 |
| 命令注入 | ✅ `runtime/process_runner.py` 强制 argv 列表、禁 shell=True，且有失败型审计门 |
| 导入边界 | ✅ JSON schema 字段级校验 + 风险路径标注（advisory）；uid 冲突跳过 |
| 明文存储 | ⚠ webhook URL 明文存 SQLite（本地单用户桌面可接受，报告备案） |
| 旧数据迁移校验 | ❌ M3——存量行无巡检 |

## 6. Stability Concerns

核心见 H1/H2/H4/H5/M4/M6/M9。补充：

- `engine.py:666-705` 原子启动 + 嵌套运行栈（`_active_run_ids`）设计良好；force_stop 孤儿记录清理（force_stop.py）覆盖了"DB 卡 running"场景。
- 取消链路（cancel watcher 0.2s 轮询 → cancel_event → taskkill /T 进程树）完整且各执行器一致。
- `_finalize_run_history` 落库失败会显式告警 UI（engine.py:540），不静默。

## 7. Performance Concerns

- H2 的 2s 扫描预算是当前最大性能相关风险（误触发整条工作流）。
- `scheduler.py` 信号量模式浪费池线程（M6）。
- DB 侧：`prev_step_status_map` 预取消 N+1（lifecycle.py P-3）、WAL checkpoint 策略（终态集中 checkpoint）均健康。
- 日志面板 deque(maxlen=2000) + 批量 flush，无无界增长。

## 8. Testing Gaps

见 I1 与 §Testing Authenticity。最高优先缺口（按用户已踩的坑排序）：

1. settle>0 的运行尾部竞态（H1 场景）——无任何测试。
2. 扫描中止/恢复交替序列——现有测试反而把误触发固化为预期。
3. watchdog observer 模式 happy path——零覆盖（CI offscreen 可跑）。
4. 通知失败→重试→成功路径；CLI 失败输出契约。
5. 打包后冒烟（--self-check 已有，但不覆盖通知/监听子系统初始化）。

## 9. Maintainability Concerns

- L1 巨型文件、L2 双实现、L3 常量重复。
- 修复标签注释体系（`R5-#2`、`H9 修复`、`MA1`…）密度极高：对回溯有价值，但无索引文档，新维护者无法解码；建议在 docs/ 建立标签索引或逐步清理。
- `engine_core/` 拆分质量好：回调注入、无 QObject 依赖、可单测。

## 10. Type Safety Analysis

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 0 | 0 | 0 | 0 | 0 |
| InputBoundary | 2 | 0 | 0 | 2 | 0 |
| OutputLeak | 0 | 0 | 0 | 0 | 0 |
| BooleanTrap | 2 | 0 | 0 | 0 | 2 |
| StringlyTyped | 3 | 0 | 0 | 1 | 2 |
| ErrorType | 1 | 0 | 0 | 0 | 1 |

- InputBoundary: `start_watch` 对 DB 脏数据已 `_safe_int` 兜底（好）；`notify_config` JSON 解析失败回 `{}`（enabled 静默丢失，M2 相关）；`step.timeout_seconds=None` 语义为"无限"未在类型层表达（M9）。
- BooleanTrap: `powerbi_executor.execute(auto_close=True, auto_refresh=True)` 布尔参数 + 字符串 args 双通道控制同一行为。
- StringlyTyped: 状态机字符串（"success"/"failure"/...）跨 engine/DB/UI 传递，已有 `RunStatus` 枚举但边界处仍裸字符串比较；watch_mode 裸字符串（已有 `_WATCH_MODES` 集合校验，可）。

## 11. Frontend State Analysis

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ComponentSize | 1 | main_window.py (2154 行, ~10 类职责) |
| StateDuplication | 2 | engine._running vs _running_workflow_id vs 指示灯（H4 死亡态不同步）；编辑模式分散 |
| PropDrilling | 0 | — |
| EffectChain | 1 | `_on_run_requested` 停止-重试回调链（手工 connect/disconnect，R8 系列已修两轮） |
| UIBusinessCoupling | 1 | webhook 测试发送在 GUI 线程做网络 IO（M8） |
| DOMasState | 0 | — |
| RequestState | 1 | 通知结果无 UI 呈现位（仅日志流）（H5） |
| RenderPerf | 0 | 日志面板批量 flush + deque 上限，健康 |

## 12. Backend Data-Access Analysis（无网络 API，按本地数据边界评估）

| Subtype | Count | 说明 |
|---------|-------|------|
| ApiConsistency | 1 | 引擎 `run()` 公开入口 vs CLI 自组装通知——同一动作两套语义（L2） |
| Validation | 1 | 导入步骤 `script_path` 允许空串落库，运行期才失败 |
| Auth | 0 | 本地单用户 |
| NplusOne | 0 | 已预取（lifecycle P-3） |
| Caching | 1 | schema 缓存 + 跨工作流环检测缓存均有失效路径，健康 |
| ErrorResponse | 1 | `import_from_json` 仅返回 count，告警全靠 logger（M2） |
| BusinessLogic | 1 | watch_rules 业务硬编码（H3） |
| DataFlow | 0 | WAL/终态 checkpoint 设计合理 |

## 13. Dependency Weight Analysis

| Dependency | Status | Weight | Used For | Recommended Action |
|------------|--------|--------|----------|-------------------|
| PySide6 6.10.1 | Healthy | ~500MB 装机/exe 内裁剪 | UI | Keep（spec 已 exclude Qml/Quick/Svg/Pdf） |
| SQLAlchemy 2.0.46 | Healthy | 中 | ORM | Keep |
| pywin32 311 | Healthy | 中 | Excel COM | Keep |
| pywinauto 0.6.9 | Overweight-ish | 拉 comtypes | 仅 PBI F5 一处 | M5 解决后可降级为可选依赖 |
| watchdog 6.0.0 | Healthy | 小 | 事件监听 | Keep（spec 已含 hiddenimports） |
| psutil 7.2.2 | Healthy | 小 | PBI 进程树兜底 | Keep |
| requests 2.32.5 + certifi | Healthy | 小 | 钉钉 | Keep（spec 已 collect_data_files("certifi")，且有 CA 缺失错误测试） |
| pyinstaller 6.11.1 | Healthy | 构建期 | 打包 | Keep；评估 upx=False（I2） |

三份 requirements 钉版本一致（dev 浮动 `>=` 仅开发面，存在轻微漂移可能）。无未用依赖。

## 14. Principles Compliance

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Fail-Fast (4.4) | 4 | High | H2 保守触发反模式、M2 半失效配置、M4 探针吞噬、config 损坏回退 |
| Don't Swallow Errors (6.1) | 3 | High→Medium | notification.py 全吞、excel 探针、watcher 静默回退轮询 |
| No Hidden Side Effects (5.3) | 2 | Medium | `init_db()` 改写监听配置（M7）、`start_watch` 内部 stop 全局监听（M1） |
| Configuration Over Hardcoding (9.1) | 2 | Medium | watch_rules 业务名/路径深度（H3）、python 解释器候选路径（M11） |
| File Size Limit (1.2) | 3 | Low | main_window/database/engine（L1） |
| DRY (4.1) | 2 | Low | 通知双实现（L2）、默认值三处定义（L3） |
| Principle of Least Surprise (3.1) | 2 | Medium | "auto_close"实为"超时强杀"（M5）、「关闭」按钮不确认（M12） |
| Timeout Every External Call (10.4) | 1 | Medium | python 步骤默认无超时（M9） |

### Principles Respected

- **进程边界单点化**（process_runner + 失败型审计门）——Explicit Dependencies、最小权限的好范例。
- **CQS / 回调注入**：engine_core 模块普遍纯函数 + 回调，易测试。
- **结构化错误**：自定义异常层次（exceptions.py）+ ErrorDiagnostician 建议修复。
- **迁移纪律**：SCHEMA_MIGRATIONS 版本化 + 失败即停启动（database.py:248 fail-fast 正确）。
- **资源清理**：执行器 taskkill /T + COM 释放 + 线程 join 全链路成体系。

## 15. Fallback / Defensive Code Analysis

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 5 | 3 | 2 | 0 |
| EmptyCatch | 4 | 2 | 0 | 2 |
| CompatibilityBranch | 2 | 2 | 0 | 0 |
| SilentCorrection | 3 | 2 | 1 | 0 |
| DefensiveGuess | 3 | 1 | 2 | 0 |

代表项（处置建议）：

- watcher watchdog 失败→轮询回退（`watcher.py:279-309`）：**KeepWithAlert**（已有日志，配合 H6 后真正可见）。
- 扫描中止→保守触发（H2）：**FailFast 改造**（不确认就不要替用户花成本）。
- excel 探针双吞（M4）：**KeepWithAlert**（计数告警）。
- `_get_python_executable` 裸回 'python'（M11）：**FailFast**。
- notification.py 全异常吞并：**KeepWithAlert**（通知失败不应中断运行，但要重试+可见）。
- UI 大量 `except Exception: pass` 包指示灯/信号 emit（main_window 多处）：低风险防御，**保留**，2 处空 catch（watch indicator）建议补 debug 日志。

## 16. Testing Authenticity Analysis

### Confidence Assessment

| Test Area | Real Confidence | What bugs would escape | Action |
|-----------|---------------|------|--------|
| test_watch_engine.py (16) | **Low-Medium** | settle>0 全部时序 bug（H1）、observer 模式、真实目录行为 | Rewrite 补时序用例 |
| test_notifier.py (7) | Medium-High | 重试/限流/keyword 拒绝；合法变体 URL 误拒（M3） | Keep + 补 |
| test_watch_rules.py (7) | Medium | Excel/PBIX 原地输出盲区（H3）——按旧规则全绿 | 补反例 |
| test_engine_scheduling.py (12) | Medium | 池饥饿/嵌套死锁（M6） | 补压力用例 |
| test_ui_main_window_actions.py (33) | Medium | 跨线程信号投递时序 | Keep |
| test_schema_guards.py (38) | 结构性 | 行为不在范围 | Keep（定位明确） |
| 守卫/元测试 ~90 项 | N/A | 产品行为完全不在范围 | Keep，但口径上与行为测试分开统计 |
| executors 系列 (45) | Medium-High | 真实 COM/进程行为（mock 边界） | Keep |

### Valuable Tests

- `test_notifier.py` 的 token 脱敏矩阵（真实回归价值）；`test_process_runner.py` shell=True 禁令；`test_engine_core_force_stop.py` 孤儿记录清理；`test_audit_*` 失败型门（刚刚抓住了 ef8f316——证明有效）。

### Suspicious Tests

- `test_watch_loop_conservatively_triggers_when_scan_aborts`：把误触发断言为正确行为（H2 固化）。
- 全部 watcher 循环测试 settle=0 + 全 mock 扫描：测的是状态机骨架，不是时序行为。
- `test_watch_loop_swallows_change_while_current_run_is_active`：is_running 序列被脚本化到恰好命中吞并分支，绕开了竞态本身。

### Missing Tests

1. H1 竞态序列（最高优先）。2. 中止→恢复交替不触发。3. observer 模式 + 真实 tmp 目录端到端。4. 通知重试/CLI 失败输出。5. 导入脱敏 webhook 后的运行期行为断言。

## 17. Recommended Fix Order

### Fix Immediately（本轮已列入修复）

| 项 | 内容 |
|---|---|
| H7 | broad-except allowlist 修正，恢复质量门绿灯 |
| H1+H2 | watcher 竞态吞并 + 取消保守触发 + 无基线不触发 + 扫描预算 10s（含测试改造） |
| H3 | watch_rules 纳入 Excel/PBIX 原地输出 |
| H4 | start_watch 守卫 `is_alive()` |
| H5 | 通知重试一次 + CLI 失败打印 + 批量脚本冲刷退出 |
| H6 | 三入口 logging 配置 |
| M10/M11/M12 | 原子写 config / 解释器 fail-fast / 关闭按钮确认 |
| M4 | Excel 探针连续失败告警 |

### Fix Before Stable Release

- M2（导入告警上浮）、M3（存量 webhook 巡检标红）、M7（启动修复可见化）、M9（python 步骤默认超时）、M8（测试发送移出 GUI 线程）、M6（scheduler 限流提交）。

### Schedule Later

- M1 多 watcher 架构、M5 Power BI 路线（REST API）、L1 巨型文件继续拆分、L2 通知实现合并、L3 常量收敛。

### Ignore for Now

- L4（仓库文档清理，建议但不阻塞）、L5（等待线程文档化）、I2（UPX 评估）。

## 18. Quick Wins

1. `btn_close.clicked.connect(self.close)`（10 分钟，M12）。
2. CLI 通知失败打印一行（10 分钟，H5 子项）。
3. allowlist 补 2 条带 reason 记录（30 分钟，H7）。
4. `save_user_config` 原子写（30 分钟，M10）。
5. `MTIME_SCAN_MAX_SECONDS` 2→10（5 分钟，H2 缓解项）。
6. 入口 logging 三行配置（1 小时，H6——一次性点亮全部既有兜底日志）。

## 19. Long-term Refactor Plan

1. **监听子系统 v2**（动机：H1-H4、M1 同根——状态机过于隐式）：每工作流独立 watcher 实例；引擎运行结束事件显式驱动基线刷新；watchdog 事件路径集为一级信号、全量扫描降级为校验；心跳+健康检查上报 UI。风险：行为变化需灰度；测试策略：以本轮新增的时序测试为基线扩展。
2. **通知管道**（动机：H5、L2、M2）：单一 `NotificationService`（模板渲染→策略→发送→重试→结果落库 run_history.notify_status），引擎/CLI/批量共用；UI 历史面板展示通知状态。
3. **步骤输出声明模型**（动机：H3 根治）：Step 增加 outputs 字段，执行器上报实际写入路径，watch 冲突检测与"运行期变更吞并"都改为基于声明/上报路径的精确判断。
4. **main_window 减肥**（动机：L1）：按 watch 区/run 区/close 区抽 controller，延续 step_table 的拆分套路。

---

*报告由 fuck-my-shit-mountain skill 按 full 模式生成；所有 Confirmed 结论均经代码逐行核验或本机实测（`pytest`、`git`）。Suspected 项已标注依据与限制。*
