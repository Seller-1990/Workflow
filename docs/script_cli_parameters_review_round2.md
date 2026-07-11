# 脚本附加命令行参数实现二次 Review

Review 日期：2026-07-11

## 结论

二次修复后，上一轮发现的主要实现问题大多已经处理：

- GUI 入口错误导入已修复。
- `engine._run_arg_overrides` 共享状态已移除。
- Windows 路径解析已增加 `win32` 分支处理。
- `--token=xxx` / `--password=xxx` 形式已增加脱敏。

但当前仍不建议合并，因为既有测试套件出现回归失败。

## 当前阻塞问题

### High：`tests/test_executor_policies_engine.py` 仍有 3 个失败

验证命令：

```bash
python -m pytest tests/test_executor_policies_engine.py -q
```

结果：

```text
3 failed, 11 passed
```

失败用例：

```text
test_engine_run_sub_workflow_reuses_parent_context_without_lock_conflict
test_engine_run_sub_workflow_forwards_nested_cancel_event
test_execute_parallel_steps_stops_submitting_after_cancel
```

核心错误：

```text
fake_execute_steps() got an unexpected keyword argument 'run_arg_overrides'
fake_execute_single_step() got an unexpected keyword argument 'run_arg_overrides'
```

## 原因分析

本次实现把 `run_arg_overrides` 沿运行链路显式下传，这是正确方向。

相关位置：

- `src/engine_core/run_orchestration.py:314`
- `src/engine_core/step_execution.py:503`

当前代码会调用：

```python
engine._execute_steps(
    workflow,
    steps,
    run_history_id,
    log_dir,
    signal_policy=signal_policy,
    run_cancel_event=external_cancel_event,
    run_arg_overrides=local_run_arg_overrides,
)
```

以及：

```python
engine._execute_single_step(
    workflow,
    step,
    run_history_id,
    log_dir,
    signal_policy,
    prev_step_status_map=prev_step_status_map,
    run_cancel_event=run_cancel_event,
    run_arg_overrides=run_arg_overrides,
)
```

但 `tests/test_executor_policies_engine.py` 中的 monkeypatch 替身函数仍是旧签名，例如：

```python
def fake_execute_steps(
    current_workflow,
    steps,
    run_history_id,
    log_dir,
    signal_policy,
    run_cancel_event=None,
):
    ...
```

以及：

```python
def fake_execute_single_step(
    workflow,
    step,
    run_history_id,
    log_dir,
    signal_policy,
    prev_step_status_map=None,
    run_cancel_event=None,
):
    ...
```

这些替身不接受 `run_arg_overrides`，所以测试失败。

## 如何修复

### 1. 更新测试替身签名

在 `tests/test_executor_policies_engine.py` 中，将相关 fake 函数增加可选参数：

```python
run_arg_overrides=None
```

示例：

```python
def fake_execute_steps(
    current_workflow,
    steps,
    run_history_id,
    log_dir,
    signal_policy,
    run_cancel_event=None,
    run_arg_overrides=None,
):
    ...
```

以及：

```python
def fake_execute_single_step(
    workflow,
    step,
    run_history_id,
    log_dir,
    signal_policy,
    prev_step_status_map=None,
    run_cancel_event=None,
    run_arg_overrides=None,
):
    ...
```

### 2. 增加断言，避免只“兼容参数”但没验证行为

建议在相关测试中增加断言：

```python
assert run_arg_overrides in (None, {})
```

或在需要验证传递链路的新增测试中断言：

```python
assert run_arg_overrides == {"step-a": ["--year", "2025"]}
```

推荐至少新增一个 focused test：

```text
engine.run(..., run_arg_overrides={"step-a": ["--year", "2025"]})
  -> _execute_steps receives same overrides
  -> _execute_single_step receives same overrides
  -> execute_step_attempt merges fixed + temporary args
```

### 3. 不建议通过吞掉参数来修测试

不要改成：

```python
if run_arg_overrides:
    engine._execute_steps(..., run_arg_overrides=run_arg_overrides)
else:
    engine._execute_steps(...)
```

原因：

- 这会让调用路径出现两种签名分支。
- 测试虽然可能过，但运行链路契约不清晰。
- 项目内部已经显式扩展了 `_execute_steps` / `_execute_single_step` 签名，应让测试替身跟随新契约。

## 已复核通过的修复点

### 1. GUI 入口导入问题已修复

上一轮问题：

```python
from database import get_steps_by_workflow, get_workflow
```

当前已改为：

```python
from database import get_steps_by_workflow, get_workflow_by_id
```

方向正确。

### 2. 共享 engine 状态已移除

上一轮问题：

```python
engine._run_arg_overrides = ...
```

当前改为：

```python
local_run_arg_overrides = normalize_run_arg_overrides(run_arg_overrides)
```

并沿调用链显式传递。方向正确。

### 3. Windows 路径解析已补

当前 `parse_cli_args_text` 会在 Windows 上使用：

```python
posix = sys.platform != "win32"
```

并增加了测试：

```python
parse_cli_args_text(r"--input C:\Data\2025")
parse_cli_args_text(r'--input "C:\My Data\file.txt"')
```

方向正确。

### 4. `--key=value` 脱敏已补

当前已增加：

```python
--token=****
--password=****
```

相关测试也已覆盖。

## 建议补充测试

当前新增测试覆盖了参数解析、脱敏、run dispatch 入口和 RunWorker 传参。

建议再补以下测试：

### 1. 运行链路传递测试

目标：证明 `run_arg_overrides` 从 `WorkflowEngine.run` 进入 `_execute_steps`。

建议断言：

```python
calls["run_arg_overrides"] == {"step-a": ["--year", "2025"]}
```

### 2. 步骤执行合并测试

目标：证明 `execute_step_attempt` 传给 executor 的参数是：

```text
fixed_args + temporary_args
```

建议构造：

```python
step.get_args() -> ["--mode", "prod"]
run_arg_overrides -> {"step-a": ["--year", "2025"]}
```

断言 executor 收到：

```python
["--mode", "prod", "--year", "2025"]
```

### 3. 子工作流隔离测试

目标：证明子工作流不会污染父工作流参数，也不会继承父级临时参数。

建议至少覆盖：

- 父步骤有临时参数。
- 子工作流运行时 `run_arg_overrides` 为空。
- 父级其他步骤仍能拿到自己的临时参数。

## 其他清理建议

根目录仍存在两个未跟踪文件：

```text
STATUS.md
project_memory.md
```

这两个文件像是实现过程 scratch 文件，不建议提交。

如需保留，应移动到明确的文档目录并说明用途；否则建议删除。

## 复审验证记录

已通过：

```bash
python -m pytest tests/test_script_cli_parameters.py tests/test_script_cli_merge.py tests/test_ui_run_worker.py tests/test_run_dispatch_cli_args.py -q
```

结果：

```text
30 passed
```

已通过：

```bash
python -m compileall src tests -q
```

失败：

```bash
python -m pytest tests/test_executor_policies_engine.py -q
```

结果：

```text
3 failed, 11 passed
```

## 合并前检查清单

合并前至少需要满足：

- `tests/test_executor_policies_engine.py` 全部通过。
- 新增或更新测试证明 `run_arg_overrides` 能进入 `_execute_steps`。
- 新增或更新测试证明 executor 收到的是固定参数 + 临时参数。
- `STATUS.md`、`project_memory.md` 不进入提交。
- `python -m compileall src tests -q` 通过。
- 本功能相关 focused tests 通过。

