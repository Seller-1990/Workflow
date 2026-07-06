# Implement Remaining Workflow Optimization Slices

## Goal

按 `docs/09_项目图谱与优化方案_2026-07-06.md` 中剩余优化建议依次实施，优先级保持：正确性/稳定性 > 速度/性能 > 可维护性/精简 > 新功能。

## Requirements

* 依次推进剩余优化项，中途除非涉及用户确认事项，否则不中断。
* 优先完成稳定性类优化：执行器取消契约、RunHistory/StepLog 一致性、UI 运行状态、监听防护、导入导出边界。
* 随后推进性能类优化：UI 高频刷新、数据库分页/索引。
* 再推进维护性优化：热点模块渐进拆分、Trellis spec 补全。
* 最后评估并实现低风险新功能，避免依赖未稳定的能力。

## Acceptance Criteria

* [x] 执行器取消契约统一并有测试覆盖。
* [x] RunHistory / StepLog 终态一致性服务化或等价收敛，并有测试覆盖。
* [x] UI 运行状态单一事实源有增量收敛和测试覆盖。
* [x] 文件监听防护测试增强。
* [x] 导入导出 schema / 安全边界增强。
* [x] 性能热点至少完成一项低风险优化或验证性测试。
* [x] 维护性 spec 和文档更新。
* [x] 可运行的验证命令已执行；若环境阻塞，记录阻塞证据。

## Out of Scope

* 不做破坏性数据迁移。
* 不安装依赖或访问外部服务，除非用户确认。
* 不做一次性大重构。

## Technical Notes

* Source plan: `docs/09_项目图谱与优化方案_2026-07-06.md`
* Current blocker for full pytest: local environment misses `sqlalchemy`, `PySide6`, and `watchdog`.
