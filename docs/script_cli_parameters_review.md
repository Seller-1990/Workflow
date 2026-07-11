# 脚本附加命令行参数实现 Review

Review 日期：2026-07-11

## 结论

当前实现方向基本符合方案，但还不建议合并。主要原因是 GUI 入口未实际接通、运行时参数使用了共享 engine 状态、Windows 路径解析会损坏参数，以及日志脱敏存在泄露风险。

## Findings

### 1. High：运行前参数弹窗实际不会出现

位置：

- `src/ui/run_dispatch.py:145`
- `src/database.py:898-902`

问题：

`src/ui/run_dispatch.py` 中使用：

```python
from database import get_steps_by_workflow, get_workflow
```

但 `database.py` 中导出的是：

```python
get_workflow_by_uid
get_workflow_by_id
get_workflow_by_name
```

不存在 `get_workflow`。该 `ImportError` 被捕获后直接返回 `{}`，导致所有非 `retry_failed` 运行都会静默跳过临时参数收集，`prompt_run_arg_overrides` 不会被调用。

影响：

- 用户点击运行时不会看到“本次运行参数”弹窗。
- argparse 静态识别 UI 不会触发。
- 功能从 GUI 入口看等于未接入。

建议：

- 改为导入 `get_workflow_by_id`。
- 对 `_collect_run_arg_overrides` 增加测试，断言正常工作流会调用 `prompt_run_arg_overrides`。
- 不建议在导入失败时静默继续运行；至少应提示参数功能不可用。

### 2. High：临时参数挂在 `engine._run_arg_overrides`，会被嵌套/并行运行污染

位置：

- `src/engine_core/run_orchestration.py:254`
- `src/engine_core/run_orchestration.py:257`
- `src/engine_core/step_execution.py:194`

问题：

实现将本次运行参数保存到 engine 实例字段：

```python
engine._run_arg_overrides = normalize_run_arg_overrides(run_arg_overrides)
```

执行步骤时再从 engine 读取：

```python
getattr(engine, "_run_arg_overrides", None)
```

这会把本次运行上下文变成共享可变状态。子工作流 `allow_nested=True` 时会重写或清空同一个字段；如果父工作流还有并行步骤在执行，父级临时参数可能丢失或被错误覆盖。

影响：

- 并行步骤 + 子工作流场景下，临时参数可能不传给应接收的步骤。
- 不同运行上下文之间存在状态串扰风险。
- 违反方案中“不挂全局状态，随本次 run context 传递”的设计目标。

建议：

- 不要使用 `engine._run_arg_overrides`。
- 将 `run_arg_overrides` 作为本次运行上下文显式传递：

```text
run_workflow
  -> _execute_steps
  -> execute_step_attempt
```

- 或增加不可变 run context 对象，将运行参数作为 context 字段传递。
- 增加并行步骤 + 子工作流场景的回归测试。

### 3. Medium：Windows 路径会被参数解析破坏

位置：

- `src/script_arg_utils.py:54`

问题：

当前使用：

```python
shlex.split(raw, posix=True)
```

在 Windows 桌面应用中，用户很可能输入：

```text
--path C:\Data\2025
```

当前会解析成：

```python
["--path", "C:Data2025"]
```

反斜杠被当作转义符吞掉。

影响：

- Windows 路径参数会被破坏。
- 脚本收到错误路径，可能读取/写入失败。

建议：

- 实现 Windows-aware 命令行分词。
- 或使用 `posix=False` 后清理外层引号，但需要补足引号行为测试。
- 增加测试：

```python
parse_cli_args_text(r"--path C:\Data\2025")
parse_cli_args_text(r'--path "C:\Data Folder\2025"')
```

### 4. Medium：日志脱敏会泄露 `--token=xxx` 形式

位置：

- `src/script_arg_utils.py:98-104`

问题：

当前脱敏逻辑能处理：

```text
--token abc
```

但不能处理：

```text
--token=abc
--password=abc
--secret=abc
```

这些参数会被原样写入日志。

影响：

- 运行日志可能泄露 token、password、secret。
- 与项目已有 webhook/secret 脱敏要求不一致。

建议：

- 识别 `--key=value`。
- 敏感 key 输出为：

```text
--token=****
```

- 对包含 `access_token=` 的 URL 参数继续脱敏。
- 增加测试覆盖 `--token=abc`、`--password=abc`、`--webhook-url https://x?access_token=abc`。

### 5. Low：根目录存在实现过程临时文件

位置：

- `STATUS.md`
- `project_memory.md`

问题：

这两个文件看起来是实现过程 scratch 文件，不属于项目长期文档。

建议：

- 不要提交这两个文件。
- 如确有保留价值，应移动到明确的任务归档或开发文档目录，并说明用途。

## 验证记录

已运行：

```bash
python -m pytest tests/test_script_cli_parameters.py tests/test_script_cli_merge.py tests/test_ui_run_worker.py -q
python -m compileall src tests -q
```

结果：

- 20 passed
- compileall 通过

但当前测试未覆盖以下关键风险：

- GUI 入口 `_collect_run_arg_overrides`
- Windows 路径参数解析
- `--token=xxx` 形式脱敏
- 并行步骤 + 子工作流运行时参数隔离

## 建议修复顺序

1. 修复 `get_workflow` 错误导入，确保参数弹窗真正接入 GUI 运行入口。
2. 移除 `engine._run_arg_overrides` 共享状态，改为显式传递运行上下文。
3. 修复 Windows 命令行参数解析。
4. 修复 `--key=value` 敏感参数脱敏。
5. 补齐对应测试。
6. 清理根目录 scratch 文件。

## Review 通过条件

满足以下条件后可以再次 review：

- 点击 GUI 运行入口时能实际弹出“本次运行参数”对话框。
- 临时参数不会写入 `Step.args` 或数据库。
- 并行和子工作流不会污染父级临时参数。
- Windows 路径参数不被破坏。
- 明显 secret 不会出现在运行日志中。
- 新增测试覆盖上述关键路径。

