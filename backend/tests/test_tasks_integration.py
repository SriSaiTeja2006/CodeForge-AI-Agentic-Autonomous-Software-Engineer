import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models.task import Task, ACTIVE_RUNNING_STATUSES
from app.models.task_event import TaskEvent
from app.models.file_change import FileChange
from app.models.test_run import TestRun
from app.agent.tools import WorkspaceTools
from app.services.llm_service import LLMService
from app.services.github_service import GitHubService
from app.services.task_runner import TaskRunner, TaskWorker, get_task_worker, reset_task_worker_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_worker_state():
    """Ensure clean worker state between tests."""
    yield
    reset_task_worker_for_testing(None)


def make_mock_services(test_passes: bool = True):
    """Helper to construct coordinated mock services for integration testing."""
    mock_llm = MagicMock(spec=LLMService)
    def mock_invoke(prompt, **kwargs):
        if "file_path" in kwargs or "patch" in str(prompt).lower():
            return "def add(a, b):\n    return a + b\n"
        return "Root cause analyzed: missing add function"

    mock_llm.invoke_prompt.side_effect = mock_invoke

    mock_github = MagicMock(spec=GitHubService)
    mock_github.token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-mock-integration-token")

    test_tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return a - b\n"},
        test_runner_fn=lambda cmd: {
            "exit_code": 0 if test_passes else 1,
            "passed": test_passes,
            "stdout": "1 passed in 0.02s" if test_passes else "FAILED test_calc.py",
            "stderr": "" if test_passes else "AssertionError: expected 3, got -1",
        },
    )

    return mock_llm, mock_github, test_tools


# ==============================================================================
# 1. POST /tasks VALIDATION & IMMEDIATE RETURN
# ==============================================================================

def test_create_task_returns_immediately_and_schedules():
    """Verify POST /tasks stores task, returns HTTP 201 immediately, and notifies worker."""
    mock_worker = MagicMock(spec=TaskWorker)
    reset_task_worker_for_testing(mock_worker)

    payload = {
        "repository_url": "https://github.com/octocat/Hello-World",
        "task_description": "Fix calculation logic in arithmetic utility.",
        "acceptance_criteria": "All unit tests pass.",
        "issue_number": 101,
    }

    res = client.post("/tasks", json=payload)
    assert res.status_code == 201
    data = res.json()
    task_id = data["id"]
    assert task_id is not None
    assert data["status"] == "queued"
    assert data["current_agent_stage"] == "queued"
    assert data["retry_count"] == 0

    # Verify background worker was notified with task ID
    mock_worker.notify_new_task.assert_called_once_with(task_id)

    # Verify task persisted in DB
    db = SessionLocal()
    try:
        task = db.scalar(select(Task).where(Task.id == task_id))
        assert task is not None
        assert task.status == "queued"

        # Check initial event
        events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)).all()
        assert len(events) == 1
        assert events[0].event_type == "task_created"
        assert events[0].stage == "queued"
    finally:
        db.close()


def test_create_task_invalid_repository_url():
    """Verify POST /tasks rejects non-GitHub or invalid URLs with HTTP 422."""
    res = client.post(
        "/tasks",
        json={
            "repository_url": "ftp://malicious.org/repo",
            "task_description": "Valid description with enough length",
        },
    )
    assert res.status_code == 422


def test_create_task_with_tree_branch_url():
    """Verify POST /tasks accepts GitHub URLs containing tree/branch paths and normalizes them."""
    res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab/tree/main",
            "task_description": "Analyze and fix GitHub issue #1 in my repository",
            "issue_number": 1,
            "acceptance_criteria": "Tests pass without regressions.",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["id"] is not None
    assert data["repository_url"] == "https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab"
    assert data["issue_number"] == 1
    assert data["status"] == "queued"


# ==============================================================================
# 2. END-TO-END WORKER CLAIM & LANGGRAPH EXECUTION
# ==============================================================================

