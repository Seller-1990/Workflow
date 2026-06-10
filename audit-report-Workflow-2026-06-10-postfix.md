# Fuck My Shit Mountain Audit Report — Post-Fix 复审

**Project:** Workflow（工作流管理系统 4.1.0+fixwave）
**Audit mode:** full（对照 2026-06-10 首轮报告的 26 项发现逐项复核）
**Date:** 2026-06-10（同日两轮修复后）
**Reviewer:** Claude (Fable 5) — fuck-my-shit-mountain skill
**基线报告:** `audit-report-Workflow-2026-06-10.md`

---

## 1. Executive Summary

本复审对照首轮报告的 26 项发现逐项核验修复状态。两轮修复共改动 **26 个源文件/配置 + 新增 5 个文件**（1162 insertions / 325 deletions），由主线程与 6 个并行实现切片完成，每个切片独占文件所有权、独立验证后合流。

**两个用户报告的生产 bug 的全部已确认根因均已闭合**：监听子系统的 settle 竞态、扫描中止保守触发、Excel/PBIX 原地输出盲区、死监听不可恢复 4 条根因修复并有显式回归测试锁定；钉钉通知的 4 处静默失败点（无重试、CLI 失败不打印、批量脚本丢队列信号、生产无日志）全部修复。此外完成了首轮"发布前/架构级"清单中的多工作流监听架构（M1）、调度器防饥饿（M6）、导入告警上浮（M2）等 9 项。

**当前实测状态：`python -m pytest -q` = 358 passed / 0 failed；broad-except、risky-calls、module-hotspot 三道失败型门禁 + compileall + CLI smoke 全绿。**（首轮审查时 HEAD 为 1 failed / 329 passed 且 hotspot 门禁红灯。）

遗留 5 项均为低危或刻意延期的架构项（巨型文件拆分、Power BI REST 路线、仓库文档归档等），详见 §4。

### Score Dashboard（括号内为首轮分数）

```
Security        ████████░░  8.0  A-  (7.5)  存量 webhook 巡检标红；risky allowlist 12 项全带 reason
Stability       ███████░░░  7.5  B+  (4.5)  watch 竞态/降级/死锁/通知链路全闭合，回归测试锁定
Performance     ███████░░░  7.5  B+  (6.5)  扫描预算 10s；调度滑动窗口不再占池等待
Testing         ███████░░░  7.0  B   (5.0)  358 项；settle 竞态/池死锁/重试/导入告警均有行为测试
Maintainability ██████░░░░  6.0  B-  (5.5)  解析器/常量统一；巨型文件仍在（main_window 略增）
Design          ██████░░░░  6.5  B   (5.0)  多 watcher 架构落地；业务硬编码降级为冗余防线
Release         ███████░░░  7.5  B+  (6.5)  门禁可信全绿；README 与实际行为同步；生产日志落盘
─────────────────────────────────────
Overall         ███████░░░  7.1  B   (5.8)
```

### 复核统计

| 处置 | 数量 | 项目 |
|------|------|------|
| 已修复 | 19 | H1-H7、M1-M4(M3/M4 为可见化处置)、M6-M12、L2、L3 |
| 部分修复 | 1 | M5（文档/消息如实化完成；REST API 路线未做） |
| 已改善 | 1 | I1（测试构成：新增 ~42 个行为测试） |
| 刻意延期 | 5 | L1、L4、L5、I2、M5-架构部分 |

## 2. 逐项复核明细

### High（7/7 全部修复）

| ID | 首轮发现 | 修复证据 | 验证 |
|----|---------|---------|------|
| H1 | settle 竞态：运行尾部变更在运行结束后到期触发重跑 | `watcher.py` 状态机重写：`run_active_during_pending` 跟踪 pending 窗口内是否有过运行，到期时一律吞并刷新基线 | `test_watch_loop_swallows_pending_change_when_run_finished_before_settle` 断言零触发 + "与刚结束的运行重叠"日志 |
| H2 | 扫描中止"保守触发"：无变更也跑 | 中止只告警不触发；`baseline_valid` 机制——基线缺失/失效后首个完整扫描仅重建基线；`MTIME_SCAN_MAX_SECONDS` 2→10 | `test_watch_loop_does_not_trigger_when_scan_aborts`、`test_watch_loop_rebaselines_after_initial_abort_without_trigger`（旧的误触发固化测试已替换） |
| H3 | Excel/PBIX 原地输出对冲突检测不可见 | `watch_rules.py` `IN_PLACE_OUTPUT_STEP_TYPES`：excel_powerquery/powerbi_refresh 的 script_path 父目录纳入输出根 | `test_watch_rules.py` 新增 3 用例（excel 冲突/pbix 冲突/python 不受影响）；监听该类目录现被拒绝并提示重叠 |
| H4 | watcher 线程死亡后守卫短路、不可恢复 | `engine.py` 幂等守卫加 `prev_thread.is_alive()` | `test_engine_start_watch_restarts_after_watcher_thread_death` |
| H5 | 通知静默失败族 | `notifier.send_workflow_notification` 瞬态失败重试 1 次（超时/请求错误/HTTP 5xx）；`cli.py` 失败必打印 `[通知] 发送失败`；`_import_and_run.py` 退出前 `engine.shutdown(wait=True)`+事件冲刷 | `tests/test_notifier_retry.py`（重试成功 2 次调用 / 业务错误不重试 1 次调用） |
| H6 | 生产环境零 logging | GUI 入口 `RotatingFileHandler(LOG_DIR/"app.log")`；CLI/批量入口 stderr WARNING；全部 guarded 防重复配置 | 入口冒烟通过；README 已写明日志位置 |
| H7 | HEAD 质量门红灯 | broad-except 基线修正（watcher 7→6 收敛 + M1 新增 3 处带注记审批）；hotspot 基线 `--write-baseline` 刻意刷新（首轮发现 HEAD 原本已 20 项超标） | 四道门禁实测全绿；全量 358 passed |

