# Workflow V2 能力扩展开发计划

日期：2026-06-06

## 1. 目标定位

当前应用已经具备“本地工作流管理器”的基础能力：工作流、阶段、步骤、Python / Excel / Power BI / 子工作流执行、文件监听、钉钉通知、运行历史和日志。下一阶段不建议直接复制 n8n 的大画布，而应先把内部运行模型从“脚本排序运行”升级为“可观测、可校验、可恢复的本地数据工作流运行时”。

目标产品定位：

- Windows 本地数据工作流自动化桌面应用。
- 面向 Excel、Power Query、Power BI、Python 清洗脚本、月度报表和本地文件流转场景。
- 优先解决日常工作中的可重复、可审计、可排障问题，而不是先做通用 SaaS 编排平台。

典型目标流程：

```text
手动触发 / 文件夹监听
-> 检查本月源文件是否齐全
-> 检查文件修改时间是否为本月
-> 读取 Excel 基础信息
-> 校验行数、关键列、重复键
-> 如果异常：钉钉通知 + 停止
-> 刷新 Excel Power Query
-> 运行 Python 清洗脚本
-> 刷新 Power BI
-> 导出产物清单
-> 钉钉通知成功，附运行摘要
```

## 2. 参考系统取舍

| 系统 | 值得吸收的能力 | 不直接照搬的部分 | 对本项目的启发 |
|---|---|---|---|
| n8n | 节点分类、触发器、节点输出 pinning、错误工作流、子工作流 | Web SaaS 画布优先、海量第三方 SaaS 连接器 | 先做节点类型与输出快照，再考虑画布 |
| Node-RED | message/context 模型、subflow、轻量事件流 | 面向 IoT/消息流的通用编辑器 | 用 DataPacket 统一步骤之间的数据与元信息 |
| Airflow | task/sensor、依赖、重试、运行历史 | 服务端调度器和复杂部署 | 引入文件检查/等待类节点和运行对账 |
| Prefect | task/deployment、状态模型、重试与可观测性 | 云端控制面 | 强化状态机、失败语义、运行摘要 |
| Dagster | asset 思维、数据质量与 lineage | 资产平台复杂度 | 把产物 Artifact 作为一等对象记录 |

结论：先建“节点语义 + 数据包 + 产物 + 状态机”，再做可视化画布。画布只是编辑体验，不能替代运行时能力。

## 3. 核心模型

### 3.1 DataPacket

`DataPacket` 是节点之间传递的轻量结构，不直接承载大文件内容，只承载引用、摘要和上下文。

字段建议：

```text
id
run_id
node_id
schema_version
status
payload_json
metadata_json
artifact_ids
created_at
```

使用原则：

- 大文件只记录路径、hash、大小、mtime，不直接存数据库。
- 表格只记录 schema、行数、列摘要、采样和质量结果。
- 失败时记录可诊断上下文，避免只留下字符串日志。

### 3.2 Artifact

`Artifact` 记录工作流产生或消费的重要文件/表格/报表。

字段建议：

```text
id
run_id
node_id
artifact_type
path
name
size_bytes
mtime
sha256
summary_json
created_at
```

典型类型：

- source_file
- cleaned_file
- excel_workbook
- powerbi_file
- log_bundle
- report_export

### 3.3 NodeResult

当前 `ExecutorResult` 偏执行器进程结果，V2 需要提升为节点语义结果。

字段建议：

```text
success
status
exit_code
message
data_packet
artifacts
quality_issues
next_ports
started_at
ended_at
duration_seconds
```

### 3.4 节点分类

第一阶段只做必要节点，不做连接器市场。

| 分类 | 节点 | 用途 |
|---|---|---|
| Trigger | ManualTrigger, FileWatchTrigger | 手动和文件监听 |
| Control | If, Switch, Stop, Continue | 条件分支和停止 |
| Data Check | FileCheck, TableQualityCheck | 文件齐套、mtime、行数、字段、重复键 |
| Action | PythonScript, ExcelRefresh, PowerBIRefresh, SubWorkflow | 现有执行器节点化 |
| Notify | DingTalkNotify | 运行摘要和异常通知 |
| Utility | ArtifactManifest, OutputSnapshot | 产物清单和输出快照 |

## 4. 数据库演进

保留现有 `workflows / stages / steps / run_history / step_logs`，新增 V2 表，不在第一步破坏旧数据。

建议新增：

```text
workflow_nodes
workflow_edges
node_runs
node_snapshots
data_packets
artifacts
credentials
```

兼容策略：

- Phase 1 中，现有 `steps` 仍是运行主路径。
- 新节点模型先以“shadow metadata”方式存在，不强制迁移所有旧步骤。
- 每次写入新表都带 `schema_version`。
- 所有迁移必须可重复执行、失败 fail-fast、保留备份。

## 5. Phase 1：节点语义与安全运行基线

目标：不做大画布，先把现有步骤升级为明确的节点语义，并修掉审查报告中的高风险假成功/假健康问题。

开发任务：

1. 定义 `src/workflow_core/` 基础模型：
   - `node_definition.py`
   - `ports.py`
   - `data_packet.py`
   - `artifact.py`
   - `node_result.py`
   - `execution_context.py`
2. 引入节点类型枚举和端口语义：
   - 输入端口：main、condition、artifact
   - 输出端口：success、failure、true、false、manual_required
3. 将现有执行器结果适配为 `NodeResult`：
   - Python / Excel / Power BI / SubWorkflow 先做 adapter，不重写执行器。
4. 修复运行语义基线：
   - Power BI 自动刷新失败不得返回成功。
   - 子工作流取消/超时不得伪装成已干净结束。
   - 并行步骤异常必须保证 step log 收敛到终态。
   - watcher 冲突和 all-folders 触发语义修正。
