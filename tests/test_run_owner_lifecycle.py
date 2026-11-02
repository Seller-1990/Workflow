"""Owner poller/session disposal on startup, nested, cancellation, and lock paths."""
from datetime import datetime
import threading
import time

import pytest
from sqlalchemy.exc import SQLAlchemyError

from _schema_guard_utils import _use_temp_database
from database_coordination_models import RunOwner
import database_run_ownership as coordination
from engine import RunMode, RunSignalPolicy, WorkflowEngine
import engine_core.lifecycle as lifecycle
from engine_core.run_ownership import OwnedRun


@pytest.fixture
def owned_engine(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("owner lifecycle")
    db.create_step(workflow.id, "A", script_path="unused.py")
    engine = WorkflowEngine()
    monkeypatch.setattr(lifecycle, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(engine, "_emit_log", lambda *_args: None)
    monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda *_args: None)
    yield db, workflow, engine
    engine.shutdown()
    db.cleanup_session()
    db._engine.dispose()
    assert not [t for t in threading.enumerate() if t.name.startswith("run-owner-")]


def _quiet():
    return RunSignalPolicy(False, False, False, False, False)


@pytest.mark.parametrize("failure_point", ("mkdir", "running_update", "observer_start"))
def test_owner_released_on_each_postpublication_startup_failure(monkeypatch, owned_engine, failure_point):
    db, workflow, engine = owned_engine
    reached = []
    executed = []
    monkeypatch.setattr(engine, "_execute_steps", lambda *_args, **_kwargs: executed.append(True))
    if failure_point == "mkdir":
        original = lifecycle.Path.mkdir

        def fail_mkdir(path, *args, **kwargs):
            if path.parent.parent == lifecycle.LOG_DIR:
                reached.append(True)
                raise OSError("mkdir fault")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(lifecycle.Path, "mkdir", fail_mkdir)
    elif failure_point == "running_update":
        original = lifecycle.update_run_history

        def fail_running(history_id, **kwargs):
            if kwargs.get("status") == "running":
                reached.append(True)
                raise RuntimeError("running fault")
            return original(history_id, **kwargs)
        monkeypatch.setattr(lifecycle, "update_run_history", fail_running)
    else:
        original = threading.Thread.start

        def fail_owner(thread):
            if thread.name.startswith("run-owner-"):
                reached.append(True)
                raise RuntimeError("thread start fault")
            return original(thread)
        monkeypatch.setattr(threading.Thread, "start", fail_owner)
    assert engine.run_all(workflow.id) is False
    assert reached == [True]
    history = db.get_run_histories_by_workflow(workflow.id)[0]
    assert history.status == "failure"
    assert executed == []
    assert engine._active_run_ids == set()
    with db.get_fresh_session() as session:
        assert session.get(RunOwner, history.id).released_at is not None


def test_nested_run_owners_release_without_losing_outer_claim(monkeypatch, owned_engine):
    db, workflow, engine = owned_engine
    child = db.create_workflow("child")
    db.create_step(child.id, "B", script_path="unused.py")
    observed = []

    def execute(current_workflow, _steps, history_id, *_args, **_kwargs):
        if current_workflow.id == workflow.id:
            assert engine.run(child.id, RunMode.FULL, allow_nested=True, signal_policy=_quiet()) is True
            with db.get_fresh_session() as session:
                owners = session.query(RunOwner).all()
                observed.append([(owner.run_history_id, owner.released_at is not None) for owner in owners])
            assert engine._active_run_ids == {history_id}
        return True

    monkeypatch.setattr(engine, "_execute_steps", execute)
    assert engine.run(workflow.id, RunMode.FULL, signal_policy=_quiet()) is True
    assert len(observed) == 1
    assert [released for _history_id, released in observed[0]] == [False, True]
    with db.get_fresh_session() as session:
        assert all(owner.released_at is not None for owner in session.query(RunOwner))
    assert engine._active_run_ids == set()


def test_observer_does_not_leak_sessions_or_wait_for_sqlite_writer(monkeypatch, owned_engine):
    db, workflow, engine = owned_engine
    scope = OwnedRun(engine)
    original_acknowledge = coordination.acknowledge_stop_requests
    polled = threading.Event()

    def observe_poll(*args, **kwargs):
        polled.set()
        return original_acknowledge(*args, **kwargs)

    def restore():
        # Idempotent teardown of acquired state: close_observer/release tolerate
        # repeated calls, so an assertion failure above cannot leak the daemon
        # run-owner thread or leave engine active IDs/_running behind.
        scope.close_observer()
        scope.release()
        engine._active_run_ids.clear()
        engine._running = False

    monkeypatch.setattr(coordination, "acknowledge_stop_requests", observe_poll)
    engine._running = True
    try:
        history = scope.create_and_register(lifecycle.create_run_history, workflow_id=workflow.id)
        assert polled.wait(3)
        assert coordination.request_run_stop(history.id).status in ("requested", "acknowledged")
        with db._engine.connect() as writer:
            writer.exec_driver_sql("BEGIN IMMEDIATE")
            before = time.monotonic()
            scope.close_observer()
            assert time.monotonic() - before < 0.8
            assert not scope.thread.is_alive()
            writer.rollback()
        restore()
        assert db._engine.pool.checkedout() == 0
    finally:
        restore()


def test_owner_release_after_failed_step_cleanup_remains_recoverable(monkeypatch, owned_engine):
    db, workflow, engine = owned_engine
    reached = []
    monkeypatch.setattr(engine, "_execute_steps", lambda *_args, **_kwargs: True)

    def fail_cleanup(*_args):
        reached.append(True)
        raise SQLAlchemyError("cleanup unavailable")

    monkeypatch.setattr(lifecycle, "finish_unfinished_step_logs", fail_cleanup)
    engine.run(workflow.id, RunMode.FULL, signal_policy=_quiet())
    assert reached == [True]
    history = db.get_run_histories_by_workflow(workflow.id)[0]
    assert history.status == "running", "never terminalize while step cleanup failed"
    assert coordination.request_run_stop(history.id).status == "orphaned"
    with db.get_fresh_session() as session:
        owner = session.get(RunOwner, history.id)
        token = owner.owner_token
        assert owner.released_at is not None
    assert coordination.recover_orphaned_run(history.id, expected_run_id=history.run_id, expected_owner_token=token).status == "cancelled"


def test_external_startup_request_is_checked_before_step_side_effects(monkeypatch, owned_engine):
    db, workflow, engine = owned_engine
    real_update = lifecycle.update_run_history
    reached, executed = [], []
    observer_gate = threading.Event()
    real_observe = OwnedRun.observe_before_steps

    def pause_background_observer(scope):
        if threading.current_thread().name.startswith("run-owner-"):
            observer_gate.wait(5)
            return
        return real_observe(scope)

    def request_during_initialization(history_id, **kwargs):
        if kwargs.get("status") == "running":
            reached.append(coordination.request_run_stop(history_id).status)
        return real_update(history_id, **kwargs)

    monkeypatch.setattr(OwnedRun, "observe_before_steps", pause_background_observer)
    monkeypatch.setattr(lifecycle, "update_run_history", request_during_initialization)
    monkeypatch.setattr(engine, "_execute_steps", lambda *_args, **_kwargs: executed.append(True))
    # Release the observer before close; only the run-thread pre-step check may
    # apply this request. The background test gate must not create a fake leak.
    original_close = OwnedRun.close_observer

    def close(scope):
        observer_gate.set()
        original_close(scope)

    monkeypatch.setattr(OwnedRun, "close_observer", close)
    try:
        assert engine.run(workflow.id, RunMode.FULL, signal_policy=_quiet()) is False
        assert reached == ["requested"]
        assert executed == []
        history = db.get_run_histories_by_workflow(workflow.id)[0]
        assert history.status == "cancelled"
        assert coordination.get_stop_state(history.id).status == "completed"
    finally:
        observer_gate.set()
