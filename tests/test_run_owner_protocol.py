"""Isolated exact-target owner protocol and process-liveness counterexamples."""
from dataclasses import replace
from datetime import datetime
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from _schema_guard_utils import _use_temp_database
from database_coordination_models import RunOwner, RunStopRequest
from database_process_identity import new_owner_identity, owner_liveness
import database_run_ownership as coordination
from models import RunHistory


@pytest.fixture
def owned_target(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("owner protocol")
    step = db.create_step(workflow.id, "A")
    identity = new_owner_identity()
    with coordination.publish_owner(identity):
        history = db.create_run_history(workflow.id)
    log = db.create_step_log(history.id, step.id)
    yield db, workflow, history, log, identity
    db.cleanup_session()
    db._engine.dispose()


def test_publication_is_atomic_and_unknown_commit_reconciles(monkeypatch, owned_target):
    db, workflow, _history, _log, identity = owned_target
    original_commit = db.Session.commit
    observed = []

    def commit_then_raise(session):
        has_owner = any(isinstance(row, RunOwner) for row in session.new)
        if has_owner:
            with db.get_fresh_session() as reader:
                observed.append((reader.query(RunHistory).count(), reader.query(RunOwner).count()))
            original_commit(session)
            raise RuntimeError("run commit acknowledgement lost")
        return original_commit(session)

    monkeypatch.setattr(db.Session, "commit", commit_then_raise)
    with coordination.publish_owner(identity):
        result = db.create_run_history(workflow.id)
    with db.get_fresh_session() as session:
        assert observed == [(1, 1)], "history and owner are invisible until the same commit"
        assert session.query(RunHistory).count() == session.query(RunOwner).count() == 2
        owner = session.get(RunOwner, result.id)
        assert (owner.owner_token, owner.run_id) == (identity.owner_token, result.run_id)


def test_wrong_identity_and_stale_request_cannot_cancel_or_ack(owned_target):
    db, _, history, _, identity = owned_target
    assert coordination.request_run_stop(history.id, expected_run_id="wrong").status == "conflict"
    assert coordination.request_run_stop(history.id, expected_owner_token="stale").status == "conflict"
    with db.get_fresh_session() as session:
        assert session.query(RunStopRequest).count() == 0
        session.add(RunStopRequest(run_history_id=history.id, run_id=history.run_id, owner_token="stale"))
        session.commit()
    assert coordination.acknowledge_stop_requests(identity.owner_token) == []
    assert coordination.request_run_stop(history.id).status == "conflict"
    assert coordination.get_stop_state(history.id).status == "active"
    with db.get_fresh_session() as session:
        assert session.get(RunHistory, history.id).status == "pending"
        assert session.get(RunStopRequest, history.id).acknowledged_at is None


def test_repeated_request_ack_and_normal_completion_race(owned_target):
    db, _, history, _, identity = owned_target
    first = coordination.request_run_stop(history.id)
    assert first.status == "requested"
    assert coordination.request_run_stop(history.id).status == "requested"
    assert coordination.acknowledge_stop_requests("not-this-owner") == []
    assert coordination.acknowledge_stop_requests(identity.owner_token) == [history.id]
    assert coordination.acknowledge_stop_requests(identity.owner_token) == [history.id], "ack replay must preserve cancellation until owner completion"
    assert coordination.get_stop_state(history.id).status == "acknowledged"
    # Normal completion can win before cooperative cancellation takes effect.
    db.update_run_history(history.id, status="success", end_time=datetime.now())
    coordination.release_run_owner(history.id, history.run_id, identity.owner_token)
    state = coordination.request_run_stop(history.id)
    assert (state.status, state.existing_status) == ("completed", "success")
    with db.get_fresh_session() as session:
        assert session.query(RunStopRequest).count() == 1
        assert session.get(RunStopRequest, history.id).completed_at is not None
        assert session.get(RunOwner, history.id).released_at is not None


@pytest.mark.parametrize("liveness", ("unknown", "alive", "dead", "released"))
def test_only_proven_dead_or_released_owner_allows_recovery(monkeypatch, owned_target, liveness):
    db, _, history, log, identity = owned_target
    monkeypatch.setattr(coordination, "owner_liveness", lambda _owner: liveness)
    request = coordination.request_run_stop(history.id)
    assert request.status == {"unknown": "unreachable", "alive": "requested", "dead": "orphaned", "released": "orphaned"}[liveness]
    recovered = coordination.recover_orphaned_run(
        history.id, expected_run_id=history.run_id, expected_owner_token=identity.owner_token,
    )
    permitted = liveness in ("dead", "released")
    assert recovered.status == ("cancelled" if permitted else "unreachable")
    assert db.get_step_logs_by_run(history.id)[0].status == ("cancelled" if permitted else "pending")
    assert db.get_run_histories_by_workflow(history.workflow_id)[0].status == ("cancelled" if permitted else "pending")


def test_orphan_recovery_rechecks_identity_liveness_and_preserves_terminal(monkeypatch, owned_target):
    db, _, history, _, identity = owned_target
    monkeypatch.setattr(coordination, "owner_liveness", lambda _owner: "dead")
    assert coordination.request_run_stop(history.id).status == "orphaned"
    assert coordination.recover_orphaned_run(
        history.id, expected_run_id="stale", expected_owner_token=identity.owner_token,
    ).status == "conflict"
    assert coordination.recover_orphaned_run(
        history.id, expected_run_id=history.run_id, expected_owner_token="wrong",
    ).status == "conflict"
    monkeypatch.setattr(coordination, "owner_liveness", lambda _owner: "unknown")
    assert coordination.recover_orphaned_run(
        history.id, expected_run_id=history.run_id, expected_owner_token=identity.owner_token,
    ).status == "unreachable"
    db.update_run_history(history.id, status="failure")
    assert coordination.recover_orphaned_run(
        history.id, expected_run_id=history.run_id, expected_owner_token=identity.owner_token,
    ).existing_status == "failure"


def test_liveness_requires_local_host_and_creation_token(monkeypatch):
    import database_process_identity as process_identity

    identity = new_owner_identity()
    owner = SimpleNamespace(**identity.__dict__, released_at=None)
    assert identity.process_id == os.getpid()
    assert owner_liveness(owner) == "alive", "real current process token must verify on this platform"
    owner.host_id = "foreign-host"
    assert owner_liveness(owner) == "unknown"
    owner.host_id = identity.host_id
    monkeypatch.setattr(process_identity, "inspect_process", lambda _pid: ("alive", "reused-pid-token"))
    assert owner_liveness(owner) == "dead", "same PID with a different creation token is the old dead owner"
    monkeypatch.setattr(process_identity, "inspect_process", lambda _pid: ("unknown", None))
    assert owner_liveness(owner) == "unknown"
    owner.released_at = datetime.now()
    assert owner_liveness(owner) == "released"


def test_missing_process_token_is_not_proof_of_death(monkeypatch):
    import database_process_identity as process_identity

    identity = new_owner_identity()
    owner = SimpleNamespace(**replace(identity, process_started=None).__dict__, released_at=None)
    monkeypatch.setattr(process_identity, "inspect_process", lambda _pid: ("alive", "present"))
    assert owner_liveness(owner) == "unknown"
    monkeypatch.setattr(process_identity, "inspect_process", lambda _pid: ("dead", None))
    assert owner_liveness(owner) == "dead"


def test_delete_history_cascades_only_its_coordination_rows(owned_target):
    db, workflow, history, _, identity = owned_target
    coordination.request_run_stop(history.id)
    assert db.clear_run_histories(workflow.id) == 1
    with db.get_fresh_session() as session:
        assert session.scalars(select(RunOwner)).all() == []
        assert session.scalars(select(RunStopRequest)).all() == []
