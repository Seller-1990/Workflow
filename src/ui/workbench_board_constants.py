# -*- coding: utf-8 -*-
"""阶段看板常量。"""

MIME_STEP_ID = "application/x-workflow-step-id"
STAGE_LANE_MIN_WIDTH = 260
STAGE_LANE_MIN_HEIGHT = 112
STAGE_LANE_GAP = 14
STAGE_LANE_BORDER_HEIGHT = 2
QT_MAX_WIDGET_SIZE = 16777215

TYPE_LABELS = {
    "python": "Python",
    "excel_powerquery": "Power Query",
    "powerbi_refresh": "Power BI",
    "sub_workflow": "子工作流",
}

STATUS_LABELS = {
    "running": "运行中",
    "success": "成功",
    "failure": "失败",
    "cancelled": "已取消",
    "skipped": "跳过",
}

COMPLETED_STATUSES = {"success", "skipped"}

TYPE_CLASSES = {
    "python": "python",
    "excel_powerquery": "excel",
    "powerbi_refresh": "powerbi",
    "sub_workflow": "subworkflow",
}
