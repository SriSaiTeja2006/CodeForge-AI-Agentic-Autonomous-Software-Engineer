import math
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.task import Task, ACTIVE_RUNNING_STATUSES, TERMINAL_STATUSES
from app.models.task_event import TaskEvent
from app.models.file_change import FileChange
from app.models.test_run import TestRun
from app.schemas.task import (
    TaskCreate,
    TaskResponse,
    TaskListResponse,
    TaskRetryResponse,
    TaskCancelResponse,
    TaskStateResponse,
    TaskPRPreviewResponse,
    TaskPRApproveRequest,
    TaskPRCreateRequest,
)
from app.schemas.github import GitHubPullRequestRef
from app.schemas.results import TaskEventResponse, FileChangeResponse, TestRunResponse
from app.services.github_service import parse_and_normalize_github_url
from app.services.task_runner import get_task_worker, get_task_runner
from app.services.pr_service import PullRequestService, get_pr_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """
    Validate, store, and schedule a new autonomous engineering task.
    Schedules execution via the durable PostgreSQL-backed task worker and returns immediately.
    """
    # Validate and normalize repository URL
    try:
        parse_and_normalize_github_url(payload.repository_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    new_task = Task(
        repository_url=payload.repository_url,
        task_description=payload.task_description,
        acceptance_criteria=payload.acceptance_criteria,
        issue_number=payload.issue_number,
        status="queued",
        current_agent_stage="queued",
        retry_count=0,
        max_retries=3,
    )
    db.add(new_task)
    db.flush()

    # Record initial lifecycle event
    initial_event = TaskEvent(
        task_id=new_task.id,
        stage="queued",
        event_type="task_created",
        message="Task created and scheduled in execution queue.",
        structured_metadata={
            "repository_url": new_task.repository_url,
            "issue_number": new_task.issue_number,
        },
    )
    db.add(initial_event)
    db.commit()
    db.refresh(new_task)

    # Signal the background worker that a new task is ready for execution
    worker = get_task_worker()
    worker.notify_new_task(new_task.id)

    return new_task


@router.get("", response_model=TaskListResponse)
def list_tasks(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by task status"),
    db: Session = Depends(get_db),
):
    """Retrieve paginated list of tasks ordered by creation time descending."""
    count_stmt = select(func.count(Task.id))
    if status:
        count_stmt = count_stmt.where(Task.status == status)
    total = db.scalar(count_stmt) or 0

    query = select(Task).order_by(Task.created_at.desc())
    if status:
        query = query.where(Task.status == status)

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    items = db.scalars(query).all()

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return TaskListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    """Retrieve details of a single task by ID."""
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )
    return task


@router.get("/{task_id}/state", response_model=TaskStateResponse)
def get_task_state(task_id: int, db: Session = Depends(get_db)):
    """
    Retrieve consolidated current state, activity status, and counts of events,
    changes, and test runs for a task.
    """
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    events_count = db.scalar(select(func.count(TaskEvent.id)).where(TaskEvent.task_id == task_id)) or 0
    file_changes_count = db.scalar(select(func.count(FileChange.id)).where(FileChange.task_id == task_id)) or 0
    test_runs_count = db.scalar(select(func.count(TestRun.id)).where(TestRun.task_id == task_id)) or 0

    return TaskStateResponse(
        id=task.id,
        repository_url=task.repository_url,
        issue_number=task.issue_number,
        task_description=task.task_description,
        acceptance_criteria=task.acceptance_criteria,
        status=task.status,
        current_agent_stage=task.current_agent_stage,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        error_summary=task.error_summary,
        pr_number=task.pr_number,
        pr_url=task.pr_url,
        source_branch=task.source_branch,
        target_branch=task.target_branch,
        is_active=task.is_active,
        is_terminal=task.is_terminal,
        can_retry=task.can_retry,
        created_at=task.created_at,
        updated_at=task.updated_at,
        events_count=events_count,
        file_changes_count=file_changes_count,
        test_runs_count=test_runs_count,
    )


@router.get("/{task_id}/events", response_model=List[TaskEventResponse])
def get_task_events(task_id: int, db: Session = Depends(get_db)):
    """Retrieve all execution events for a task ordered chronologically."""
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    events = db.scalars(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.created_at.asc(), TaskEvent.id.asc())
    ).all()
    return events


@router.get("/{task_id}/changes", response_model=List[FileChangeResponse])
def get_task_file_changes(task_id: int, db: Session = Depends(get_db)):
    """Retrieve all file changes and diffs generated for a task."""
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    changes = db.scalars(
        select(FileChange).where(FileChange.task_id == task_id).order_by(FileChange.id.asc())
    ).all()
    return changes


