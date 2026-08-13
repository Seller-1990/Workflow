# -*- coding: utf-8 -*-
"""智能错误诊断模块

根据错误类型和上下文，自动推断错误原因并提供修复建议。
"""


class ErrorDiagnostician:
    """错误诊断器"""

    # 错误关键词 -> (错误类型, 修复建议)
    _PATTERNS = [
        # 文件/路径问题
        (
            ["FileNotFoundError", "No such file", "文件不存在", "找不到文件"],
            "文件路径错误",
            "请检查步骤的脚本路径配置，确认文件存在且路径正确"
        ),
        (
            ["PermissionError", "权限不足", "Permission denied", "Access is denied"],
            "权限不足",
            "请检查文件/目录的访问权限，确认当前用户有读写权限"
        ),
        (
            ["ModuleNotFoundError", "No module named", "ImportError"],
            "Python 依赖缺失",
            "请确认脚本所需的 Python 包已安装，可在脚本中添加 pip install 命令或在命令行执行 pip install <包名>"
        ),
        # 超时问题
        (
            ["TimeoutError", "超时", "timed out"],
            "执行超时",
            "脚本执行时间超过设定超时限制，可在步骤设置中增大超时时间，或优化脚本性能"
        ),
        # 编码问题
        (
            ["UnicodeDecodeError", "编码", "encoding", "codec"],
            "文件编码问题",
            "文件编码与预期不符，请确认文件使用 UTF-8 编码保存，或在脚本中指定正确的编码"
        ),
        # 内存问题
        (
            ["MemoryError", "Out of memory", "内存不足"],
            "内存不足",
            "系统内存不足，请关闭其他程序释放内存，或优化脚本减少内存使用"
        ),
        # 数据库问题
        (
            ["OperationalError", "database is locked", "sqlite", "SQLAlchemy"],
            "数据库错误",
            "数据库操作失败，可能是并发访问导致锁定，请稍后重试"
        ),
        # 网络问题
        (
            ["ConnectionError", "NetworkError", "ConnectionRefused", "网络"],
            "网络连接失败",
            "请检查网络连接是否正常，以及目标服务是否可访问"
        ),
        # 依赖问题
        (
            ["DependencyError", "循环依赖", "依赖不存在"],
            "步骤依赖错误",
            "请检查步骤间的依赖关系配置，确保没有循环依赖且引用的步骤存在"
        ),
        # 用户取消
        (
            ["用户取消"],
            "用户取消",
            "用户主动取消了运行"
        ),
    ]

    @classmethod
    def diagnose(cls, error_message: str, step_type: str = None, context: dict = None) -> dict:
        """分析错误并返回诊断结果

        Args:
            error_message: 错误信息字符串
            step_type: 步骤类型（python/excel_powerquery/powerbi_refresh/sub_workflow）
            context: 额外上下文（如 timeout, script_path 等）

        Returns:
            {
                "error_type": str,      # 错误类型分类
                "suggested_fix": str,   # 修复建议
            }
        """
        if not error_message:
            return {
                "error_type": "未知错误",
                "suggested_fix": "未获取到错误详情，请查看步骤日志获取更多信息"
            }

        # 用户取消特殊处理
        if "用户取消" in error_message:
            return {
                "error_type": "用户取消",
                "suggested_fix": "用户主动取消了运行"
            }

        # 遍历模式匹配
        for keywords, error_type, suggested_fix in cls._PATTERNS:
            for keyword in keywords:
                if keyword in error_message:
                    # 根据上下文补充建议
                    fix = suggested_fix
                    if context:
                        fix = cls._enrich_fix(fix, error_type, context)
                    return {
                        "error_type": error_type,
                        "suggested_fix": fix
                    }

        # 根据步骤类型给出通用建议
        type_hints = {
            "python": "请检查 Python 脚本语法和逻辑是否正确",
            "sub_workflow": "请检查子工作流配置是否正确",
        }
        hint = type_hints.get(step_type, "请查看步骤日志获取详细错误信息")

        return {
            "error_type": "运行错误",
            "suggested_fix": hint
        }

    @classmethod
    def _enrich_fix(cls, fix: str, error_type: str, context: dict) -> str:
        """根据上下文丰富修复建议"""
        if error_type == "执行超时" and context.get("timeout"):
            fix += f"（当前超时设置: {context['timeout']}秒）"
        if error_type == "文件路径错误" and context.get("script_path"):
            fix += f"（路径: {context['script_path']}）"
        return fix
