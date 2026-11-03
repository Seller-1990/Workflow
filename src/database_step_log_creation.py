"""Unique-arbitrated StepLog creation with clean-session commit reconciliation."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import time
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import StepLog

_operation_key = ContextVar("step_log_operation_key", default=None)
CREATION_ERRORS = (SQLAlchemyError, OSError, RuntimeError, ValueError)


@contextmanager
def step_log_operation(run_history_id: int, step_id: int):
    """Preserve legacy callable seams while binding one scheduled log identity."""
    token = _operation_key.set(f"step:{run_history_id}:{step_id}")
    try:
        yield
    finally:
        _operation_key.reset(token)


def _matching_row(session, operation_key, payload):
    row = session.query(StepLog).filter(StepLog.operation_key == operation_key).first()
    if row is not None and row.creation_payload != payload:
        raise ValueError(f"StepLog operation identity payload conflict: {operation_key}")
    return row


def create_step_log(
    run_history_id: int,
    step_id: int,
    order: int = 0,
    error_message: str | None = None,
    *,
    operation_key: str | None = None,
) -> StepLog:
    from database import get_fresh_session
    from database_runs import truncate_error_message

    key = operation_key if operation_key is not None else (_operation_key.get() or uuid.uuid4().hex)
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError("StepLog operation_key must be a nonempty string of at most 128 characters")
    note = truncate_error_message(error_message)
    initial_note = None if error_message is None else str(error_message)
    payload = json.dumps([run_history_id, step_id, order, initial_note], ensure_ascii=False, separators=(",", ":"))
    for attempt in range(3):
        try:
            with get_fresh_session() as session:
                existing = _matching_row(session, key, payload)
                if existing is not None:
                    return existing
                row = StepLog(
                    run_history_id=run_history_id, step_id=step_id, order=order,
                    status="pending", error_message=note,
                    operation_key=key, creation_payload=payload,
                )
                session.add(row)
                session.flush()
                session.commit()
                # All defaults/primary keys were materialized by flush. A refresh
                # adds no guarantee and must never authorize another INSERT.
                return row
        except CREATION_ERRORS as error:
            # The failed Session has been closed/discarded before this read.
            # If this read fails, propagate: uncertainty is not permission to retry.
            with get_fresh_session() as clean_session:
                existing = _matching_row(clean_session, key, payload)
                if existing is not None:
                    return existing
            if isinstance(error, (IntegrityError, ValueError)) or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("StepLog operation recovery exhausted")