@router.get("/{task_id}/tests", response_model=List[TestRunResponse])
def get_task_test_runs(task_id: int, db: Session = Depends(get_db)):
    """Retrieve all verification test runs associated with a task."""
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    runs = db.scalars(
        select(TestRun).where(TestRun.task_id == task_id).order_by(TestRun.started_at.asc())
    ).all()
    return runs


@router.post("/{task_id}/retry", response_model=TaskRetryResponse)
def retry_task(task_id: int, db: Session = Depends(get_db)):
    """
    Request a permitted retry for a failed or stalled task.
    Locks row using SELECT FOR UPDATE to prevent race conditions and duplicate executions.
    Rejects running tasks with HTTP 409 Conflict and exceeded retry counts with HTTP 400 Bad Request.
    """
    # Prevent concurrent retry races by acquiring row-level lock
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    # Reject if the task is actively executing
    if task.status in ACTIVE_RUNNING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is currently running with status '{task.status}' and cannot be retried.",
        )

    # Reject if retry limit is reached
    if task.retry_count >= task.max_retries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} has reached its maximum retry limit ({task.max_retries}).",
        )

    # Transition task back to queued state
    task.retry_count += 1
    task.status = "queued"
    task.current_agent_stage = "queued"
    task.error_summary = None

    # Record retry event
    event = TaskEvent(
        task_id=task.id,
        stage="queued",
        event_type="retry_requested",
        message=f"Retry attempt {task.retry_count}/{task.max_retries} requested.",
        structured_metadata={
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(task)

    # Signal the background worker that the task has been re-queued
    worker = get_task_worker()
    worker.notify_new_task(task.id)

    return TaskRetryResponse(
        message=f"Task {task.id} successfully queued for retry (attempt {task.retry_count}/{task.max_retries}).",
        task=task,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
def cancel_task(task_id: int, db: Session = Depends(get_db)):
    """
    Cancel an active or queued task.
    Rejects tasks already in terminal states with HTTP 400 Bad Request.
    """
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found",
        )

    if task.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is already in terminal status '{task.status}' and cannot be cancelled.",
        )

    task.status = "cancelled"
    task.current_agent_stage = "cancelled"
    cancel_event = TaskEvent(
        task_id=task.id,
        stage="cancelled",
        event_type="task_cancelled",
        message="Task was cancelled by user request.",
    )
    db.add(cancel_event)
    db.commit()
    db.refresh(task)
    return TaskCancelResponse(
        message=f"Task {task.id} successfully marked as cancelled.",
        task=task,
    )


@router.get("/{task_id}/pr", response_model=TaskPRPreviewResponse)
def get_task_pr_preview(
    task_id: int,
    db: Session = Depends(get_db),
    pr_service: PullRequestService = Depends(get_pr_service),
):
    """
    Prepare PR metadata, concise verified change summary, test evidence, and safety scan.
    """
    return pr_service.get_task_pr_preview(db=db, task_id=task_id)


@router.post("/{task_id}/pr/approve")
def approve_task_pr(
    task_id: int,
    payload: TaskPRApproveRequest = TaskPRApproveRequest(approved=True),
    db: Session = Depends(get_db),
):
    """
    Explicitly record human approval for opening a pull request.
    """
    if not payload.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval must be explicitly confirmed (approved=True).",
        )
    task = db.scalar(select(Task).where(Task.id == task_id))
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found")

    approval_event = TaskEvent(
        task_id=task.id,
        stage="pr_approved",
        event_type="pr_approved",
        message="Pull request creation approved by human reviewer." + (f" Note: {payload.comment}" if payload.comment else ""),
        structured_metadata={"approved": True, "comment": payload.comment},
    )
    db.add(approval_event)
    db.commit()
    return {"message": f"Task {task_id} approved for pull request creation.", "task_id": task_id, "approved": True}


@router.post("/{task_id}/pr/create", response_model=GitHubPullRequestRef, status_code=status.HTTP_201_CREATED)
def create_task_pull_request(
    task_id: int,
    payload: TaskPRCreateRequest,
    db: Session = Depends(get_db),
    pr_service: PullRequestService = Depends(get_pr_service),
):
    """
    Create a real GitHub pull request for a verified task after human approval.
    Never merges automatically.
    """
    return pr_service.create_task_pull_request(
        db=db,
        task_id=task_id,
        approved=payload.approved,
        custom_title=payload.title,
        custom_body=payload.body,
        custom_base=payload.base_branch,
        draft=payload.draft,
    )