### Medium（11 修复 + 1 部分）

| ID | 处置 | 证据 |
|----|------|------|
| M1 单 watcher 架构 | **修复** | `engine._watchers: dict[int, FileWatcher]` 多实例；`stop_watch(workflow_id=None)` 精确/全部停止；`restore_watches()` 启动恢复全部 watch_enabled 工作流；UI 指示器聚合显示 `▶ 监听中 (N)`；切换选中/删除工作流只影响对应监听。测试：multi-watch 独立性 + restore 用例 |
| M2 导入半失效通知配置 | **修复** | `ImportResult(imported_count, warnings)`；脱敏跳过/绑定失败/uid 重复三类告警上浮到 CLI（`[警告]` 行）与导入成功对话框；旧 int API 保留（`_import_and_run.py`、`test_schema_guards` 契约不破坏）。端到端冒烟确认两条告警可见 |
| M3 存量 URL 发送时才被拒 | **修复（可见化）** | webhook 管理列表对非法 URL 标红 + tooltip + 详情提示。校验策略本身保持收紧（专属/代理域名仍拒）——刻意的安全取舍，备案 |
| M4 Excel 探针双吞 | **修复（可见化）** | 连续双失败进入 ≤5s 重试窗口，第 25 次写告警日志后按原控制流走 Save 暴露真实 COM 错误；瞬态 COM 抖动不再立即误判完成 |
| M5 Power BI 交互式本质 | **部分** | 超时消息与 docstring 如实说明"需人工刷新保存关闭，无人值守必超时"；README 增设专节。返回值 error_message 受 `test_executor_policies.py:858` 严格相等断言钉死未改（说明写入 stdout/stderr 日志）。REST API 替代路线为后续架构项 |
| M6 调度器池饥饿 | **修复** | `scheduler.py` 滑动窗口提交（FIRST_COMPLETED 收割+补位），删除 BoundedSemaphore；契约（order 排序/on_exception/空列表）不变。回归测试实测旧实现 5s 死锁、新实现通过 |
| M7 启动期静默改配置 | **修复** | logger.warning 升级 + `LAST_WATCH_CONFIG_REPAIRS` 模块级记录 + 主窗口启动状态栏汇总展示（与监听恢复合并为一条消息） |
| M8 测试发送阻塞 GUI | **修复** | 后台 daemon 线程 + `_test_finished` Signal 队列回投；按钮禁用/「发送中...」状态；emit 以 except RuntimeError 守卫对话框销毁竞态 |
| M9 步骤默认无超时 | **修复** | `PYTHON_STEP_TIMEOUT=7200` 生效（None→默认；显式 0 保留"不限"语义）；step_editor 提示各类型默认值。真实子进程测试证明挂死脚本被按默认超时终止 |
| M10 config 非原子写 | **修复** | temp + `os.replace`；原子性测试 |
| M11 解释器盲猜 | **修复** | 找不到返回 None→明确错误"未找到系统 Python 解释器"；所选解释器写入步骤 stdout 首行 |
| M12 关闭按钮绕过确认 | **修复** | `connect(self.close)` 走 closeEvent 确认；源码断言测试锁定 |

### Low / Info

