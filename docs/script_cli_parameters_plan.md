# 脚本附加命令行参数方案

## 目标

为 Python 脚本步骤增加“本次运行临时附加命令行参数”能力：

- 脚本默认不传参数时保持原行为，例如生成所有年度。
- 用户运行前临时输入参数，例如 `--year 2025`，本次只生成 2025 年。
- 临时参数只影响本次运行，不写回工作流配置。
- 如果脚本使用 `argparse`，应用静态识别可用参数并生成更清晰的填写界面。
- 如果无法识别 `argparse`，用户仍可手动填写命令行参数。

## 当前基础

项目已有底层参数传递能力：

- `models.Step.args` 保存步骤固定参数，格式为 JSON 数组。
- `models.Workflow.single_script_args` 保存单脚本模式固定参数，格式为 JSON 数组。
- `engine_core.step_execution.execute_step_attempt` 调用执行器时使用 `step.get_args()`。
- `executors.python_executor.PythonExecutor.execute()` 最终执行：

```text
python -u <script_path> + args
```

因此本需求不需要改 Python 执行器的核心启动方式，主要改动在：

- 运行前参数输入 UI
- `argparse` 静态识别
- 临时参数从 UI 到引擎执行链路的传递
- 日志和测试

## 核心定义

### 固定参数

固定参数是步骤配置中已保存的参数，来自：

- `Step.args`
- `Workflow.single_script_args`

固定参数持久化在数据库中，属于工作流配置的一部分。

### 临时附加参数

临时附加参数是用户每次点击运行时填写的参数：

- 只对本次运行生效。
- 不写入 `Step.args`。
- 不写入 `Workflow.single_script_args`。
- 不改变导入导出格式。

### 参数合并规则

实际执行参数应为：

```text
固定参数 + 临时附加参数
```

示例：

```text
固定参数: ["--mode", "prod"]
临时参数: --year 2025
实际执行: ["--mode", "prod", "--year", "2025"]
```

临时参数放在固定参数之后，方便用户在脚本支持重复参数或后写覆盖时进行本次覆盖。

## 推荐用户体验

### 运行入口

以下 GUI 手动运行入口建议支持运行前临时参数：

- 运行全部工作流
- 从选中步骤开始
- 只运行选中步骤
- 只运行某阶段
- 从某阶段开始

`retry_failed` 第一版建议不主动弹出临时参数窗口，避免重试语义变复杂。后续如有需要可增加“带参数重试”入口。

### 运行前弹窗

点击运行后，在真正启动 `RunWorker` 前弹出“本次运行参数”对话框。

对话框展示本次将运行的 Python 步骤：

- 步骤名
- 脚本路径
- 固定参数预览
- 参数识别状态
- 临时参数输入区域
- 最终参数预览

非 Python 步骤第一版不显示临时参数输入。

### 识别成功时

如果脚本可通过 `argparse` 静态识别，展示参数表单：

- 普通值：文本输入框
- `choices`：下拉框
- `store_true` / `store_false`：复选框
- positional 参数：文本输入框
- `required=True`：视觉提示必填
- `default`：展示默认值，不强制写入临时参数
- `help`：作为说明或 tooltip

用户填写后，应用生成参数数组，例如：

```text
--year 2025 --mode incremental
```

生成：

```json
["--year", "2025", "--mode", "incremental"]
```

### 识别失败时

如果脚本没有使用 `argparse`，或者静态识别不支持当前写法，展示手动输入框：

```text
--year 2025
```

应用使用命令行分词规则转成参数数组。

高级用户仍可直接输入 JSON 数组：

```json
["--year", "2025"]
```

第一版可以保留这类兼容能力，但 UI 主路径应优先支持普通命令行文本。

## argparse 静态识别方案

### 原则

只做静态读取，不执行脚本。

禁止为了识别参数自动运行：

```text
python script.py --help
```

原因：部分脚本可能在 import 阶段连接数据库、读写文件或直接触发任务，自动执行存在副作用风险。

### 识别范围

第一版建议支持以下常见写法：

```python
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, help="只生成指定年份")
parser.add_argument("--mode", choices=["full", "incremental"], default="full")
```

以及：

```python
from argparse import ArgumentParser

parser = ArgumentParser()
parser.add_argument("--year", type=int)
```

推荐识别字段：

