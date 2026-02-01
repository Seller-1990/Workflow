# -*- coding: utf-8 -*-
"""应用配置管理"""

import os
import sys
from pathlib import Path

# 判断是否为打包后的 exe
if getattr(sys, 'frozen', False):
    # 打包后：使用用户目录存储数据
    APP_DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / "工作流管理"
else:
    # 开发时：使用项目目录
    APP_DATA_DIR = Path(__file__).resolve().parents[1]

# 数据目录
DATA_DIR = APP_DATA_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 日志目录
LOG_DIR = APP_DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 数据库路径
DATABASE_PATH = DATA_DIR / "workflows.db"

# 应用信息
APP_NAME = "工作流管理"
APP_VERSION = "1.0.0"

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