def test_worker_processes_queued_task_to_completion():
    """
    Verify worker claims next task via SKIP LOCKED, executes LangGraph agent,
    updates stages dynamically, and persists FileChanges, TestRuns, and TaskEvents.
    """
    mock_llm, mock_github, test_tools = make_mock_services(test_passes=True)

    # Create task in database
    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Fix arithmetic subtraction bug in calculator.",
        status="queued",
        current_agent_stage="queued",
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id
    db.close()

    # Configure custom TaskRunner with mock services
    runner = TaskRunner(
        llm_service=mock_llm,
        github_service=mock_github,
        default_max_repairs=2,
    )

    # Mock setup_task_workspace to use our test tools
    runner.setup_task_workspace = MagicMock(return_value=test_tools)

    worker = TaskWorker(task_runner=runner)

    # Process next task through worker
    processed_id = worker.process_next_task(task_id=task_id)
    assert processed_id == task_id

    # Verify database state after agent execution
    db = SessionLocal()
    try:
        updated = db.scalar(select(Task).where(Task.id == task_id))
        assert updated.status == "completed"
        assert updated.current_agent_stage == "completed"
        assert updated.error_summary is None

        # Verify FileChanges persisted
        changes = db.scalars(select(FileChange).where(FileChange.task_id == task_id)).all()
        assert len(changes) >= 1
        assert changes[0].relative_file_path == "calc.py"
        assert "def add(a, b):" in changes[0].new_content
        assert changes[0].diff_text != ""

        # Verify TestRun persisted with real output
        test_runs = db.scalars(select(TestRun).where(TestRun.task_id == task_id)).all()
        assert len(test_runs) >= 1
        assert test_runs[0].passed is True
        assert test_runs[0].exit_code == 0
        assert "1 passed" in test_runs[0].stdout

        # Verify events progression
        events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id.asc())).all()
        stages = [e.stage for e in events]
        assert "investigating" in stages
        assert "planning" in stages
        assert "editing" in stages
        assert "testing" in stages
        assert "verifying" in stages
        assert "completed" in stages
    finally:
        db.close()


# ==============================================================================
# 3. CONCURRENT EXECUTION PREVENTION
# ==============================================================================

def test_prevent_concurrent_execution_of_same_task():
    """Verify attempting to run the same task concurrently is strictly prevented."""
    runner = TaskRunner()
    task_id = 888

    # Simulate task already running in this worker
    with runner._lock:
        runner._active_task_ids.add(task_id)

    with pytest.raises(RuntimeError) as exc:
        runner.run_task(task_id)
    assert "already actively running" in str(exc.value).lower()
    assert "concurrent" in str(exc.value).lower()

    # Clean up lock
    with runner._lock:
        runner._active_task_ids.discard(task_id)


# ==============================================================================
# 4. RETRIEVE CURRENT TASK STATE & EXECUTION HISTORY ENDPOINTS
# ==============================================================================

def test_get_task_state_endpoint_and_subresources():
    """Verify GET /tasks/{task_id}/state returns live counts and state."""
    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Live state inspection test.",
        status="running",
        current_agent_stage="testing",
        retry_count=1,
        max_retries=3,
    )
    db.add(task)
    db.flush()

    event = TaskEvent(task_id=task.id, stage="testing", event_type="test_run", message="Running unit tests.")
    change = FileChange(
        task_id=task.id,
        relative_file_path="foo.py",
        original_content="a=1",
        new_content="a=2",
        diff_text="diff",
        change_summary="update",
    )
    run = TestRun(
        task_id=task.id,
        command="pytest",
        exit_code=0,
        passed=True,
        stdout="passed",
        stderr="",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.add(change)
    db.add(run)
    db.commit()
    task_id = task.id
    db.close()

    res = client.get(f"/tasks/{task_id}/state")
    assert res.status_code == 200
    state_data = res.json()
    assert state_data["id"] == task_id
    assert state_data["status"] == "running"
    assert state_data["current_agent_stage"] == "testing"
    assert state_data["is_active"] is True
    assert state_data["is_terminal"] is False
    assert state_data["can_retry"] is False
    assert state_data["events_count"] == 1
    assert state_data["file_changes_count"] == 1
    assert state_data["test_runs_count"] == 1


# ==============================================================================
# 5. STALE TASK RECOVERY AFTER CRASH OR TIMEOUT
# ==============================================================================

def test_stale_task_recovery_requeues_when_retries_remain():
    """Verify recover_stale_tasks re-queues orphaned running tasks if retries remain."""
    db = SessionLocal()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=600)

    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Orphaned task after hypothetical worker crash.",
        status="running",
        current_agent_stage="testing",
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Force updated_at into the past
    task.updated_at = stale_time
    db.commit()
    task_id = task.id
    db.close()

    runner = TaskRunner()
    recovered = runner.recover_stale_tasks(stale_threshold_seconds=300)
    assert task_id in recovered

    db = SessionLocal()
    try:
        updated = db.scalar(select(Task).where(Task.id == task_id))
        assert updated.status == "queued"
        assert updated.current_agent_stage == "queued"
        assert updated.retry_count == 1

        events = db.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.event_type == "stale_task_recovered")
        ).all()
        assert len(events) == 1
    finally:
        db.close()


