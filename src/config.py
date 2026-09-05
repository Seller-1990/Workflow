# -*- coding: utf-8 -*-
"""应用配置管理"""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
APP_DATA_DIR_ENV_VAR = "WORKFLOW_APP_DATA_DIR"


# 判断是否为打包后的 exe
if getattr(sys, 'frozen', False):
    # 打包后：使用临时目录作为根目录（用于查找资源）
    ROOT_DIR = Path(sys._MEIPASS)
else:
    # 开发时：使用项目根目录
    ROOT_DIR = Path(__file__).resolve().parents[1]


def _resolve_app_data_dir() -> Path:
    override_dir = os.environ.get(APP_DATA_DIR_ENV_VAR)
    if override_dir:
        return Path(override_dir).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', Path.home())) / "工作流管理"
    return ROOT_DIR


APP_DATA_DIR = _resolve_app_data_dir()

# 图标路径：优先使用 .ico，兼容 slim 包去掉 png 的场景
ICON_PATH = ROOT_DIR / "图标.ico"
if not ICON_PATH.exists():
    ICON_PATH = ROOT_DIR / "图标.png"

# 数据目录
DATA_DIR = APP_DATA_DIR / "data"


def _ensure_directory(path: Path, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"无法创建{label}: {path}") from e


_ensure_directory(DATA_DIR, "数据目录")

# 日志目录
LOG_DIR = APP_DATA_DIR / "logs"
_ensure_directory(LOG_DIR, "日志目录")

# 数据库路径
DATABASE_PATH = DATA_DIR / "workflows.db"

# 应用信息
APP_NAME = "工作流管理"
APP_VERSION = "6.0.2"

# 步骤类型
class StepType:
    PYTHON = "python"
    SUB_WORKFLOW = "sub_workflow"
    BAT = "bat"

    @classmethod
    def choices(cls):
        choices = [(cls.PYTHON, "Python")]
        if sys.platform.startswith("win"):
            choices.append((cls.BAT, "批处理脚本"))
        choices.append((cls.SUB_WORKFLOW, "子工作流"))
        return choices
    
    @classmethod
    def display_name(cls, value: str) -> str:
        mapping = dict(cls.choices())
        return mapping.get(value, value)