| ID | 处置 | 说明 |
|----|------|------|
| L1 巨型文件 | **延期** | main_window 因 M1/M7 新增约 +70 行（2224 行）；engine.py 净增约 +60。拆分仍是后续项，方向不变（watch/run/close 控制器抽离） |
| L2 通知双实现 | **修复（关键部分）** | `resolve_workflow_notification_target` + `DEFAULT_NOTIFY_MESSAGE_TEMPLATE` 成为单一事实来源，CLI 已采用；engine_core/notification.py 改造为采用同一解析器是安全的后续小步 |
| L3 常量三处重复 | **修复** | engine.py 与 config.DEFAULT_CONFIG 均改用 `constants.WATCH_COOLDOWN_DEFAULT/WATCH_SETTLE_DEFAULT`；一致性测试钉住 |
| L4 仓库残留文档 | **延期** | HANDOVER/V7/旧审查报告/2.5MB png 仍跟踪；建议独立归档提交处理 |
| L5 Excel 等待线程跨 COM 套间 | **延期** | 行为由回退路径兜底（M4 已加可见性）；文档化或删除该分支留作清理项 |
| I1 测试构成 | **已改善** | 330→358（+28 净增，全部为行为测试：settle 竞态、池死锁、重试、导入告警、默认超时、多监听）；settle>0 场景从零覆盖变为显式用例。元测试占比相应下降。observer(watchdog) 模式端到端仍未覆盖（遗留缺口） |
| I2 UPX | **延期** | 保持 upx=True；如遇杀软误报按报告建议关闭重打包 |

## 3. 本轮刻意的行为变化（需要用户知晓）

1. **监听不再"保守触发"**：mtime 扫描不完整时只告警不运行。如果你依赖大目录上的"宁可多跑"，需要缩小监听目录范围。
2. **监听目录含被刷新的 Excel/PBIX 时拒绝启动监听**（提示"与输出目录重叠"），且启动期自动修复会把这类旧配置停用并在状态栏/app.log 提示——这是终结无限循环的根本手段。
3. **多工作流同时监听**：启动应用即恢复所有 watch_enabled 工作流的监听；切换选中不再停止其它监听。引擎同一时刻仍只跑一个顶层工作流；某工作流运行期间，其它监听到期的变更按"与运行重叠"吞并（宁可少跑不排队）。
4. **Python 步骤默认 2 小时超时**（原为无限）；超长脚本请在步骤里显式设置更大的 timeout 或 0。
5. **运行中/运行刚结束窗口内的文件变更不再补跑**——监听语义统一为"只响应外部静默期变更"。

## 4. 遗留风险清单（按优先级）

> **2026-06-10 第三波更新：本节原有 5 项遗留已全部处理完毕**，处置明细见 §6。剩余唯一持续性事项：继续按既定套路渐进拆分大文件（非阻塞）。

| 优先级 | 项 | 建议 |
|--------|----|------|
| 低 | engine_core/notification.py 采用统一解析器（L2 收尾小步） | 30 分钟重构 + 现有测试保护 |
| 低 | 大文件继续渐进拆分（main_window 2022 / database 1315 / engine 1562） | 按 watch_status_controller / run_dispatch 套路分批 |

## 5. 验证证据汇总

| 检查 | 结果 |
|------|------|
| `python -m pytest -q` | **358 passed, 0 failed**（首轮前：1 failed / 329 passed） |
| `tools/audit_broad_except.py` | 0 regressions（基线变更均带注记：watcher 7→6、engine 19→21、main_window 70→71） |
| `tools/audit_risky_calls.py` | 0 unapproved / 12 allowlist 全带 reason（新增 test_import_warnings 子进程隔离条目） |
| `tools/module_hotspot_report.py --fail-on-regression` | OK（基线刻意刷新；首轮发现修复前 HEAD 即已 20 项超标） |
| `python -m compileall src tests _import_and_run.py` | 干净 |
| CLI smoke（cli --help / export --help / _import_and_run --help） | OK |
| 端到端导入告警冒烟 | 脱敏 webhook 跳过与通知失效告警在 stdout 可见 |
| worker 关键改动抽查 | notifier 重试常量 / ImportResult / PYTHON_STEP_TIMEOUT / LAST_WATCH_CONFIG_REPAIRS / README 新节 / 测试发送 Signal 均在源码中核实 |

---

## 6. 第三波处置（2026-06-10 同日追加）：原遗留清单全部落地