def test_stale_task_recovery_fails_when_max_retries_exhausted():
    """Verify recover_stale_tasks marks orphaned task as failed when max retries is reached."""
    db = SessionLocal()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=600)

    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Orphaned task with exhausted retries.",
        status="running",
        current_agent_stage="repairing",
        retry_count=3,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task.updated_at = stale_time
    db.commit()
    task_id = task.id
    db.close()

    runner = TaskRunner()
    recovered = runner.recover_stale_tasks(stale_threshold_seconds=300)
    assert task_id in recovered

    db = SessionLocal()
    try:
        updated = db.scalar(select(Task).where(Task.id == task_id))
        assert updated.status == "failed"
        assert updated.current_agent_stage == "failed"
        assert "max retries" in updated.error_summary.lower()

        events = db.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.event_type == "stale_task_failed")
        ).all()
        assert len(events) == 1
    finally:
        db.close()


# ==============================================================================
# 6. EXECUTION TIMEOUT ENFORCEMENT
# ==============================================================================

def test_task_runner_execution_timeout_marks_failed():
    """Verify execution exceeding configured timeout marks task failed with timeout event."""
    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Timeout testing task.",
        status="queued",
        current_agent_stage="queued",
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    runner = TaskRunner(default_timeout=1)

    # Mock graph.invoke to simulate a hung step
    def slow_graph_invoke(*args, **kwargs):
        import time
        time.sleep(1.5)
        return {"status": "completed"}

    runner.graph.invoke = slow_graph_invoke
    runner.setup_task_workspace = MagicMock(return_value=WorkspaceTools(virtual_files={"a.py": "1"}))

    final_state = runner.run_task(task_id, timeout=1)
    assert final_state["status"] == "failed"
    assert "timed out" in final_state["error_summary"].lower()

    db = SessionLocal()
    try:
        updated = db.scalar(select(Task).where(Task.id == task_id))
        assert updated.status == "failed"
        assert updated.current_agent_stage == "failed"
        assert "timed out after 1 seconds" in updated.error_summary

        events = db.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.event_type == "task_timeout")
        ).all()
        assert len(events) == 1
    finally:
        db.close()


# ==============================================================================
# 7. TASK CANCELLATION API & WORKFLOW STOP
# ==============================================================================

def test_cancel_task_api_and_rejection_of_terminal_states():
    """Verify POST /tasks/{task_id}/cancel cancels task and rejects cancelling completed tasks."""
    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Cancellation API test.",
        status="running",
        current_agent_stage="editing",
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    # Cancel the running task
    res = client.post(f"/tasks/{task_id}/cancel")
    assert res.status_code == 200
    assert res.json()["task"]["status"] == "cancelled"

    # Attempting to cancel already cancelled task should fail with 400
    res_again = client.post(f"/tasks/{task_id}/cancel")
    assert res_again.status_code == 400
    assert "terminal status" in res_again.json()["detail"].lower()


# ==============================================================================
# 8. RETRY FLOW & REJECTION CONSTRAINTS
# ==============================================================================

def test_retry_task_flow_and_worker_notification():
    """Verify POST /tasks/{task_id}/retry increments count, re-queues, and notifies worker."""
    mock_worker = MagicMock(spec=TaskWorker)
    reset_task_worker_for_testing(mock_worker)

    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Retry flow test.",
        status="failed",
        current_agent_stage="failed",
        error_summary="Previous run failed",
        retry_count=1,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    res = client.post(f"/tasks/{task_id}/retry")
    assert res.status_code == 200
    data = res.json()
    assert data["task"]["status"] == "queued"
    assert data["task"]["retry_count"] == 2

    mock_worker.notify_new_task.assert_called_once_with(task_id)


# ==============================================================================
# 9. TRUTHFULNESS & FABRICATION PREVENTION
# ==============================================================================

def test_unverified_patch_never_claims_success():
    """
    CRITICAL INVARIANT:
    Never claim success when tests fail. Must transition to needs_human_review or failed.
    """
    mock_llm, mock_github, test_tools = make_mock_services(test_passes=False)

    db = SessionLocal()
    task = Task(
        repository_url="https://github.com/octocat/Hello-World",
        task_description="Fix bug with failing tests.",
        status="queued",
        current_agent_stage="queued",
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    runner = TaskRunner(
        llm_service=mock_llm,
        github_service=mock_github,
        default_max_repairs=1,
    )
    runner.setup_task_workspace = MagicMock(return_value=test_tools)

    worker = TaskWorker(task_runner=runner)
    worker.process_next_task(task_id=task_id)

    db = SessionLocal()
    try:
        updated = db.scalar(select(Task).where(Task.id == task_id))
        # Must NOT be completed
        assert updated.status in ("needs_human_review", "failed")
        assert updated.status != "completed"

        # Verification evidence must record failure truthfully
        runs = db.scalars(select(TestRun).where(TestRun.task_id == task_id)).all()
        assert any(r.passed is False for r in runs)
    finally:
        db.close()
