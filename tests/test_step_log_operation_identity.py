"""Isolated regressions for durable StepLog creation, not script exactly-once."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

import pytest
from sqlalchemy import select

from _schema_guard_utils import _use_temp_database
from models import StepLog


@pytest.fixture
def log_target(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("operation identity")
    step = db.create_step(workflow.id, "A", order=1)
    history = db.create_run_history(workflow.id)
    yield db, history.id, step.id
    db.cleanup_session()
    db._engine.dispose()


@pytest.mark.parametrize("commit_boundary", ("before", "after"))
def test_commit_uncertainty_reuses_one_operation(monkeypatch, log_target, commit_boundary):
    db, run_id, step_id = log_target
    real_commit = db.Session.commit
    observed = {"faults": 0, "sessions": [], "opened": []}
    real_fresh = db.get_fresh_session

    @contextmanager
    def record_session(**kwargs):
        with real_fresh(**kwargs) as session:
            observed["opened"].append(session)
            yield session

    monkeypatch.setattr(db, "get_fresh_session", record_session)

    def uncertain_commit(session):
        inserts_log = any(isinstance(row, StepLog) for row in session.new)
        # flush() empties session.new, so also inspect objects in the identity map.
        inserts_log = inserts_log or any(isinstance(row, StepLog) for row in session.identity_map.values())
        if inserts_log and not observed["faults"]:
            observed["faults"] += 1
            observed["sessions"].append(session)
            if commit_boundary == "after":
                real_commit(session)
            raise RuntimeError("commit result unknown")
        return real_commit(session)

    monkeypatch.setattr(db.Session, "commit", uncertain_commit)
    row = db.create_step_log(run_id, step_id, order=1)
    stored = db.get_step_logs_by_run(run_id)
    assert observed["faults"] == 1, "fault injection must actually reach the commit boundary"
    assert len(observed["opened"]) >= 2
    assert observed["opened"][0] is not observed["opened"][1], "reconciliation must use a different Session"
    assert [item.id for item in stored] == [row.id]
    assert row.operation_key


def test_replay_returns_current_row_and_conflict_is_explicit(log_target):
    db, run_id, step_id = log_target
    row = db.create_step_log(run_id, step_id, order=3, error_message="initial", operation_key="replay")
    db.update_step_log(row.id, status="success", error_message="changed after creation")
    replay = db.create_step_log(run_id, step_id, order=3, error_message="initial", operation_key="replay")
    assert (replay.id, replay.status, replay.error_message) == (row.id, "success", "changed after creation")
    for changes in ({"order": 4}, {"error_message": "different"}, {"step_id": step_id + 1}):
        payload = dict(run_history_id=run_id, step_id=step_id, order=3, error_message="initial")
        payload.update(changes)
        with pytest.raises(ValueError, match="operation|操作"):
            db.create_step_log(**payload, operation_key="replay")
    assert len(db.get_step_logs_by_run(run_id)) == 1


def test_competing_sessions_arbitrate_same_operation(log_target):
    db, run_id, step_id = log_target
    barrier = threading.Barrier(2)

    def create():
        barrier.wait(timeout=5)
        try:
            return db.create_step_log(run_id, step_id, order=2, operation_key="concurrent").id
        finally:
            db.cleanup_session()

    with ThreadPoolExecutor(max_workers=2) as workers:
        rows = list(workers.map(lambda _: create(), range(2)))
    assert rows[0] == rows[1]
    assert len(db.get_step_logs_by_run(run_id)) == 1


@pytest.mark.parametrize("commit_before_fault", (False, True))
def test_reconciliation_failure_never_authorizes_another_insert(monkeypatch, log_target, commit_before_fault):
    db, run_id, step_id = log_target
    real_commit = db.Session.commit
    real_fresh = getattr(db, "get_fresh_session", db.get_session)
    observed = {"commits": 0, "opens": 0}

    @contextmanager
    def unavailable_reconciliation(**kwargs):
        observed["opens"] += 1
        if observed["commits"]:
            raise OSError("reconciliation unavailable")
        with real_fresh(**kwargs) as session:
            yield session

    def commit_then_raise(session):
        if commit_before_fault:
            real_commit(session)
        observed["commits"] += 1
        raise RuntimeError("ack lost")

    monkeypatch.setattr(db, "get_fresh_session", unavailable_reconciliation, raising=False)
    monkeypatch.setattr(db.Session, "commit", commit_then_raise)
    with pytest.raises((OSError, RuntimeError), match="reconciliation|恢复"):
        db.create_step_log(run_id, step_id, order=1)
    assert observed["commits"] == 1
    with real_fresh() as session:
        assert len(session.scalars(select(StepLog)).all()) == int(commit_before_fault)


def test_legacy_calls_are_distinct_operations(log_target):
    db, run_id, step_id = log_target
    rows = [db.create_step_log(run_id, step_id, order=1) for _ in range(2)]
    assert rows[0].id != rows[1].id
    assert rows[0].operation_key != rows[1].operation_key


def test_conflict_compares_full_initial_note_not_truncated_projection(log_target):
    db, run_id, step_id = log_target
    prefix = "x" * 5000
    row = db.create_step_log(run_id, step_id, error_message=prefix + "A", operation_key="long-note")
    assert len(row.error_message) == 4096
    with pytest.raises(ValueError, match="operation identity payload conflict"):
        db.create_step_log(run_id, step_id, error_message=prefix + "B", operation_key="long-note")
    assert len(db.get_step_logs_by_run(run_id)) == 1
