"""Publish a RunHistory and its optional local owner in one durable transaction."""
from sqlalchemy.exc import SQLAlchemyError

from database_coordination_models import RunOwner
from models import RunHistory

PUBLICATION_ERRORS = (SQLAlchemyError, OSError, RuntimeError, ValueError)


class UncertainRunPublication(RuntimeError):
    """An INSERT candidate is known, but its durable publication is unverified."""

    def __init__(self, history_id, run_id):
        super().__init__(f"运行发布结果暂时无法确认: run_history_id={history_id}, run_id={run_id}")
        self.history_id, self.run_id = history_id, run_id


def create_run_history(
    workflow_id: int,
    run_mode: str = "full",
    run_mode_param: str = None,
    reason: str = "manual",
    trace_id: str = None,
    parent_run_id: str = None,
) -> RunHistory:
    from database import generate_uid, get_fresh_session
    from database_run_ownership import add_published_owner

    run_id = generate_uid()
    history_id = None
    owner_token = None
    try:
        with get_fresh_session() as session:
            history = RunHistory(
                workflow_id=workflow_id, run_id=run_id, status="pending",
                reason=reason, run_mode=run_mode, run_mode_param=run_mode_param,
                trace_id=trace_id or run_id, parent_run_id=parent_run_id,
            )
            session.add(history)
            session.flush()
            history_id = history.id
            add_published_owner(session, history)
            owner_token = next((row.owner_token for row in session.new if isinstance(row, RunOwner)), None)
            session.commit()
            return history
    except PUBLICATION_ERRORS:
        # A failed clean read is not evidence of either commit or rollback. Keep
        # the candidate separate from identities safe for ordinary finalization.
        if history_id is not None:
            try:
                with get_fresh_session() as session:
                    history = session.get(RunHistory, history_id)
                    if history is not None and history.run_id == run_id:
                        owner = session.get(RunOwner, history_id)
                        if owner_token is not None and (
                            owner is None or (owner.run_id, owner.owner_token) != (run_id, owner_token)
                        ):
                            raise ValueError("运行发布恢复时 owner 身份不匹配")
                        return history
            except PUBLICATION_ERRORS as recovery_error:
                raise UncertainRunPublication(history_id, run_id) from recovery_error
        raise
