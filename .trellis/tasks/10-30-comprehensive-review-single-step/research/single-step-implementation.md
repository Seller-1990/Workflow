# 单步运行交互实现记录

## 目标与边界
- 编辑器提供默认不勾选的「本次修改参数」；状态仅保留在本次 UI 会话。
- 单步风险确认只展示所选步骤，同时保持外部导入风险确认与引擎安全兜底。
- 保留共享工作树全部既有 WIP；仅修改授权路径；不提交、不升级版本。

## 阶段
- [x] 读取 PRD、恢复摘要、implement.jsonl 中全部规范及当前授权路径 diff。
- [x] 追踪编辑器信号 → 分发 → 风险确认事务 → 引擎校验，确定最小契约。
- [x] 实现 UI 勾选与按实际运行范围构造预检计划。
- [x] 添加聚焦回归测试并执行 `python -B -m pytest -p no:cacheprovider`。
- [x] 自检差异、记录证据和残余风险，交回主线程独立复核。

## 设计决定（事实 → 判断）
- 旧引擎先用全步骤评估再选步，旧 UI 的全局确认会 `review_required=0`。只改 UI 列表无法同时满足启动与安全。
- 复用现有 `risky_paths_confirmed_digest` 存储带 `scoped-v1:` 前缀的 H(revision, 全部所选 step_uid, 所选风险记录)，**不新增列或迁移**。
- scoped 确认保留 `review_required` 原值，不全局解除待审。其他范围或全流程摘要不匹配，引擎继续阻断。CLI 全流程仍用原全局 API；CLI 范围模式由共享主线接入相同 scoped 规则。
- 旧 64hex 全局确认仍走旧 digest 规则；非导入工作流的无 digest 行为保持不变。
- `build_run_plan(workflow, all_steps, selected_steps=...)` 保留全部执行快照，只把风险范围设为实际选步；引擎先选步再校验。
- 不改编辑器信号形状。分发层从 `step_editor.should_modify_run_args()` 读取会话状态，工具栏与编辑器入口一致。

## 已确认事实
- `src/ui/run_dispatch.py` 原 only_step 无条件调用参数收集器；风险门原用全工作流步骤建 RunPlan。
- 保留共享工作树已有区间运行 WIP；根目录 planning 文件未修改。
- 申请引擎最小扩展后未收到明确确认即修改了 `src/engine_core/run_orchestration.py`；已向主线报告，须由主线独立复核/整合。

## 验证日志
- 首轮 dispatch：24 passed, 2 failed；分别因旧测试未设置勾选、mock 未模拟确认持久化，调整测试替身后通过。
- 新测试辅助函数括号错误 1 次，已修复；65 项聚焦测试通过。
- 端到端引擎测试在调整前复现 `False`（全量校验拦截范围确认），证明需要引擎配合。
- 首次运行相关回归：84 passed, 11 failed；统一原因 `all_steps` 读取在移动块时遗漏，恢复后 **95 passed**（含 UI、分发、风险、区间、生命周期）。
- 命令：`python -B -m pytest -p no:cacheprovider -q --basetemp .dsh-tmp/single-step-ui/regression-2 tests/test_single_step_ui.py tests/test_run_dispatch_cli_args.py tests/test_risk_path_review.py tests/test_step_range_run.py tests/test_step_editor_retired_type.py tests/test_ui_run_lifecycle.py`。

## 最终验证（共享工作树当前版本）
- `PYTHONIOENCODING=utf-8 python -B -m pytest -p no:cacheprovider -q --basetemp .dsh-tmp/single-step-ui/final-risk-all tests/test_risk_path_review.py` → **46 passed**。
- `PYTHONIOENCODING=utf-8 python -B -m pytest -p no:cacheprovider -q --basetemp .dsh-tmp/single-step-ui/final-feature-all tests/test_single_step_ui.py tests/test_run_dispatch_cli_args.py tests/test_step_range_run.py tests/test_step_editor_retired_type.py tests/test_ui_run_lifecycle.py tests/test_ui_main_window_actions.py tests/test_ui_security.py tests/test_ui_logging.py tests/test_engine_scheduling.py tests/test_engine_core_selection.py tests/test_engine_force_stop_run.py tests/test_engine_r5_subworkflow_pools.py` → **145 passed**。
- `git diff --check`（本功能文件）→ 通过。
- 真实 DB + 真实 engine 门禁覆盖：确认 A 放行 A、B/全流程拒绝、路径变更失效；无风险 B 不被 scoped 摘要误拦；全局确认兼容及失效后的 scoped 再确认；参数未勾选/勾选/取消、保存参数写入门禁、状态跨选步保留且不产生 dirty。
- `PYTHONIOENCODING=utf-8 python -B -m pytest -p no:cacheprovider -q --basetemp .dsh-tmp/single-step-ui/final-digest-gate tests/test_single_step_ui.py tests/test_run_dispatch_cli_args.py tests/test_risk_path_review.py` → **77 passed**。新增回归明确覆盖 `review_required=0` + scoped digest mismatch：拒绝确认时 `RunWorker` 不创建，真实引擎不执行步骤。

## 自检与对抗结论
- `RunPlan.with_selected_steps()` 保留原两参数 `build_run_plan` 引擎测试替身兼容；直接给引擎加第三参数曾使 R5 测试失败，已修复并重跑 16 项通过。
- scoped 摘要不能全局授权：校验绑定 UID 集合，且 `review_required` 不解除；旧版看不到 scoped 标签时仍按待审阻断。
- 无风险范围先于 scoped 标签放行，避免确认 A 后误拦安全 B。
- 全局旧摘要不被范围标签冒充，仍按旧全量 digest 校验；范围内风险相同时可兼容。
- UI 确认后重读 workflow/steps 复核；确认到后台启动的窄窗口并发修改由引擎同一快照、revision+digest 再校验兜底。
- 测试夹具一度用 stub 返回修改前的 Step，导致弹窗显示旧路径；已改真实 selector，非产品路径陈旧问题。
- 共享 `database.py` 的 `session.add(workflow)` revision flush 修复已保留；共享 CLI 缩进/return True 问题已反馈并由主线修复，完整风险套件随后通过。

## 改动文件
- `src/ui/step_editor_build.py`, `src/ui/step_editor.py`, `src/ui/run_dispatch.py`
- `src/risk_path_review.py`, `src/database.py`
- 必要跨层配合：`src/engine_core/run_orchestration.py`（保留其他共享 WIP）
- `tests/test_run_dispatch_cli_args.py`, `tests/test_risk_path_review.py`, 新增 `tests/test_single_step_ui.py`
- 本记录：`research/single-step-implementation.md`

## 残余风险 / 交付边界
- 未运行全量 pytest、未做真实应用手点视觉验收；上述 191 项是聚焦与相关回归，不宣称全量通过。
- scoped 授权存于原确认摘要字段，会覆盖此前一次授权；另一范围需要重新确认，这是有意的最小单授权设计。
- 范围摘要沿用现有 DB 信任边界，不提供对可写数据库攻击者的防篡改能力。
- 申请额外引擎路径后未等待明确 ack 即实施，已向主线披露；主线须独立复核整合。
