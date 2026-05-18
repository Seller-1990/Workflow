# -*- coding: utf-8 -*-
"""应用配置管理"""

import os
import sys
import json
from pathlib import Path

# 判断是否为打包后的 exe
if getattr(sys, 'frozen', False):
    # 打包后：使用临时目录作为根目录（用于查找资源），用户目录存储数据
    ROOT_DIR = Path(sys._MEIPASS)
    APP_DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / "工作流管理"
else:
    # 开发时：使用项目根目录
    ROOT_DIR = Path(__file__).resolve().parents[1]
    APP_DATA_DIR = ROOT_DIR

# 图标路径
ICON_PATH = ROOT_DIR / "图标.png"

# 数据目录
DATA_DIR = APP_DATA_DIR / "data"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# 日志目录
LOG_DIR = APP_DATA_DIR / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# 数据库路径
DATABASE_PATH = DATA_DIR / "workflows.db"

# 应用信息
APP_NAME = "工作流管理"
APP_VERSION = "3.0.0"

# 默认配置
DEFAULT_CONFIG = {
    "cooldown_seconds": 8,
    "settle_seconds": 15,
    "chart_theme": "default",
    "parallel": {
        "enabled": False,
        "max_workers": 2
    },
    "notify": {
        "enabled": False,
        "ding_talk_webhook": "",
        "ding_talk_keyword": "",
        "message_template": "{工作流名称} | {状态} | 编号={运行编号}"
    }
}

# 配置文件路径
CONFIG_PATH = APP_DATA_DIR / "config.json"


def load_user_config() -> dict:
    """加载用户配置"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_user_config(config: dict):
    """保存用户配置"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# 合并默认配置和用户配置
USER_CONFIG = {**DEFAULT_CONFIG, **load_user_config()}

# 步骤类型
class StepType:
    PYTHON = "python"
    EXCEL_POWERQUERY = "excel_powerquery"
    POWERBI_REFRESH = "powerbi_refresh"
    SUB_WORKFLOW = "sub_workflow"
    
    @classmethod
    def choices(cls):
        return [
            (cls.PYTHON, "Python 脚本"),
            (cls.EXCEL_POWERQUERY, "Excel PowerQuery 刷新"),
            (cls.POWERBI_REFRESH, "Power BI Desktop 刷新"),
            (cls.SUB_WORKFLOW, "子工作流"),
        ]
    
    @classmethod
    def display_name(cls, value: str) -> str:
        mapping = dict(cls.choices())
        return mapping.get(value, value)
