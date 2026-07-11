# -*- coding: utf-8 -*-
"""静态识别 Python 脚本中的 argparse 参数（只读 AST，不执行脚本）。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def inspect_script_arguments(script_path: str | Path) -> ScriptArgumentSpec:
    """读取脚本文本并静态识别 argparse 参数。"""
    path = Path(script_path)
    path_text = str(path)
    if not path.exists() or not path.is_file():
        return ScriptArgumentSpec(
            script_path=path_text,
            detected=False,
            arguments=(),
            warnings=("脚本文件不存在或不可读",),
        )

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ScriptArgumentSpec(
            script_path=path_text,
            detected=False,
            arguments=(),
            warnings=(f"读取脚本失败: {exc}",),
        )
    except UnicodeDecodeError:
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            return ScriptArgumentSpec(
                script_path=path_text,
                detected=False,
                arguments=(),
                warnings=(f"读取脚本编码失败: {exc}",),
            )

    return inspect_script_source(source, script_path=path_text)


def inspect_script_source(source: str, script_path: str = "<memory>") -> ScriptArgumentSpec:
    """从源码文本静态识别 argparse 参数。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ScriptArgumentSpec(
            script_path=script_path,
            detected=False,
            arguments=(),
            warnings=(f"脚本语法错误，无法识别参数: {exc.msg}",),
        )

    parser_aliases = _collect_parser_aliases(tree)
    if not parser_aliases:
        return ScriptArgumentSpec(
            script_path=script_path,
            detected=False,
            arguments=(),
            warnings=("未检测到 argparse.ArgumentParser",),
        )

    arguments: list[ScriptArgument] = []
    warnings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_add_argument_call(node, parser_aliases):
            continue
        try:
            arg = _parse_add_argument_call(node)
        except _UnsupportedArgument as exc:
            warnings.append(str(exc))
            continue
        if arg is not None:
            arguments.append(arg)

    return ScriptArgumentSpec(
        script_path=script_path,
        detected=bool(arguments),
        arguments=tuple(arguments),
        warnings=tuple(warnings),
    )


class _UnsupportedArgument(Exception):
    pass


def _collect_parser_aliases(tree: ast.AST) -> set[str]:
    """收集可能的 ArgumentParser 类名与实例变量名。"""
    class_names = {"ArgumentParser"}
    instance_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "argparse":
                    # import argparse -> argparse.ArgumentParser
                    class_names.add("argparse.ArgumentParser")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "argparse":
                for alias in node.names:
                    if alias.name == "ArgumentParser":
                        class_names.add(alias.asname or "ArgumentParser")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if not _call_is_parser_ctor(node.value, class_names):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                instance_names.add(target.id)
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                # self.parser = ArgumentParser()
                instance_names.add(f"{target.value.id}.{target.attr}")

    # 也支持直接 ArgumentParser().add_argument 链式调用的临时对象（少见）
    return instance_names | class_names


def _call_is_parser_ctor(call: ast.Call, class_names: set[str]) -> bool:
    name = _call_func_name(call.func)
    return name in class_names or name.endswith(".ArgumentParser")


def _is_add_argument_call(call: ast.Call, parser_aliases: set[str]) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
        return False
    owner = _expr_name(func.value)
    if owner is None:
        return False
    # parser.add_argument / self.parser.add_argument
    if owner in parser_aliases:
        return True
    # 宽松：任意 *.add_argument 且同文件存在 ArgumentParser 构造
    if parser_aliases and ("ArgumentParser" in " ".join(parser_aliases) or any(
        "parser" in a.lower() for a in parser_aliases
    )):
        # 若 owner 看起来像 parser 变量也接受
        short = owner.split(".")[-1]
        if "parser" in short.lower() or owner in parser_aliases:
            return True
    return owner in parser_aliases


def _parse_add_argument_call(call: ast.Call) -> ScriptArgument | None:
    option_strings: list[str] = []
    for arg in call.args:
        val = _literal(arg)
        if not isinstance(val, str):
            raise _UnsupportedArgument("add_argument 位置参数非字面量，已跳过")
        option_strings.append(val)

    kwargs: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            raise _UnsupportedArgument("add_argument 使用了 **kwargs，已跳过")
        kwargs[kw.arg] = _literal_or_name(kw.value)

    positional = not any(s.startswith("-") for s in option_strings)
    dest = kwargs.get("dest")
    if not isinstance(dest, str) or not dest:
        dest = _infer_dest(option_strings, positional)

    help_text = kwargs.get("help")
    if help_text is not None and not isinstance(help_text, str):
        help_text = str(help_text)

    required = bool(kwargs.get("required", False))
    default = kwargs.get("default", None)

    choices_raw = kwargs.get("choices")
    choices: tuple[str, ...] | None = None
    if choices_raw is not None:
        if isinstance(choices_raw, (list, tuple)):
            choices = tuple(str(x) for x in choices_raw)
        else:
            raise _UnsupportedArgument("choices 非常量序列，已跳过该参数")

    type_name = None
    if "type" in kwargs:
        type_name = str(kwargs["type"]) if kwargs["type"] is not None else None

    action = kwargs.get("action")
    if action is not None:
        action = str(action)

    nargs = kwargs.get("nargs", None)
    if nargs is not None and not isinstance(nargs, (str, int)):
        nargs = str(nargs)

    metavar = kwargs.get("metavar")
    if metavar is not None and not isinstance(metavar, str):
        if isinstance(metavar, (list, tuple)):
            metavar = " ".join(str(x) for x in metavar)
        else:
            metavar = str(metavar)

    return ScriptArgument(
        option_strings=tuple(option_strings),
        dest=str(dest),
        help=help_text,
        required=required,
        default=default,
        choices=choices,
        type_name=type_name,
        action=action,
        nargs=nargs,
        metavar=metavar,
        positional=positional,
    )


def _infer_dest(option_strings: list[str], positional: bool) -> str:
    if not option_strings:
        return "arg"
    if positional:
        return option_strings[0].replace("-", "_")
    # 优先长选项
    for s in option_strings:
        if s.startswith("--"):
            return s[2:].replace("-", "_")
    s = option_strings[0].lstrip("-")
    return s.replace("-", "_") or "arg"


def _call_func_name(func: ast.AST) -> str:
    return _expr_name(func) or ""


def _expr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


def _literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return type(node)([_literal(elt) for elt in node.elts]) if False else [
            _literal(elt) for elt in node.elts
        ]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _literal(node.operand)
        if isinstance(val, (int, float)):
            return val if isinstance(node.op, ast.UAdd) else -val
    raise _UnsupportedArgument("非常量字面量")


def _literal_or_name(node: ast.AST) -> Any:
    try:
        return _literal(node)
    except _UnsupportedArgument:
        pass
    if isinstance(node, ast.Name):
        # type=int / action=store_true 等
        return node.id
    if isinstance(node, ast.Attribute):
        return _expr_name(node)
    if isinstance(node, ast.Call):
        # type=str 以外的 callable，记录名字
        name = _call_func_name(node.func)
        return name or "<call>"
    raise _UnsupportedArgument("无法静态求值的关键字参数")
