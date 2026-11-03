"""Reached concurrent state changes must not turn stop requests into early outcomes."""
from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from _schema_guard_utils import _use_temp_database
from database_coordination_models import RunOwner, RunStopRequest
from database_process_identity import new_owner_identity
import database_run_ownership as coordination
from engine import WorkflowEngine
from models import RunHistory


@pytest.fixture
def target(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("stop race")
    step = db.create_step(workflow.id, "A")
    identity = new_owner_identity()
    with coordination.publish_owner(identity):
        history = db.create_run_history(workflow.id)
    log = db.create_step_log(history.id, step.id)
    yield db, history, log, identity
    db.cleanup_session()
    db._engine.dispose()


def test_terminal_update_wins_between_liveness_read_and_request_insert(monkeypatch, target):
    db, history, _, _identity = target
    reached = []

    def normal_completion(_owner):
        reached.append(True)
        db.update_run_history(history.id, status="success", end_time=datetime.now())
        return "alive"

    monkeypatch.setattr(coordination, "owner_liveness", normal_completion)
    state = coordination.request_run_stop(history.id)
    assert reached == [True]
    assert (state.status, state.existing_status) == ("already_terminal", "success")
    with db.get_fresh_session() as session:
        assert session.query(RunStopRequest).count() == 0


def test_orphan_cleanup_failure_rolls_back_before_terminal_write(monkeypatch, target):
    db, history, _, identity = target
    monkeypatch.setattr(coordination, "owner_liveness", lambda _owner: "dead")
    reached = []

    def unavailable_cleanup(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE step_logs"):
            reached.append(True)
            raise SQLAlchemyError("unfinished cleanup failed")

    event.listen(db._engine, "before_cursor_execute", unavailable_cleanup)
    try:
        with pytest.raises(SQLAlchemyError, match="cleanup failed"):
            coordination.recover_orphaned_run(history.id, expected_run_id=history.run_id, expected_owner_token=identity.owner_token)
    finally:
        event.remove(db._engine, "before_cursor_execute", unavailable_cleanup)
    assert reached == [True]
    assert db.get_step_logs_by_run(history.id)[0].status == "pending"
    with db.get_fresh_session() as session:
        assert session.get(RunHistory, history.id).status == "pending"
        assert session.get(RunOwner, history.id).released_at is None


def test_terminal_legacy_history_still_cleans_its_unfinished_steps(target):
    db, history, log, _identity = target
    with db.get_fresh_session() as session:
        session.query(RunOwner).filter(RunOwner.run_history_id == history.id).delete()
        session.commit()
    db.update_run_history(history.id, status="success")
    engine = WorkflowEngine()
    engine._emit_log = lambda *_args: None
    try:
        state = engine.force_stop_run(history.id)
        assert state.status == "already_terminal"
        assert db.get_step_logs_by_run(history.id)[0].status == "cancelled"
        with db.get_fresh_session() as session:
            assert session.get(RunHistory, history.id).status == "success"
    finally:
        engine.shutdown()


def test_stale_owner_release_cannot_complete_or_release_current_owner(target):
    db, history, _, identity = target
    assert coordination.request_run_stop(history.id).status == "requested"
    with db.get_fresh_session() as session:
        owner = session.get(RunOwner, history.id)
        owner.owner_token = "replacement-owner"
        session.get(RunHistory, history.id).status = "success"
        session.commit()
    coordination.release_run_owner(history.id, history.run_id, identity.owner_token)
    with db.get_fresh_session() as session:
        assert session.get(RunOwner, history.id).released_at is None
        assert session.get(RunStopRequest, history.id).completed_at is None
    assert coordination.get_stop_state(history.id).status == "already_terminal"


def test_concurrent_history_delete_during_request_is_reported_not_found(monkeypatch, target):
    db, history, _log, _identity = target
    reached = []

    def delete_before_insert(_owner):
        reached.append(db.clear_run_histories(history.workflow_id))
        return "alive"

    monkeypatch.setattr(coordination, "owner_liveness", delete_before_insert)
    assert coordination.request_run_stop(history.id).status == "not_found"
    assert reached == [1]
