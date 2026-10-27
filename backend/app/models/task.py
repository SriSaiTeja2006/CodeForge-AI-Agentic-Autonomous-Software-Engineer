from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.task_event import TaskEvent
    from app.models.file_change import FileChange
    from app.models.test_run import TestRun


# States representing active in-progress execution
ACTIVE_RUNNING_STATUSES = {
    "running",
    "investigating",
    "planning",
    "editing",
    "testing",
    "diagnosing",
    "repairing",
    "verifying",
    "publishing",
    "pr_creation",
}

# Final, terminal states
TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "needs_human_review",
    "verification_failed",
    "publish_failed",
    "pr_creation_failed",
}


class Task(Base):
    """SQLAlchemy model representing an autonomous coding task."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_url: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    issue_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued", index=True)
    current_agent_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    events: Mapped[List["TaskEvent"]] = relationship(
        "TaskEvent", back_populates="task", cascade="all, delete-orphan", order_by="TaskEvent.created_at"
    )
    file_changes: Mapped[List["FileChange"]] = relationship(
        "FileChange", back_populates="task", cascade="all, delete-orphan", order_by="FileChange.id"
    )
    test_runs: Mapped[List["TestRun"]] = relationship(
        "TestRun", back_populates="task", cascade="all, delete-orphan", order_by="TestRun.started_at"
    )

    @property
    def is_active(self) -> bool:
        """Return True if task is actively executing in the workflow."""
        return self.status in ACTIVE_RUNNING_STATUSES

    @property
    def is_terminal(self) -> bool:
        """Return True if task has reached a final terminal state."""
        return self.status in TERMINAL_STATUSES

    @property
    def can_retry(self) -> bool:
        """Return True if task is eligible to be retried."""
        return not self.is_active and self.retry_count < self.max_retries
