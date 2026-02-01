# -*- coding: utf-8 -*-
"""子工作流执行器"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from executors.base import BaseExecutor, ExecutorResult
from database import (
    get_workflow_by_uid, get_workflow_by_id,
    has_cross_workflow_cycle
)


class SubWorkflowExecutor(BaseExecutor):
    """子工作流执行器"""

    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        workflow_id: int = None,
        **kwargs
    ) -> ExecutorResult:
        if not script_path:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="未指定子工作流"
            )

        target = get_workflow_by_uid(script_path)
        if not target:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"未找到子工作流: {script_path}"
            )
        
        if workflow_id is not None:
            parent = get_workflow_by_id(workflow_id)
            if parent and parent.id == target.id:
                return ExecutorResult(
                    success=False,
                    exit_code=1,
                    error_message="禁止引用自身工作流"
                )
            if parent and has_cross_workflow_cycle(parent.id, target.uid):
                return ExecutorResult(
                    success=False,
                    exit_code=1,
                    error_message="检测到跨工作流循环依赖"
                )

        from engine import WorkflowEngine

        start_time = datetime.now()
        engine = WorkflowEngine()
        ok = engine.run_all(target.id, reason="sub_workflow")
        end_time = datetime.now()

        return ExecutorResult(
            success=ok,
            exit_code=0 if ok else 1,
            start_time=start_time,
            end_time=end_time,
            stdout_path=None,
            stderr_path=None,
            error_message=None if ok else "子工作流执行失败"
        )

    def validate(self, script_path: str) -> bool:
        if not script_path:
            return False
        return get_workflow_by_uid(script_path) is not None
