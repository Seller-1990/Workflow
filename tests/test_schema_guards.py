# -*- coding: utf-8 -*-
"""模式层守卫测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from models import Step


def test_step_model_declares_unique_workflow_uid_index():
    indexes = {index.name: index for index in Step.__table__.indexes}

    assert "uq_steps_workflow_uid" in indexes
    unique_index = indexes["uq_steps_workflow_uid"]

    assert unique_index.unique is True
    assert [column.name for column in unique_index.columns] == ["workflow_id", "uid"]