- `option_strings`
- `dest`
- `help`
- `required`
- `default`
- `choices`
- `type`
- `action`
- `nargs`
- `metavar`
- 是否 positional

### 不承诺识别的情况

第一版不需要支持：

- `click`
- `typer`
- 自定义 `sys.argv` 解析
- 动态生成参数名
- 从外部模块导入 parser 后再拼装
- 复杂循环或条件里生成的 `add_argument`
- 运行时才知道的 `choices`

这些情况统一回退到手动输入。

### 建议模块

建议新增纯逻辑模块：

```text
src/script_arg_introspection.py
```

职责：

- 读取 Python 文件文本
- `ast.parse`
- 查找 `ArgumentParser`
- 查找 `add_argument`
- 输出参数元数据

建议数据结构：

```python
@dataclass(frozen=True)
class ScriptArgument:
    option_strings: tuple[str, ...]
    dest: str
    help: str | None
    required: bool
    default: object | None
    choices: tuple[str, ...] | None
    type_name: str | None
    action: str | None
    nargs: str | int | None
    metavar: str | None
    positional: bool

@dataclass(frozen=True)
class ScriptArgumentSpec:
    script_path: str
    detected: bool
    arguments: tuple[ScriptArgument, ...]
    warnings: tuple[str, ...]
```

该模块必须是纯函数为主，便于单元测试，不依赖 Qt。

## 命令行参数解析

### 普通输入

用户输入：

```text
--year 2025 --name "North Region"
```

应解析为：

```json
["--year", "2025", "--name", "North Region"]
```

建议新增纯函数：

```python
parse_cli_args_text(text: str) -> list[str]
```

规则：

- 空字符串返回 `[]`
- JSON 数组字符串按 JSON 解析
- 普通命令行文本按 shell-like quoting 解析
- 引号不闭合时返回明确错误，不启动运行
- 禁止参数包含 `\x00`

### Windows 注意

执行器最终使用 `subprocess` 的 list 参数形式，不需要拼接成一整条命令字符串。

UI 输入只是为了帮助用户表达参数，解析结果必须始终是 `list[str]`。

## 运行链路改造

### 不推荐方案

不建议把临时参数临时写入 `Step.args` 再运行，原因：

- 容易污染工作流配置。
- 并发或取消时容易留下错误状态。
- 运行历史难以判断参数是固定配置还是临时输入。

### 推荐方案

在运行链路中传递一个只读覆盖层：

```python
run_arg_overrides: dict[str, list[str]]
```

key 使用 `step.uid`，不是 `step.id`。

原因：

- `uid` 更稳定。
- 单脚本模式生成的 `single_script` 步骤也可统一处理。
- 日志中更容易追踪。

建议传递路径：

```text
MainWindow
  -> RunWorker
  -> ui.run_actions.run_engine_mode
  -> WorkflowEngine.run_all / run_from / run_only / ...
  -> WorkflowEngine.run
  -> engine_core.run_orchestration.run_workflow
  -> engine_core.step_execution.execute_step_attempt
```

最终在执行步骤时合并：

```python
fixed_args = step.get_args()
temporary_args = run_arg_overrides.get(step.uid, [])
effective_args = fixed_args + temporary_args
```

然后传给执行器：

```python
executor.execute(..., args=effective_args, ...)
```

该合并过程不得修改 `step.args`。

## 日志与追溯

建议在每个 Python 步骤开始执行前记录最终参数摘要：

```text
本次执行参数: --mode prod --year 2025
```

但需要做基础脱敏：

- 参数名包含 `token`
- 参数名包含 `secret`
- 参数名包含 `password`
- 值中包含 `access_token=`

应显示为：

```text
--token ****
```

或：

```text
--webhook-url ****
```

不要为了日志追溯把临时参数写入数据库字段。第一版记录到运行日志即可。

## 脚本编写规范

建议新增脚本规范文档，本方案文件可以作为基础，也可以拆出单独文档：

```text
docs/script_cli_parameter_guide.md
```

推荐脚本格式：

