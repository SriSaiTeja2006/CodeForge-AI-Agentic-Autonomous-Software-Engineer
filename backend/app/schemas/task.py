import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

class TaskBase(BaseModel):
    """Base fields for Task schemas."""

    repository_url: str = Field(
        ...,
        description="Target GitHub repository URL (HTTPS or SSH)",
        examples=["https://github.com/octocat/Hello-World"],
    )
    task_description: str = Field(
        ...,
        min_length=5,
        max_length=10000,
        description="Detailed description of the coding task or feature request",
    )
    acceptance_criteria: Optional[str] = Field(
        None,
        max_length=10000,
        description="Optional specific conditions required for task acceptance",
    )
    issue_number: Optional[int] = Field(
        None,
        gt=0,
        description="Optional associated GitHub issue number",
    )

    @field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, v: str) -> str:
        clean_url = (v or "").strip()
        if not clean_url:
            raise ValueError("repository_url cannot be empty")
        from app.services.github_service import parse_and_normalize_github_url
        try:
            _, _, normalized = parse_and_normalize_github_url(clean_url)
            return normalized
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            raise ValueError(
                f"Invalid repository URL. Must be a valid GitHub repository URL: {detail}"
            )

    @field_validator("task_description")
    @classmethod
    def validate_task_description(cls, v: str) -> str:
        clean_desc = v.strip()
        if not clean_desc:
            raise ValueError("task_description cannot be empty or whitespace only")
        return clean_desc


class TaskCreate(TaskBase):
    """Schema for creating a new autonomous coding task."""
    pass


class TaskResponse(BaseModel):
    """Detailed response schema for a task."""

    id: int
    repository_url: str
    issue_number: Optional[int] = None
    task_description: str
    acceptance_criteria: Optional[str] = None
    status: str
    current_agent_stage: Optional[str] = None
    retry_count: int
    max_retries: int
    error_summary: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    source_branch: Optional[str] = None
    target_branch: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Paginated response schema for task history."""

    items: List[TaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskRetryResponse(BaseModel):
    """Response schema following a permitted task retry request."""

    message: str
    task: TaskResponse


class TaskCancelResponse(BaseModel):
    """Response schema following a task cancellation request."""

    message: str
    task: TaskResponse


class TaskStateResponse(BaseModel):
    """Consolidated state and execution summary for a task."""

    id: int
    repository_url: str
    issue_number: Optional[int] = None
    task_description: str
    acceptance_criteria: Optional[str] = None
    status: str
    current_agent_stage: Optional[str] = None
    retry_count: int
    max_retries: int
    error_summary: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    source_branch: Optional[str] = None
    target_branch: Optional[str] = None
    is_active: bool
    is_terminal: bool
    can_retry: bool
    created_at: datetime
    updated_at: datetime
    events_count: int = 0
    file_changes_count: int = 0
    test_runs_count: int = 0

    model_config = ConfigDict(from_attributes=True)


from app.schemas.github import GitHubPullRequestRef


class TaskPRPreviewResponse(BaseModel):
    """Metadata, verification summary, and readiness checks for PR creation."""

    task_id: int
    repository_url: str
    head_branch: str
    base_branch: str
    suggested_title: str
    suggested_body: str
    file_changes_count: int
    test_runs_count: int
    tests_passed: bool
    safety_passed: bool
    safety_violations: List[str] = Field(default_factory=list)
    is_ready: bool
    readiness_issues: List[str] = Field(default_factory=list)
    is_approved: bool = False
    can_create_pr: bool = False
    existing_pr: Optional[GitHubPullRequestRef] = None

    model_config = ConfigDict(from_attributes=True)


class TaskPRApproveRequest(BaseModel):
    """Explicit human approval request payload."""

    approved: bool = Field(True, description="Must be explicitly True to confirm approval")
    comment: Optional[str] = Field(None, max_length=2000, description="Optional reviewer comment")


class TaskPRCreateRequest(BaseModel):
    """Request payload to create a pull request for a task."""

    approved: bool = Field(False, description="Must be explicitly True confirming human approval")
    title: Optional[str] = Field(None, min_length=1, max_length=512, description="Optional custom PR title")
    body: Optional[str] = Field(None, max_length=50000, description="Optional custom PR body")
    base_branch: Optional[str] = Field(None, description="Optional custom base branch (defaults to main)")
    draft: bool = Field(False, description="Whether to open the PR as a draft")

