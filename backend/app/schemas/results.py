from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class TaskEventResponse(BaseModel):
    """Schema for individual execution events within a task."""

    id: int
    task_id: int
    stage: str
    event_type: str
    message: str
    created_at: datetime
    structured_metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class FileChangeResponse(BaseModel):
    """Schema for file diffs and modifications generated during a task."""

    id: int
    task_id: int
    relative_file_path: str
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    diff_text: Optional[str] = None
    change_summary: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestRunResponse(BaseModel):
    """Schema for test suite execution runs and output."""

    id: int
    task_id: int
    command: str
    exit_code: Optional[int] = None
    passed: Optional[bool] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
