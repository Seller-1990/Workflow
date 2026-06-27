# 外部执行安全检查清单

适用于 Workflow 中 Python、PowerBI、Excel、子工作流、文件导入导出等会触达本机文件系统或外部进程的功能。

## 命令与进程

- 优先使用参数数组并保持 `shell=False`。
- 如必须 `shell=True`，记录原因并确保输入不可由用户直接拼接。
- 为外部进程设置超时、工作目录和环境变量边界。
- 捕获 stdout/stderr 时避免吞掉退出码。

## 路径与文件

- 对用户输入路径执行规范化和存在性检查。
- 临时文件应位于受控目录，执行后清理。
- 导入导出不应覆盖未明确确认的文件。

## 错误传播与审计

- 不要静默吞掉 `Exception`；至少记录上下文、文件、步骤和原始异常。
- 执行结果应可被测试断言：成功、失败、跳过、超时需有明确状态。
- 新增外部执行点时运行 `python tools/audit_risky_calls.py`。

## Approved risky execution guard

`python tools/audit_risky_calls.py` is the executable checklist for dynamic execution and subprocess usage.

Review questions before adding an allowlist entry:

1. Can the feature avoid `eval` / `exec` / `compile` / `subprocess` entirely?
2. Is `shell=True` avoided? The guard rejects it unconditionally.
3. Are command arguments passed as an explicit list and validated by the caller?
4. Is process lifecycle cleanup covered by tests when `Popen` is used?
5. Does the allowlist reason explain why this call site is necessary?

Current approved categories are executor process launching, CLI/test subprocess contracts, and repository tooling wrappers.

