"""Durable local run identity and exact-target cooperative stop requests."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database_base import Base


class RunOwner(Base):
    __tablename__ = "run_owners"

    run_history_id: Mapped[int] = mapped_column(
        ForeignKey("run_histories.id", ondelete="CASCADE"), primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_token: Mapped[str] = mapped_column(String(64), nullable=False)
    host_id: Mapped[str] = mapped_column(Text, nullable=False)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    process_started: Mapped[str | None] = mapped_column(String(128), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_run_owners_token", "owner_token"),)


class RunStopRequest(Base):
    __tablename__ = "run_stop_requests"

    run_history_id: Mapped[int] = mapped_column(
        ForeignKey("run_histories.id", ondelete="CASCADE"), primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_token: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
