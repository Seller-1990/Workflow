"""Exact-target durable cancellation for local processes sharing one SQLite DB."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select, update
from sqlalchemy.dialects.sqlite import insert

from database_coordination_models import RunOwner, RunStopRequest
from database_process_identity import owner_liveness
from models import RunHistory, StepLog

TERMINAL = frozenset(("success", "failure", "cancelled"))
_publishing_owner = ContextVar("publishing_run_owner", default=None)


@dataclass(frozen=True)
class StopState:
    status: str
    existing_status: str | None = None
    run_id: str | None = None
    owner_token: str | None = None


@contextmanager
def publish_owner(identity):
    token = _publishing_owner.set(identity)
    try:
        yield
    finally:
        _publishing_owner.reset(token)


def add_published_owner(session, history):
    identity = _publishing_owner.get()
    if identity is not None:
        session.add(RunOwner(
            run_history_id=history.id, run_id=history.run_id,
            owner_token=identity.owner_token, host_id=identity.host_id,
            process_id=identity.process_id, process_started=identity.process_started,
        ))


def _state(history, owner, request=None):
    if history is None:
        return StopState("not_found")
    if request is not None and (owner is None or (request.run_id, request.owner_token) != (owner.run_id, owner.owner_token)):
        request = None
    values = dict(existing_status=history.status, run_id=history.run_id,
                  owner_token=owner.owner_token if owner else None)
    if history.status in TERMINAL:
        return StopState("completed" if request else "already_terminal", **values)
    if request is not None:
        return StopState("acknowledged" if request.acknowledged_at else "requested", **values)
    return StopState("active" if owner else "ownerless", **values)


def get_stop_state(run_history_id):
    from database import get_fresh_session
    with get_fresh_session() as session:
        history = session.get(RunHistory, run_history_id)
        owner = session.get(RunOwner, run_history_id)
        request = session.get(RunStopRequest, run_history_id)
        return _state(history, owner, request)


def request_run_stop(run_history_id, *, expected_run_id=None, expected_owner_token=None):
    """Only request a live owner; unknown liveness never authorizes terminal writes."""
    from database import get_fresh_session
    with get_fresh_session() as session:
        history = session.get(RunHistory, run_history_id)
        owner = session.get(RunOwner, run_history_id)
        if history is None:
            return StopState("not_found")
        if ((expected_run_id is not None and expected_run_id != history.run_id)
                or (expected_owner_token is not None and (owner is None or expected_owner_token != owner.owner_token))):
            return StopState("conflict", history.status, history.run_id)
        if history.status in TERMINAL:
            return _state(history, owner, session.get(RunStopRequest, run_history_id))
        if owner is None:
            return StopState("ownerless", history.status, history.run_id)
        if owner.run_id != history.run_id:
            return StopState("unreachable", history.status, history.run_id, owner.owner_token)
        liveness = owner_liveness(owner)
        if liveness in ("dead", "released"):
            return StopState("orphaned", history.status, history.run_id, owner.owner_token)
        # INSERT..SELECT is one write/CAS: a normal terminal update wins safely.
        eligible = select(
            RunOwner.run_history_id, RunOwner.run_id, RunOwner.owner_token,
        ).join(RunHistory, RunHistory.id == RunOwner.run_history_id).where(
            RunOwner.run_history_id == run_history_id,
            RunOwner.run_id == history.run_id, RunOwner.owner_token == owner.owner_token,
            RunOwner.released_at.is_(None), RunHistory.status.in_(("pending", "running")),
        )
        statement = insert(RunStopRequest).from_select(
            ["run_history_id", "run_id", "owner_token"], eligible,
        ).on_conflict_do_nothing(index_elements=["run_history_id"])
        session.execute(statement)
        session.commit()
        session.expire_all()
        request = session.get(RunStopRequest, run_history_id)
        history = session.get(RunHistory, run_history_id)
        owner = session.get(RunOwner, run_history_id)
        if history is None or history.status in TERMINAL:
            return _state(history, owner, request)
        if owner is None or request is None or (request.run_id, request.owner_token) != (history.run_id, owner.owner_token):
            return StopState("conflict", history.status, history.run_id, owner.owner_token if owner else None)
        if liveness == "unknown":
            return StopState("unreachable", history.status, history.run_id, owner.owner_token)
        return _state(history, owner, request)


def acknowledge_stop_requests(owner_token, *, busy_timeout_ms=100):
    """Claim only exact, unreleased identities. Each poll owns and closes its Session."""
    from database import get_fresh_session
    with get_fresh_session(busy_timeout_ms=busy_timeout_ms) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        rows = session.execute(select(RunStopRequest.run_history_id).join(
            RunOwner, and_(RunOwner.run_history_id == RunStopRequest.run_history_id,
                           RunOwner.run_id == RunStopRequest.run_id,
                           RunOwner.owner_token == RunStopRequest.owner_token),
        ).join(RunHistory, and_(RunHistory.id == RunOwner.run_history_id,
                              RunHistory.run_id == RunOwner.run_id)).where(
            RunOwner.owner_token == owner_token, RunOwner.released_at.is_(None),
            RunHistory.status.in_(("pending", "running")),
            RunStopRequest.completed_at.is_(None),
        )).scalars().all()
        if rows:
            session.execute(update(RunStopRequest).where(
                RunStopRequest.run_history_id.in_(rows),
                RunStopRequest.owner_token == owner_token,
                RunStopRequest.acknowledged_at.is_(None),
            ).values(acknowledged_at=datetime.now()))
            session.commit()
        return rows


def release_run_owner(run_history_id, run_id, owner_token):
    from database import get_fresh_session
    with get_fresh_session(busy_timeout_ms=100) as session:
        session.execute(update(RunOwner).where(
            RunOwner.run_history_id == run_history_id, RunOwner.run_id == run_id,
            RunOwner.owner_token == owner_token, RunOwner.released_at.is_(None),
        ).values(released_at=datetime.now()))
        terminal = exists().where(RunHistory.id == run_history_id,
                                  RunHistory.run_id == run_id, RunHistory.status.in_(TERMINAL))
        session.execute(update(RunStopRequest).where(
            RunStopRequest.run_history_id == run_history_id, RunStopRequest.run_id == run_id,
            RunStopRequest.owner_token == owner_token, terminal,
            exists().where(RunOwner.run_history_id == run_history_id,
                           RunOwner.run_id == run_id, RunOwner.owner_token == owner_token),
        ).values(completed_at=datetime.now()))
        session.commit()


def recover_orphaned_run(run_history_id, *, expected_run_id, expected_owner_token=None):
    """Recheck owner while holding SQLite's writer reservation before any cleanup."""
    from database import get_fresh_session
    with get_fresh_session() as session:
        # No ORM reads before BEGIN IMMEDIATE: no stale read-to-write snapshot.
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        history = session.get(RunHistory, run_history_id)
        owner = session.get(RunOwner, run_history_id)
        if history is None:
            return StopState("not_found")
        if history.run_id != expected_run_id or (owner.owner_token if owner else None) != expected_owner_token:
            return StopState("conflict", history.status, history.run_id)
        if history.status in TERMINAL:
            return _state(history, owner, session.get(RunStopRequest, run_history_id))
        if owner is not None and (owner.run_id != history.run_id or owner_liveness(owner) not in ("dead", "released")):
            return StopState("unreachable", history.status, history.run_id, owner.owner_token)
        now = datetime.now()
        session.execute(update(StepLog).where(
            StepLog.run_history_id == run_history_id, StepLog.status.in_(("pending", "running")),
        ).values(status="cancelled", end_time=now, error_message="用户强制停止：孤儿运行已回收"))
        history.status, history.end_time = "cancelled", now
        if owner is not None:
            owner.released_at = now
        request = session.get(RunStopRequest, run_history_id)
        if request and (request.run_id, request.owner_token) == (history.run_id, expected_owner_token):
            request.completed_at = now
        session.commit()
        return StopState("cancelled", "cancelled", history.run_id, expected_owner_token)
