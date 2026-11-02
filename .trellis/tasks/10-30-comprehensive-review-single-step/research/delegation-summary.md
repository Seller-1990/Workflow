# 子代理续办阶段 — Research Summary（2026-10-31 收尾）

状态：整体任务 **`in_progress` / 未归档**；Phase 10、Phase 11 已完成（本地代码与自动验证闭环），Phase 6 原生 **`blocked`**。

## 结论（以 `.dsh-tmp/verify-recheck-20261031-02/completion-result.json`（15:10:55）为准）

1. **源码绑定**：checkpoint **291** 路径，drift 0 / missing 0；受影响范围与 CLI demo 前后均匹配。
2. **门禁实跑**：hotspots **0 回归**（checker/baseline 未改）、untracked Python **88 文件 0 命中**、compile / requirements / broad / risky / tracked-hygiene / environment / tracked-diff 全 **exit 0**。
3. **测试**：受影响 5 模块 **69 passed / 7.17s**；收集 **968**；全量 **967 passed / 1 skipped / 2 既有 warnings / 224.25s**，`source_unchanged=true`。
4. **fresh CLI demo**：exit 0；执行步骤 `[2,2,3]`、2 条成功 history、3 条 StepLog、owner 全释放、保存默认值未变、非法区间按预期 exit 2；42 条审计事件、33 条 SQLite 事件全部允许且位于输出目录、阻断网络事件 0（审计只覆盖其自身 9 个子进程）。
5. **未完成**：working-strict 本轮 **not run**（51 为历史计数）；原生 Phase 6 **blocked 且未执行**；新交付副本与 closeout 尚未生成。

## 三项只读审计的实际结论

- **hygiene**：工作副本历史 **51 项 local-residue**（47 缓存 + 4 根 runtime/build 目录），全部保留、未删除；跨 14 文件的 **20 处 CRLF 末尾空白行**已移除。
- **hotspot**：真实职责拆分落地，本轮热点门 **0 回归**，测试未删除/压缩，基线未抬。
- **native acceptance**：**无可执行的原生输入证据**——无新 harness、无新窗口、无 `SendInput`；用户工具选择存在，但执行方以授权可见性不足拒绝接手，主会话坚持边界、不换执行器绕过。**不得写成“用户从未授权”，也不得据此声称原生矩阵通过。**

## 两项窄重构的实际结果

- **EOF 空白**：14 个列明文件移除 **20 处**末尾空白行（**6 文件各 2 行、8 文件各 1 行**，40 字节）；AST 等价 14/14、忽略 EOL 与末尾空白后文本等价 14/14、孤立 LF = 0、CRLF 改前改后一致。**授权措辞为“每文件一个空行”，实际 6 文件删两行——偏差保留披露，不追溯改授权原文**；也**不得**把清理写成“原本干净/空操作”。
- **热点拆分**：dialog 11 → 8 函数、presentation 3 函数（`tests/test_script_run_args_dialog_presentation.py`），收集 ID 12 → 12；`tests/conftest.py` 路径配置移至 `pytest.ini`（7 行 / 5 行），pytest 8.3.3 下 SRC 优先保持。证明用 `node-id-comparison-v3.json` 的 4 条显式映射 + **Counter 多重集**比较：未映射 964 一致、映射后 968 相等、重复 0。
- **必须保留的错误披露**：原始 `l2/node-id-comparison.json`（match=false）来自静态 AST 预测漏掉 parametrize 展开；且 L3 全量曾在修正前运行过。

## 证据边界（不可外推）

- 真实 DB：只有“静态配置 + 隔离产物 + 真实文件 size/mtime 未变（`stat`：163840 / 2026-08-11）”这一层；`real_db_opened=false` **不是** pytest 整链实测，mtime/size 不变 ≠ 从未打开或读取。
- CLI 的 33 条 SQLite 日志（全部 allowed、guard 加载 9 个 child process、阻断网络事件 0）只确证这 9 个子进程，不能回溯 pytest 链，也不覆盖脚本孙进程。
- 隔离 INI 至少一次重定向 **≠** 注册表未被写；显式 `QSettings(path, IniFormat)` 按设计绕过，真实注册表刻意未查。
- pytest 链路**无 socket 级审计**，“无网络”属**未测量**（仅弹出钉钉 webhook 环境变量让集成用例跳过）。
- CLI 审计不覆盖 pytest 链，也不覆盖 demo 步骤派生的孙进程。

## 历史有效性与新封存口径

- `completion-delivery-20261031-final02`（505 文件 / 267 Python）、`completion-context-20261031-final02`、`completion-closeout-20261031-final01`（`mechanical_closeout_passed=true`、`all_task_complete=false`、`all_quality_gates_green=false`）**仅对其自身封存快照有效**，未被改写；当前工作树已不匹配其完整 hash 集合。
- 历史 `full03` 967 / `affected03` 612 / `cli-demo02` / `gates03` / `owned-freezes03` / `193` 文件 map 均为**更早源码身份**的结果，不能用于验收当前源码。
- 本轮新副本与外部封存**尚未生成**；规划路径为 `.dsh-tmp/completion-delivery-20261031-delegated01/source/` 与 `.dsh-tmp/completion-closeout-20261031-delegated01/result.json`，**路径为规划值，未通过、计数未知**。

## 需要阅读完整证据的情形

- 核对本轮任一数字：读 `.dsh-tmp/verify-recheck-20261031-02/completion-result.json` 及其 `l0/`、`l1/`、`l2/`、`l3/`、`cli-demo/` 子目录。
- 核对 ID 迁移：读 `node-id-comparison-v3.json`（现行）与 `l2/node-id-comparison.json`（保留的错误记录）。
- 核对 Phase 9 后端实现与契约：读 `research/completion-summary.md`、`research/evidence/remaining-work-verification.md`。

## 未解决

- 原生稳定输入通道仍未证明（两次无业务探针 `checks=[]`，第二次 snapshot 超时；根因未定），Phase 6 完整矩阵未验收。
- working-strict 未在本轮运行，当前值未知。
- 本轮新交付副本 / closeout 尚未生成。
