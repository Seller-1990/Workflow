# 实施 Context7 复核优化项

## Goal

落实 Context7 复核后除可选新功能外的优化项，提高发布可靠性、数据库删除稳定性、运行线程边界、运行历史性能、版本一致性和热点模块可维护性。

## Requirements

- 删除工作流时避免 ORM 级联加载大量运行历史/步骤日志导致事务和内存放大。
- 修复 release hygiene 与已跟踪打包产物、本地 residue 的冲突，使严格检查适合发布流程。
- 收敛 GUI 运行线程生命周期，避免裸线程与 Qt 对象交互边界继续扩散。
- 优化运行历史分页摘要，加载更多时不重复汇总已加载历史。
- 补强版本单一事实源，避免 README、包名、应用版本漂移。
- 对当前热点模块做伴随式精简，不做无业务收益的大拆分。
- 保持 PyInstaller 现有 certifi data 和 hidden imports 机制，并补强可验证的包元数据/文档一致性。

## Acceptance Criteria

- [ ] 工作流删除对关联 stages、steps、run_histories、step_logs、versions 使用明确的数据库级或批量删除策略，并有回归测试覆盖。
- [ ] `repo_hygiene --strict` 不再因为受版本控制的 `dist/*.exe` / `.sha256` 产物失败；本地 residue 策略清晰。
- [ ] 运行分发的后台执行边界有单一适配层，UI 线程更新只通过 Qt queued 信号/调用进入主线程。
- [ ] 运行历史分页加载仅查询新增历史的步骤摘要，既有测试更新。
- [ ] 当前发布版本文本从 `src/config.py` 同步或有测试防漂移。
- [ ] 打包 spec / README 中明显陈旧的版本文案被消除，打包输出仍从 `APP_VERSION` 推导。
- [ ] 相关质量门和针对性测试通过。

## Definition of Done

- 代码和文档改动通过相关单元测试。
- 运行 `audit_broad_except.py`、`audit_risky_calls.py`、`module_hotspot_report.py`、`run_tests.py --collect-only`。
- 对无法在本机完整验证的跨平台打包项说明残余风险。

## Out of Scope

- 不实现钉钉加签 webhook 新功能。
- 不做大规模 UI 重设计。
- 不做完整 macOS 本机实包验证，除非当前环境具备 macOS runner。

## Technical Notes

- Context7 直接 stdio MCP 已验证可用：Context7 v3.2.3。
- 关键依赖文档见 `research/context7-docs.md`。
- 高风险动作：移出已跟踪 exe/sha256 产物属于版本库清理，执行前需确认或采用非破坏性替代。