5. 增加最小节点：
   - Stop/Error
   - If
   - FileCheck
6. UI 暂不做新画布：
   - 在现有阶段卡片/步骤编辑器中增加“节点类型”和输出摘要字段。

验收标准：

- 现有工作流不需要迁移即可运行。
- Power BI、子工作流、watcher、导入安全等审计高风险问题有测试覆盖。
- 新增 `NodeResult` 不破坏现有 `ExecutorResult`。
- `pytest -q`、`compileall`、`repo_hygiene` 全部通过。

## 6. Phase 2：DataPacket、Artifact 与调试能力

目标：让每个节点都有可检查的输入/输出摘要，日常排障不再只靠日志文本。

开发任务：

1. 新增 `data_packets` 和 `artifacts` 表。
2. 每个步骤运行完成后记录：
   - 输出摘要
   - 重要文件产物
   - 质量检查结果
3. 增加输出快照：
   - 最近一次运行输出
   - 历史节点输出对比
   - 错误节点上下文
4. 增加 pin node output：
   - 节点可固定上次输出用于调试。
   - pin 只用于手动调试，正式运行默认禁用或显式标记。
5. 增加 run from node / upstream-only：
   - 从某节点开始运行。
   - 只运行上游依赖。
6. UI 增加节点详情页：
   - 输入摘要
   - 输出摘要
   - 产物清单
   - 质量问题
   - 原始日志入口

验收标准：

- 每个运行过的节点都有可读输出摘要。
- 大文件不进入 SQLite，只记录引用和 hash。
- pin 输出不会污染正式运行历史。
- 从节点运行不会破坏现有阶段运行逻辑。

## 7. Phase 3：业务模板与数据质量节点

目标：把“月度报表流程”从脚本堆叠变成模板化工作流。

开发任务：

1. 增加模板系统：
   - 月度源文件检查模板
   - Excel PQ 刷新模板
   - Python 清洗模板
   - Power BI 刷新模板
   - 成功/失败通知模板
2. FileCheck 节点增强：
   - 文件是否存在
   - mtime 是否在本月
   - 文件大小是否异常
   - 文件名模式是否匹配
3. TableQualityCheck 节点：
   - 行数阈值
   - 必填列
   - 重复键
   - 空值比例
   - 数值范围
4. DingTalkNotify 增强：
   - 运行摘要
   - 失败节点列表
   - 产物清单
   - 数据质量问题摘要
5. 模板参数化：
   - 月份
   - 源目录
   - 输出目录
   - 报表文件
   - 通知机器人

验收标准：

- 用户可以从模板创建完整月度流程。
- 无需写新 Python 脚本即可完成文件齐套和基础表质量检查。
- 失败通知能告诉用户“缺什么、错在哪、哪个文件”。

## 8. Phase 4：可视化编排与插件化

目标：在运行模型稳定后，再做可视化画布和插件扩展。

开发任务：

1. 可视化 DAG/画布：
   - 节点拖拽
   - 连线
   - 端口
   - 条件分支可视化
   - 运行状态覆盖层
2. 节点配置面板：
   - 统一表单 schema
   - 参数校验
   - 默认值
   - 高级选项折叠
3. 插件 SDK：
   - 节点定义
   - 参数 schema
   - 执行函数
   - 输出 schema
   - 测试夹具
4. Credential vault：
   - 短期：URL 校验 + 本地敏感扫描 + 明确脱敏
   - 中期：Windows DPAPI / Credential Manager
   - 长期：多后端 credential provider
5. Durable runtime 增强：
   - 运行心跳
   - 启动对账
   - orphan run 收敛
   - 通知 outbox
   - 可恢复 checkpoint

验收标准：

- 画布只是现有节点模型的编辑器，不产生第二套运行语义。
- 插件节点必须有 schema、测试和安全边界。
- 凭据不再以明文长期留在 SQLite 主表。

## 9. 并行开发切分

适合并行的子任务：

| 子任务 | 写入范围 | 风险 |
|---|---|---|
| Runtime 语义修复 | `src/engine.py`, `src/engine_core/*`, `src/executors/*` | 高 |
| Import/DB 安全 | `src/database*.py`, `src/database_import_export.py`, `tests/test_schema_guards.py` | 高 |
| Workflow Core 模型 | `src/workflow_core/*`, 新测试 | 中 |
| Artifact/DataPacket | 新表、新模块、新测试 | 中 |
| UI 输出摘要 | `src/ui/*` 局部面板 | 中 |
| CI/Repo Hygiene | `.github/*`, `tools/*`, `tests/test_repo_hygiene.py` | 低 |
| 文档/模板 | `docs/*`, template fixtures | 低 |

并行规则：

- 不允许两个任务同时修改同一文件。
- 数据库迁移只能串行合并。
- 运行时状态机相关改动必须先过单元测试，再进 UI。
- 画布开发必须等待 `workflow_core` 和 `node_runs` 稳定。

## 10. 风险与决策

短期不做：

- 不做完整 n8n 克隆。
- 不做云端调度服务。
- 不做插件市场。
- 不把大文件内容塞进 SQLite。

必须优先做：

- 修复假成功、假健康、导入安全和运行状态收敛。
- 建立节点输出和产物的可观测性。
- 保持旧工作流兼容。
- 保持 Windows 本地工作体验。

关键决策：

- V2 以现有模型兼容演进，不推倒重来。
- Phase 1 到 Phase 3 都以“无画布也能提升工作流能力”为准。
- Phase 4 再做画布，避免把 UI 当成架构核心。
