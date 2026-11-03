# -*- coding: utf-8 -*-
"""Safe path-metadata fixtures shared by legacy, snapshot and current-policy tests."""

import json
from types import SimpleNamespace

from risk_path_review import build_run_plan


def _wf(**overrides):
    fields = {
        "id": 1,
        "risky_paths_review_required": False,
        "risky_paths_revision": 0,
        "risky_paths_confirmed_digest": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _risky_steps():
    return [SimpleNamespace(uid="s1", step_type="python", script_path="C:/x.py", cwd=None)]


def _import_risky_workflow(db, tmp_path, *, uid="wf_risky", name="风险路径工作流", script="../outside.py"):
    payload_path = tmp_path / f"{uid}.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": uid,
                        "name": name,
                        "description": "说明",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "Step",
                                "step_type": "python",
                                "script": script,
                                "cwd": "safe",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert db.import_from_json(payload_path) == 1
    return db.get_workflow_by_uid(uid)


def _import_two_risky_steps(db, tmp_path):
    payload = tmp_path / "scoped-confirmation.json"
    payload.write_text(json.dumps({
        "version": 1,
        "workflows": [{
            "id": "wf_scoped_confirmation",
            "name": "范围确认",
            "steps": [
                {"id": "a", "name": "A", "step_type": "python", "script": "C:/a.py"},
                {"id": "b", "name": "B", "step_type": "python", "script": "D:/b.py"},
            ],
        }],
    }), encoding="utf-8")
    assert db.import_from_json(payload) == 1
    workflow = db.get_workflow_by_uid("wf_scoped_confirmation")
    return workflow, db.get_steps_by_workflow(workflow.id)


def _current_plan(db, workflow_id):
    workflow = db.get_workflow_by_id(workflow_id)
    steps = db.get_steps_by_workflow(workflow_id)
    return build_run_plan(workflow, steps)
