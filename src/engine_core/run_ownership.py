"""Lifecycle-scoped local owner observation, feeding the existing cancel chain."""
import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from database_process_identity import new_owner_identity
from database_run_creation import UncertainRunPublication
import database_run_ownership as persistence

logger = logging.getLogger(__name__)
OWNERSHIP_ERRORS = (SQLAlchemyError, OSError, RuntimeError)


class OwnedRun:
    def __init__(self, engine):
        self.engine = engine
        self.identity = new_owner_identity()
        self.history_id = None
        self.run_id = None
        self.stop = threading.Event()
        self.thread = None
        self.published = False
        self.uncertain_publication = None

    def create_and_register(self, create_history, **kwargs):
        from models import RunHistory

        with self.engine._lock:
            with persistence.publish_owner(self.identity):
                try:
                    history = create_history(**kwargs)
                except UncertainRunPublication as error:
                    self.uncertain_publication = error
                    raise
            self.history_id, self.run_id = history.id, history.run_id
            self.engine._active_run_ids.add(history.id)
        # ORM histories carry the durable claim; lightweight caller test doubles
        # intentionally have no database publication to observe.
        if isinstance(history, RunHistory):
            self.published = True
            self.thread = threading.Thread(
                target=self._watch, name=f"run-owner-{history.id}", daemon=True,
            )
            self.thread.start()
        return history

    def _observe(self):
        targets = persistence.acknowledge_stop_requests(self.identity.owner_token)
        with self.engine._lock:
            if not self.stop.is_set() and self.history_id in targets and self.history_id in self.engine._active_run_ids:
                # Targeting a nested run retains shared-engine propagation.
                self.engine._cancelled = True

    def observe_before_steps(self):
        if not self.published:
            return
        try:
            self._observe()
        except OWNERSHIP_ERRORS:
            logger.warning("运行停止请求暂时不可读取: run_history_id=%s", self.history_id, exc_info=True)

    def _watch(self):
        try:
            while not self.stop.is_set():
                self.observe_before_steps()
                self.stop.wait(0.1)
        finally:
            from database import cleanup_session
            cleanup_session()

    def close_observer(self):
        self.stop.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(timeout=0.5)
            if self.thread.is_alive():
                logger.warning("运行 owner 观察线程尚未退出: run_history_id=%s", self.history_id)

    def release(self):
        history_id, run_id = self.history_id, self.run_id
        if self.uncertain_publication is not None:
            # This candidate must never reach ID-only finalization. Exact release
            # is safe after either commit or rollback, even if SQLite reused ID.
            history_id = self.uncertain_publication.history_id
            run_id = self.uncertain_publication.run_id
        if history_id is not None and (self.published or self.uncertain_publication is not None):
            try:
                persistence.release_run_owner(history_id, run_id, self.identity.owner_token)
            except OWNERSHIP_ERRORS:
                logger.warning("运行 owner 释放失败: run_history_id=%s", history_id, exc_info=True)
