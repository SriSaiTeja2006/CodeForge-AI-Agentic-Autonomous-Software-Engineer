from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, String, Text, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.task import Task


class TaskEvent(Base):
    """SQLAlchemy model for structured execution events occurring during a task."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    structured_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="events")
