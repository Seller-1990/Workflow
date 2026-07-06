# Workflow Reliability Optimization Plan

## Goal

梳理 Workflow 项目图谱，并按“正确性/稳定性 > 速度/性能 > 可维护性/精简 > 新功能”的优先级形成整体优化方案；方案写入项目文档，经过整体审查后等待用户确认，再进入实施。

## What I Already Know

* 用户要求先修复停止运行无效的问题，再使用 Trellis 和 grill-with-docs 梳理后续优化方案。
* 停止问题已定位在并行批调度：取消后仍继续补提交后续步骤。
* 已修复 `engine_core.scheduler` 支持取消后停止补提交，并让 `step_execution` 传入取消判定。
* 项目是 Python + PySide6 桌面工作流编排工具，核心分层为 UI、编排引擎、执行器、SQLite 数据层、监听、通知、导入导出。
* 当前本机 `python -m pytest tests/test_executor_policies_engine.py -q` 因缺少 `sqlalchemy` 无法收集测试。

## Requirements

* 生成项目图谱，覆盖核心模块、职责、关键运行链路和风险点。
* 新增优化方案梳理 Markdown 文件并在其中维护方案。
* 方案必须按优先级排序：正确性/稳定性、速度/性能、可维护性/精简、新功能。
* 各模块方案写完后做一次整体审查，避免单模块视角导致遗漏。
* 整体审查后停在用户确认点，不直接实施后续优化。

## Acceptance Criteria

* [x] Trellis 已初始化。
* [x] Trellis 任务已创建。
* [x] 项目图谱已写入 Markdown 文件。
* [x] 优化方案已按优先级写入 Markdown 文件。
* [x] 已完成整体审查并调整方案。
* [x] 用户确认下一步实施切片。
* [x] Slice 1：并行取消调度语义已修正。
* [x] Slice 1：调度器取消回归测试已补充。
* [x] Slice 4：测试环境预检已扩展核心依赖检查。
* [x] Trellis backend quality spec 已记录取消调度契约。

## Definition of Done

* 文档可作为后续实施入口。
* 后续实施前有明确的首批切片。
* 不在用户确认前继续批量改动业务代码。

## Technical Approach

* 使用 repo 本地 README、docs、源码树、热点扫描、测试结构作为图谱依据。
* 使用 grill-with-docs 的要求：能从代码和文档发现的先自行检查，不向用户索取可推导信息。
* 使用 Trellis 记录任务状态，PRD 指向项目文档。

## Output

* `docs/09_项目图谱与优化方案_2026-07-06.md`

## Implementation Scope Confirmed

用户已确认先实施：

* Slice 1：取消与终态一致性
* Slice 4：测试环境与质量门

暂不实施 UI 状态投影重构、执行器契约全面统一、热点模块拆分和新功能。

## Out of Scope

* 不在本规划阶段实施后续优化切片。
* 不一次性重构热点大文件。
* 不新增用户功能。

## Technical Notes

* 项目热点扫描命令：`python tools/module_hotspot_report.py --top 20`
* 当前最大热点：`src/ui/main_window.py`, `src/ui/workbench_board.py`, `src/ui/theme.py`, `src/engine.py`, `src/ui/step_editor.py`, `src/database.py`, `src/cli.py`
* 完整 pytest 当前受本地依赖缺失阻塞：`ModuleNotFoundError: No module named 'sqlalchemy'`
