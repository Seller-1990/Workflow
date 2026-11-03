"""Surviving child and uncertain publication must not escape their owner family."""
from contextlib import contextmanager
import threading

import pytest
from sqlalchemy.exc import SQLAlchemyError

from _schema_guard_utils import _use_temp_database
from database_coordination_models import RunOwner
from database_process_identity import new_owner_identity
import database_run_ownership as coordination
from engine import RunMode, RunSignalPolicy, WorkflowEngine
import engine_core.lifecycle as lifecycle
from engine_core.run_ownership import OwnedRun
from executors.sub_workflow_executor import SubWorkflowExecutor
from models import RunHistory


@pytest.fixture
def isolated_engine(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("owner correction")
    db.create_step(workflow.id, "controlled", script_path="unused.py")
    engine = WorkflowEngine()
    monkeypatch.setattr(lifecycle, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(engine, "_emit_log", lambda *_args: None)
    monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda *_args: None)
    yield db, workflow, engine
    engine.shutdown()
    db.cleanup_session()
    db._engine.dispose()
    assert not [thread for thread in threading.enumerate() if thread.name.startswith("run-owner-")]


def _quiet():
    return RunSignalPolicy(False, False, False, False, False)


def test_surviving_child_blocks_next_root_until_exact_child_cleanup(monkeypatch, isolated_engine):
    db, root, engine = isolated_engine
    child = db.create_workflow("surviving child")
    db.create_step(child.id, "blocked", script_path="unused.py")
    following = db.create_workflow("unrelated next root")
    db.create_step(following.id, "next", script_path="unused.py")
    child_entered, child_done = threading.Event(), threading.Event()
    release_child, release_next = threading.Event(), threading.Event()
    next_ready, child_stop_observed = threading.Event(), threading.Event()
    child_threads, child_results, child_ids = [], [], []
    interrupted, next_results, next_executed, expired = [], [], [], []
    real_runner = engine.run_sub_workflow
    real_observe = OwnedRun._observe

    def child_runner(workflow_id, reason, cancel_event, subworkflow_depth):
        child_threads.append(threading.current_thread())
        try:
            result = real_runner(workflow_id, reason, cancel_event, subworkflow_depth)
            child_results.append(result)
            return result
        finally:
            child_done.set()

    def observe(scope):
        real_observe(scope)
        if child_ids and scope.history_id == child_ids[0] and engine.is_cancelled:
            child_stop_observed.set()

    def execute(workflow, _steps, history_id, *_args, **_kwargs):
        if workflow.id == child.id:
            child_ids.append(history_id)
            child_entered.set()
            if not release_child.wait(8):
                expired.append("child")
            return True
        if workflow.id == root.id:
            result = SubWorkflowExecutor().execute(
                script_path=child.uid, workflow_id=root.id,
                workflow_runner=child_runner, timeout=0.15,
            )
            interrupted.append(result)
            return result.success
        next_executed.append(history_id)
        next_ready.set()
        if not release_next.wait(8):
            expired.append("next")
        return True

    def try_next_root():
        try:
            next_results.append(engine.run(following.id, RunMode.FULL, signal_policy=_quiet()))
        finally:
            next_ready.set()
            db.cleanup_session()

    monkeypatch.setattr(OwnedRun, "_observe", observe)
    monkeypatch.setattr(engine, "_execute_steps", execute)
    next_thread = threading.Thread(target=try_next_root, name="attempt-unrelated-root")
    try:
        assert engine.run(root.id, RunMode.FULL, signal_policy=_quiet()) is False
        assert child_entered.is_set() and not child_done.is_set()
        assert interrupted[0].extra["background_risk"] is True
        assert engine._active_run_ids == set(child_ids)
        assert engine.is_running is False
        child_history = db.get_run_histories_by_workflow(child.id)[0]
        with db.get_fresh_session() as session:
            child_token = session.get(RunOwner, child_history.id).owner_token
        next_thread.start()
        assert next_ready.wait(5), "attempt must reach either rejection or next-root execution"
        attempt = {
            "executed": bool(next_executed),
            "history_count": len(db.get_run_histories_by_workflow(following.id)),
            "root_running": engine.is_running,
        }
        stop = coordination.request_run_stop(
            child_history.id, expected_run_id=child_history.run_id,
            expected_owner_token=child_token,
        )
        assert stop.status in ("requested", "acknowledged")
        assert child_stop_observed.wait(5), "the exact surviving child's real observer must apply its request"
        attempt["old_child_cancelled_next_root"] = bool(next_executed) and engine.is_cancelled
        assert coordination.get_stop_state(child_history.id).status == "acknowledged"
    finally:
        release_next.set()
        release_child.set()
        if next_thread.ident is not None:
            next_thread.join(timeout=8)
        assert child_done.wait(8)
        for thread in child_threads:
            thread.join(timeout=5)
        assert not next_thread.is_alive()
        assert all(not thread.is_alive() for thread in child_threads)
    assert expired == []
    assert engine._active_run_ids == set()
    assert attempt == {
        "executed": False, "history_count": 0, "root_running": False,
        "old_child_cancelled_next_root": False,
    }, attempt
    assert len(child_results) == 1 and next_results == [False]
    assert coordination.get_stop_state(child_history.id).status == "completed"
    assert engine.run(following.id, RunMode.FULL, signal_policy=_quiet()) is True
    assert len(db.get_run_histories_by_workflow(following.id)) == 1
    assert engine.is_cancelled is False


@pytest.mark.parametrize("boundary", ("before_publication", "after_context_restore"))
def test_surviving_child_slot_blocks_next_root_outside_active_id_window(monkeypatch, isolated_engine, boundary):
    import engine as engine_module

    db, root, engine = isolated_engine
    child = db.create_workflow("startup or cleanup child")
    db.create_step(child.id, "controlled child", script_path="unused.py")
    following = db.create_workflow("next root outside ID window")
    db.create_step(following.id, "next", script_path="unused.py")
    boundary_entered, release_boundary = threading.Event(), threading.Event()
    finish_child, child_done = threading.Event(), threading.Event()
    child_threads, timed_out, attempted, expired = [], [], [], []
    original_lookup = engine_module.get_workflow_by_id
    original_release = engine._release_subworkflow_slot
    original_runner = engine.run_sub_workflow

    def wait_boundary():
        boundary_entered.set()
        if not release_boundary.wait(8):
            expired.append(boundary)

    def lookup(workflow_id):
        if workflow_id == child.id and boundary == "before_publication":
            wait_boundary()
        return original_lookup(workflow_id)

    def release_slot():
        if boundary == "after_context_restore":
            wait_boundary()
        original_release()

    def runner(workflow_id, reason, cancel_event, subworkflow_depth):
        child_threads.append(threading.current_thread())
        try:
            return original_runner(workflow_id, reason, cancel_event, subworkflow_depth)
        finally:
            child_done.set()

    def execute(workflow, _steps, _history_id, *_args, **_kwargs):
        if workflow.id == root.id:
            result = SubWorkflowExecutor().execute(
                script_path=child.uid, workflow_id=root.id,
                workflow_runner=runner, timeout=0.15,
            )
            timed_out.append(result)
            return result.success
        if workflow.id == child.id:
            if not finish_child.wait(8):
                expired.append("child execution")
            return True
        attempted.append(True)
        return True

    monkeypatch.setattr(engine_module, "get_workflow_by_id", lookup)
    monkeypatch.setattr(engine, "_release_subworkflow_slot", release_slot)
    monkeypatch.setattr(engine, "_execute_steps", execute)
    try:
        assert engine.run(root.id, RunMode.FULL, signal_policy=_quiet()) is False
        assert timed_out[0].extra["background_risk"] is True
        if boundary == "after_context_restore":
            finish_child.set()
        assert boundary_entered.wait(5) and not child_done.is_set()
        assert engine.is_running is False and engine._active_run_ids == set()
        assert engine._active_subworkflow_count == 1
        result = engine.run(following.id, RunMode.FULL, signal_policy=_quiet())
        observation = (result, list(attempted), len(db.get_run_histories_by_workflow(following.id)))
    finally:
        finish_child.set()
        release_boundary.set()
        assert child_done.wait(8)
        for thread in child_threads:
            thread.join(timeout=5)
        assert all(not thread.is_alive() for thread in child_threads)
    assert expired == []
    assert observation == (False, [], 0), "an in-flight child must reserve its engine before publication and through cleanup"
    assert engine._active_subworkflow_count == 0 and engine._active_run_ids == set()
    assert engine.run(following.id, RunMode.FULL, signal_policy=_quiet()) is True


@pytest.mark.parametrize("next_cancelled", (False, True), ids=("healthy-next-root", "cancelled-next-root"))
def test_running_child_before_slot_cannot_publish_into_next_root(monkeypatch, isolated_engine, next_cancelled):
    db, root, engine = isolated_engine
    child = db.create_workflow("old child before slot")
    db.create_step(child.id, "stale", script_path="unused.py")
    following = db.create_workflow("next root during old worker")
    db.create_step(following.id, "next", script_path="unused.py")
    normal = db.create_workflow("uncancelled nested control")
    db.create_step(normal.id, "normal", script_path="unused.py")
    before_slot, release_slot, child_done = threading.Event(), threading.Event(), threading.Event()
    next_entered, release_next, stop_observed = threading.Event(), threading.Event(), threading.Event()
    normal_check = threading.Event()
    workers, child_events, slot_calls, child_results = [], [], [], []
    interrupted, next_results, late_publications, requests, expired = [], [], [], [], []
    normal_executed, normal_results = [], []
    real_acquire = engine._acquire_subworkflow_slot
    real_runner = engine.run_sub_workflow
    real_update = lifecycle.update_run_history
    real_observe = OwnedRun._observe

    def acquire_after_gate():
        if workers and threading.current_thread() is workers[0]:
            before_slot.set()
            if not release_slot.wait(8):
                expired.append("before slot")
        acquired = real_acquire()
        slot_calls.append(acquired)
        return acquired

    def runner(workflow_id, reason, cancel_event, subworkflow_depth):
        workers.append(threading.current_thread())
        child_events.append(cancel_event)
        try:
            result = real_runner(workflow_id, reason, cancel_event, subworkflow_depth)
            child_results.append(result)
            return result
        finally:
            child_done.set()

    def observe(scope):
        real_observe(scope)
        if late_publications and scope.history_id == late_publications[0] and engine.is_cancelled:
            stop_observed.set()

    def update(history_id, **kwargs):
        result = real_update(history_id, **kwargs)
        if kwargs.get("status") == "running":
            with db.get_fresh_session() as session:
                history = session.get(RunHistory, history_id)
                if history.workflow_id != child.id:
                    return result
                owner = session.get(RunOwner, history_id)
                identity = (history.run_id, owner.owner_token)
            late_publications.append(history_id)
            requests.append(coordination.request_run_stop(
                history_id, expected_run_id=identity[0], expected_owner_token=identity[1],
            ).status)
            if not stop_observed.wait(5):
                expired.append("old child observation")
        return result

    def execute(workflow, _steps, history_id, *_args, **_kwargs):
        if workflow.id == root.id:
            result = SubWorkflowExecutor().execute(
                script_path=child.uid, workflow_id=root.id,
                workflow_runner=runner, timeout=0.15,
            )
            interrupted.append(result)
            return result.success
        if workflow.id == following.id:
            next_entered.set()
            if not release_next.wait(8):
                expired.append("next root")
            if normal_check.is_set():
                normal_results.append(engine.run_sub_workflow(normal.id))
            return True
        if workflow.id == normal.id:
            normal_executed.append(history_id)
        return True

    def next_root():
        try:
            next_results.append(engine.run(following.id, RunMode.FULL, signal_policy=_quiet()))
        finally:
            db.cleanup_session()

    def shared_state():
        with engine._lock:
            return (engine._running, engine._cancelled, engine._current_run_history_id,
                    engine._current_run_id, frozenset(engine._active_run_ids))

    monkeypatch.setattr(engine, "_acquire_subworkflow_slot", acquire_after_gate)
    monkeypatch.setattr(engine, "_execute_steps", execute)
    monkeypatch.setattr(lifecycle, "update_run_history", update)
    monkeypatch.setattr(OwnedRun, "_observe", observe)
    next_thread = threading.Thread(target=next_root, name="next-root-before-child-slot")
    try:
        assert engine.run(root.id, RunMode.FULL, signal_policy=_quiet()) is False
        assert before_slot.is_set() and not child_done.is_set()
        assert len(workers) == 1 and workers[0].is_alive()
        assert child_events[0].is_set(), "real timeout/grace must cancel the running old future"
        assert interrupted[0].extra["background_risk"] is True
        assert engine.is_running is False and engine._active_run_ids == set()
        assert engine._active_subworkflow_count == 0 and slot_calls == []
        assert db.get_run_histories_by_workflow(child.id) == []
        next_thread.start()
        assert next_entered.wait(5), "unrelated next root must reach actual execution before resuming old child"
        if next_cancelled:
            engine.cancel()
        expected_state = shared_state()
        assert expected_state[1] is next_cancelled
        release_slot.set()
        assert child_done.wait(8)
        actual_state = shared_state()
        late_rows = len(db.get_run_histories_by_workflow(child.id))
    finally:
        release_slot.set()
        release_next.set()
        if next_thread.ident is not None:
            next_thread.join(timeout=8)
        if workers:
            assert child_done.wait(8)
        for worker in workers:
            worker.join(timeout=5)
        assert not next_thread.is_alive() and all(not worker.is_alive() for worker in workers)
    assert expired == []
    assert slot_calls == [True] and child_results == [False]
    assert {
        "late_child_publications": late_rows,
        "late_stop_requests": requests,
        "next_cancelled_before": expected_state[1],
        "next_cancelled_after": actual_state[1],
    } == {
        "late_child_publications": 0, "late_stop_requests": [],
        "next_cancelled_before": next_cancelled, "next_cancelled_after": next_cancelled,
    }, "an already-cancelled old worker must not publish an owner or contaminate the new root"
    assert actual_state == expected_state, "rejected stale work must not change any shared run context"
    assert next_results == [True]
    assert engine._active_subworkflow_count == 0 and engine._active_run_ids == set()
    assert db.get_run_histories_by_workflow(following.id)[0].status == ("cancelled" if next_cancelled else "success")
    normal_check.set()
    assert engine.run(following.id, RunMode.FULL, signal_policy=_quiet()) is True
    assert normal_results == [True] and len(normal_executed) == 1
    assert engine._active_subworkflow_count == 0 and engine._active_run_ids == set()
    assert engine.is_cancelled is False


@pytest.mark.parametrize("publication", ("committed", "rolled_back", "reused_id", "reused_id_reader_ok"))
def test_uncertain_publication_reader_failure_releases_only_exact_claim(monkeypatch, isolated_engine, publication):
    db, workflow, engine = isolated_engine
    original_commit = db.Session.commit
    original_fresh = db.get_fresh_session
    reached, candidates, executed, finalized = [], [], [], []
    recovery_due = False
    replacement_identity = new_owner_identity()
    real_finalize = engine._finalize_run_history

    def lose_commit_ack(session):
        nonlocal recovery_due
        owners = [row for row in session.new if isinstance(row, RunOwner)]
        if owners and not candidates:
            owner = owners[0]
            candidates.append((owner.run_history_id, owner.run_id, owner.owner_token))
            if publication == "committed":
                original_commit(session)
                reached.append("real_commit")
            else:
                reached.append("rolled_back_publication")
            recovery_due = True
            raise RuntimeError("publication acknowledgement lost")
        return original_commit(session)

    @contextmanager
    def first_recovery_reader_fails(**kwargs):
        nonlocal recovery_due
        if recovery_due:
            recovery_due = False
            if publication in ("reused_id", "reused_id_reader_ok"):
                history_id, run_id, _owner_token = candidates[0]
                with original_fresh() as session:
                    session.add(RunHistory(
                        id=history_id, workflow_id=workflow.id, run_id=run_id,
                        status="running", reason="replacement",
                    ))
                    session.flush()
                    session.add(RunOwner(
                        run_history_id=history_id, run_id=run_id,
                        **replacement_identity.__dict__,
                    ))
                    session.commit()
                reached.append("same_numeric_and_run_id_reused_by_other_owner")
            if publication == "reused_id_reader_ok":
                reached.append("clean_reader_available_for_replacement")
            else:
                reached.append("first_clean_reader_failed")
                raise SQLAlchemyError("first clean reader unavailable")
        with original_fresh(**kwargs) as session:
            yield session

    def finalize(history_id, *args):
        finalized.append(history_id)
        return real_finalize(history_id, *args)

    monkeypatch.setattr(db.Session, "commit", lose_commit_ack)
    monkeypatch.setattr(db, "get_fresh_session", first_recovery_reader_fails)
    monkeypatch.setattr(engine, "_finalize_run_history", finalize)
    monkeypatch.setattr(engine, "_execute_steps", lambda *_args, **_kwargs: executed.append(True))
    result = engine.run(workflow.id, RunMode.FULL, signal_policy=_quiet())
    assert reached == {
        "committed": ["real_commit", "first_clean_reader_failed"],
        "rolled_back": ["rolled_back_publication", "first_clean_reader_failed"],
        "reused_id": ["rolled_back_publication", "same_numeric_and_run_id_reused_by_other_owner", "first_clean_reader_failed"],
        "reused_id_reader_ok": ["rolled_back_publication", "same_numeric_and_run_id_reused_by_other_owner", "clean_reader_available_for_replacement"],
    }[publication]
    assert len(candidates) == 1
    assert engine._active_run_ids == set() and engine.is_running is False
    with original_fresh() as session:
        histories = session.query(RunHistory).all()
        owner = session.get(RunOwner, candidates[0][0])
        if publication == "rolled_back":
            assert histories == [] and owner is None
        elif publication in ("reused_id", "reused_id_reader_ok"):
            assert len(histories) == 1 and histories[0].status == "running"
            assert owner.owner_token == replacement_identity.owner_token
            assert owner.released_at is None, "uncertain cleanup must not release a replacement owner"
        else:
            assert len(histories) == 1 and histories[0].status == "pending"
            assert owner.owner_token == candidates[0][2]
            assert owner.released_at is not None, "published owner must not remain live and unobserved after DB recovers"
    assert result is False and executed == []
    assert finalized == [None], "unverified numeric IDs must never enter ordinary finalization"
    if publication == "committed":
        history_id, run_id, token = candidates[0]
        assert coordination.request_run_stop(history_id).status == "orphaned"
        assert coordination.recover_orphaned_run(
            history_id, expected_run_id=run_id, expected_owner_token=token,
        ).status == "cancelled"
