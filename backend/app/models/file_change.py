from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.task import Task


class FileChange(Base):
    """SQLAlchemy model representing a file modified or generated for a task."""

    __tablename__ = "file_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    relative_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diff_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="file_changes")