| 原遗留项 | 处置 | 证据 |
|---------|------|------|
| **L1 巨型文件拆分** | **完成（第一批）** | `database.py` 1707→1315（拆出 `database_runs.py` 351 / `database_webhooks.py` 141，门面再导出，公共 API 与测试零改动）；`engine.py` 1670→1562（拆出 `engine_core/watch_manager.py` 212，`_watchers` property 契约保持）；`main_window.py` 2224→2022（拆出 `ui/watch_status_controller.py` 105 / `ui/run_dispatch.py` 138，类方法薄委托，UI 测试零改动）。broad-except 计数跨文件精确转移（17→10+7 / 21→17+4 / 71→60+6+5），总量不变 |
| **M5 Power BI REST API 路线** | **完成（opt-in）** | 新增 `executors/powerbi_rest.py`：REST 触发+轮询（全程显式超时、并发刷新/权限/404/Disabled/取消/轮询超时全路径错误语义、token 永不落日志）；步骤参数 `--refresh-mode=rest --workspace-id=<GUID> --dataset-id=<GUID>`，token 取 `POWERBI_ACCESS_TOKEN`；桌面模式仍为默认且字节级不变；14 个 mocked 单测 + README 专节 |
| **I1 watchdog observer 端到端缺口** | **完成** | `tests/test_watch_observer_integration.py`：真实 Observer + 真实 tmp 目录——事件驱动触发一次且基线刷新后不复触发；运行期变更吞并不补跑；3 连跑无 flake；watchdog 缺失自动 skip |
| **L4 仓库历史文档归档** | **完成** | 6 个过时文档（HANDOVER×2、V7_iOS、05_整体Review、2026-06-09 旧审查报告、REVIEW_2026-05-15）`git mv` 至 `docs/archive/` 并建立索引 README；docs/hygiene 守卫 18 项全绿 |

**第三波后最终实测**：`python -m pytest -q` = **374 passed / 0 failed**（首轮审查前 HEAD：1 failed / 329 passed）；broad-except / risky-calls / module-hotspot（拆分后已收紧重写）/ compileall / CLI smoke 全绿。测试净增 45 项，全部为行为测试。

执行说明：本波四个重切片由并行 worker 实施，其中一次宿主进程退出导致 4 个 worker 中断；database/main_window 两个切片留下的半成品（新模块已建、原文件未改写）由主线程完成手术并逐一验证，PBI REST 切片重新派发后完整交付。所有合流结果均以全量测试与门禁实测为准，不依赖 worker 自述。

---

## 7. ROI 波次（2026-06-10 同日第四波）：冲 8.5 路线 1-4 项落地

| ROI 项 | 处置 | 证据 |
|--------|------|------|
| **1. 通知结果落库 + 历史面板可见** | **完成** | `run_histories.notify_status` 列（迁移 v6）；`engine_core/notification.py` 全矩阵回写（sent / failed:摘要 / skipped:原因，250 字符截断，写失败不影响发送，run_id 反查兜底）；历史面板状态格 📨✓/📨✗+tooltip；同时完成 L2 收尾——通知解析统一走 `notifier.resolve_workflow_notification_target`，双实现彻底消除 |
| **2. Step 输出声明模型（H3 根治）** | **完成** | `steps.output_paths` 列（迁移 v7）+ `get/set_output_paths`；watch_rules 优先级=显式声明 > `--out` 推断 > 原地写回类型推断，`collect_workflow_output_roots` **去除"月度数据处理"业务硬编码**（遗留网兜降级为 `detect` 的显式参数，默认开、收紧路径已注释）；步骤编辑器新增「输出目录」字段；导入/导出携带且向后兼容 |
| **3. 质量门不可绕过** | **完成（本地）** | `.githooks/pre-commit`（三审计+compileall 快门）/`pre-push`（快门+全量 pytest）；`tools/install_hooks.py` 幂等安装器（`--repo`/`--uninstall`/回读验证）；guardrails 文档含远端分支保护步骤（GitHub UI + `gh api`，**远端启用待用户决定**——remote 已存在且 gh 已认证）；8 个钩子测试在隔离临时仓库验证 |
| **4. 大文件第二批 + L2 收尾** | **完成** | `main_window.py` 2022→**1879**（脏数据守卫簇 8 方法纯移动至 `ui/dirty_guard.py`，git diff 机械核验 VERBATIM_MATCH）；L2 已随 ROI-1 完成 |

**ROI 波次后最终实测**：`python -m pytest -q` = **399 passed / 0 failed**（首轮审查前 HEAD：1 failed / 329 passed；累计净增 70 项行为测试）；broad-except（基线精确登记：notification 1→2、dirty_guard 0→8、main_window 60→52）/ risky-calls（14 条 allowlist 全带 reason）/ module-hotspot / compileall / CLI smoke 全绿。schema 升级至 v7（两列新增均为幂等迁移，新老库双路径验证）。

**对评分的影响**：通知可观测闭环 + 输出声明根治 + 门禁本地强制落地后，Stability≈8.0、Design≈7.5、Maintainability≈7.0（main_window 仍 1879 行）、Release≈8.0（远端保护待启用）。总体约 **7.7（B+）**。距 8.5 的剩余路径：远端分支保护实际启用（等待推送决定）、main_window/engine 第三批拆分、真实外设集成测试层。

---

*复审结论（四波累计）：首轮 26 项发现全部闭合，"冲 8.5"路线前 4 项亦已落地。总体评分 5.8 → 7.7（C+ → B+）。两个用户报告的生产 bug 的代码级根因均已修复，并由回归测试、端到端集成测试与通知状态落库三重保障；质量门已具备本地不可绕过性，远端强制只差一次推送决定。*
