from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.task import Task


class TestRun(Base):
    """SQLAlchemy model for recording test execution command results."""

    __tablename__ = "test_runs"
    __test__ = False  # Prevent pytest from attempting to collect this model as a test suite

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    command: Mapped[str] = mapped_column(String(1024), nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="test_runs")