```python
import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成年度报表")
    parser.add_argument(
        "--year",
        type=int,
        help="只生成指定年份，例如 2025；不传则生成全部年份",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="生成模式",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.year:
        print(f"生成 {args.year} 年数据")
    else:
        print("生成全部年份数据")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 推荐规则

- 优先使用命名参数，例如 `--year 2025`，不要只用位置参数 `2025`。
- `add_argument` 尽量使用字面量参数，便于静态识别。
- 每个对用户可见的参数都写 `help`。
- 有固定选项时使用 `choices`。
- 有默认值时写 `default`。
- 只筛选某个年度这类参数不要设为 `required=True`，否则无法表达“不传则全部运行”。
- 不要在 import 阶段执行实际业务逻辑。
- 业务逻辑放进 `main()`，用 `if __name__ == "__main__"` 启动。

### 不推荐写法

```python
import sys

year = sys.argv[1] if len(sys.argv) > 1 else None
run(year)
```

原因：

- 应用无法可靠静态识别参数。
- 用户看不到 help、choices、默认值。
- import 阶段容易产生副作用。

## 验收标准

### 手动输入

- 用户点击运行时可以输入 `--year 2025`。
- 实际脚本收到 `sys.argv` 中的 `--year` 和 `2025`。
- 本次参数不写回步骤配置。
- 参数引号不闭合时不启动运行，并给出错误提示。

### argparse 识别

- 使用 `argparse.ArgumentParser().add_argument("--year", ...)` 的脚本能展示 `--year`。
- `choices` 参数展示为下拉选择。
- `store_true` 参数展示为复选框。
- 无法识别时回退到手动输入，不阻塞运行。
- 识别过程不执行脚本。

### 合并规则

- 固定参数和临时参数按顺序合并。
- 固定参数为空时，仅使用临时参数。
- 临时参数为空时，行为与当前版本一致。
- 合并后不修改 `Step.args`。

### 运行模式

- 只运行此步骤时，仅展示该步骤参数。
- 从此步骤开始时，展示将运行的 Python 步骤参数。
- 运行全部工作流时，展示全部将运行的 Python 步骤参数。
- 阶段运行时，仅展示该阶段范围内的 Python 步骤参数。

### 安全与稳定

- 静态识别不执行脚本。
- 文件不存在或读取失败时回退手动输入。
- 参数日志需脱敏明显的 token、secret、password。
- 停止运行、取消运行、并行步骤调度行为不应改变。

## 测试建议

### 纯单元测试

新增测试覆盖：

- `parse_cli_args_text("--year 2025")`
- `parse_cli_args_text('--name "North Region"')`
- `parse_cli_args_text('["--year", "2025"]')`
- 引号不闭合错误
- 参数含 `\x00` 错误
- 静态识别 `import argparse`
- 静态识别 `from argparse import ArgumentParser`
- 静态识别 `choices`
- 静态识别 `store_true`
- 动态或未知写法回退 warning

### 引擎测试

新增测试覆盖：

- `run_arg_overrides` 与 `Step.args` 合并顺序正确。
- 临时参数不修改 `Step.args`。
- 没有临时参数时执行参数与当前行为一致。
- 非 Python 步骤不受影响。

### UI 测试

视项目测试能力选择：

- 参数对话框能列出本次运行范围内的 Python 步骤。
- argparse 识别结果能生成最终参数预览。
- 手动输入错误时禁止启动运行。
- 用户取消对话框时不启动 `RunWorker`。

## 实施顺序建议

1. 新增纯函数：命令行文本解析。
2. 新增纯模块：`argparse` 静态识别。
3. 新增运行时参数数据结构和合并逻辑。
4. 改造 `RunWorker` 和 `run_engine_mode` 传递临时参数。
5. 改造 `WorkflowEngine` 和 `run_workflow` 签名，向下传递覆盖层。
6. 改造 `execute_step_attempt` 合并固定参数和临时参数。
7. 新增运行前参数对话框。
8. 接入各 GUI 手动运行入口。
9. 增加日志脱敏和最终参数预览。
10. 补充测试。
11. 根据发布规则，打包前更新版本号。

## Review 重点

实现完成后 review 时重点检查：

- 是否有任何地方为了识别参数执行了用户脚本。
- 临时参数是否被写回数据库。
- 参数合并顺序是否为固定参数在前、临时参数在后。
- 是否使用 `step.uid` 作为运行时覆盖 key。
- 是否保持无临时参数时的旧行为。
- 是否影响取消、停止、并行调度和子工作流。
- 日志中是否泄露明显 secret。
- 新增逻辑是否主要落在纯函数中，避免 UI 和解析逻辑耦合。
- 是否有足够的单元测试覆盖解析、识别、合并和回退路径。

