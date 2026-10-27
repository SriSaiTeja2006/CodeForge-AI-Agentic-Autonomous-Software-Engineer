import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.database import SessionLocal
from app.models.task import Task
from app.models.task_event import TaskEvent
from app.models.file_change import FileChange
from app.models.test_run import TestRun

client = TestClient(app)


def test_create_task_success():
    """Verify truthful task creation with initial queued state and creation event."""
    payload = {
        "repository_url": "https://github.com/octocat/Hello-World",
        "task_description": "Implement authentication middleware and update tests.",
        "acceptance_criteria": "All unit tests pass and auth header is verified.",
        "issue_number": 42,
    }
    response = client.post("/tasks", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["repository_url"] == payload["repository_url"]
    assert data["task_description"] == payload["task_description"]
    assert data["acceptance_criteria"] == payload["acceptance_criteria"]
    assert data["issue_number"] == 42
    assert data["status"] == "queued"
    assert data["current_agent_stage"] == "queued"
    assert data["retry_count"] == 0
    assert data["max_retries"] == 3

    # Verify initial task event was generated
    events_res = client.get(f"/tasks/{data['id']}/events")
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "task_created"
    assert events[0]["stage"] == "queued"


def test_create_task_invalid_input():
    """Verify input validation rules for invalid URLs and empty descriptions."""
    # Invalid repository URL
    res = client.post(
        "/tasks",
        json={"repository_url": "ftp://invalid-url.com", "task_description": "Some task"},
    )
    assert res.status_code == 422

    # Whitespace only description
    res = client.post(
        "/tasks",
        json={"repository_url": "https://github.com/octocat/Hello-World", "task_description": "   "},
    )
    assert res.status_code == 422

    # Missing repository_url
    res = client.post("/tasks", json={"task_description": "Valid description"})
    assert res.status_code == 422


def test_list_tasks_pagination():
    """Verify task history pagination structure and filtering."""
    # Create two tasks
    client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/repo-one",
            "task_description": "First task for pagination test",
        },
    )
    client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/repo-two",
            "task_description": "Second task for pagination test",
        },
    )

    res = client.get("/tasks?page=1&page_size=2")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) <= 2
    assert data["total"] >= 2


def test_get_task_details_and_not_found():
    """Verify retrieving existing task and 404 for missing task."""
    create_res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/detail-test",
            "task_description": "Task details inspection test",
        },
    )
    task_id = create_res.json()["id"]

    # Existing task
    res = client.get(f"/tasks/{task_id}")
    assert res.status_code == 200
    assert res.json()["id"] == task_id

    # Non-existent task
    missing_res = client.get("/tasks/99999999")
    assert missing_res.status_code == 404
    assert "not found" in missing_res.json()["detail"].lower()


def test_task_subresources_endpoints():
    """Verify events, file changes, and test runs endpoints including 404 for missing task."""
    create_res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/subresources-test",
            "task_description": "Subresources validation test",
        },
    )
    task_id = create_res.json()["id"]

    # Seed one file change and one test run directly in database for verification
    with SessionLocal() as db:
        change = FileChange(
            task_id=task_id,
            relative_file_path="src/utils.py",
            diff_text="+ def new_helper(): pass",
            change_summary="Added new_helper function",
        )
        test = TestRun(
            task_id=task_id,
            command="pytest tests/",
            exit_code=0,
            passed=True,
            stdout="1 passed",
        )
        db.add_all([change, test])
        db.commit()

    # Query events
    events_res = client.get(f"/tasks/{task_id}/events")
    assert events_res.status_code == 200
    assert len(events_res.json()) >= 1

    # Query changes
    changes_res = client.get(f"/tasks/{task_id}/changes")
    assert changes_res.status_code == 200
    changes = changes_res.json()
    assert len(changes) == 1
    assert changes[0]["relative_file_path"] == "src/utils.py"

    # Query tests
    tests_res = client.get(f"/tasks/{task_id}/tests")
    assert tests_res.status_code == 200
    tests = tests_res.json()
    assert len(tests) == 1
    assert tests[0]["passed"] is True

    # 404 for missing task subresources
    assert client.get("/tasks/99999999/events").status_code == 404
    assert client.get("/tasks/99999999/changes").status_code == 404
    assert client.get("/tasks/99999999/tests").status_code == 404


def test_retry_task_permitted_flow():
    """Verify permitted retry transitions status to queued and increments retry count."""
    create_res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/retry-test",
            "task_description": "Retry permitted test case",
        },
    )
    task_id = create_res.json()["id"]

    # Mark as failed directly in database
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.id == task_id))
        task.status = "failed"
        task.error_summary = "Build failed on step 3"
        db.commit()

    # Request retry
    retry_res = client.post(f"/tasks/{task_id}/retry")
    assert retry_res.status_code == 200
    data = retry_res.json()
    assert "successfully queued for retry" in data["message"]
    assert data["task"]["status"] == "queued"
    assert data["task"]["retry_count"] == 1
    assert data["task"]["error_summary"] is None

    # Verify event logged
    events_res = client.get(f"/tasks/{task_id}/events")
    event_types = [e["event_type"] for e in events_res.json()]
    assert "retry_requested" in event_types


def test_retry_task_rejects_running_state():
    """Verify retry is rejected with HTTP 409 Conflict when task is actively running."""
    create_res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/running-retry-test",
            "task_description": "Reject retry when running test case",
        },
    )
    task_id = create_res.json()["id"]

    # Set status to running/investigating
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.id == task_id))
        task.status = "investigating"
        db.commit()

    retry_res = client.post(f"/tasks/{task_id}/retry")
    assert retry_res.status_code == 409
    assert "currently running" in retry_res.json()["detail"].lower()


def test_retry_task_rejects_exceeded_limit():
    """Verify retry is rejected with HTTP 400 Bad Request when max retries exceeded."""
    create_res = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/owner/limit-test",
            "task_description": "Exceeded retry limit test case",
        },
    )
    task_id = create_res.json()["id"]

    # Set retry_count to max_retries (3)
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.id == task_id))
        task.status = "failed"
        task.retry_count = 3
        task.max_retries = 3
        db.commit()

    retry_res = client.post(f"/tasks/{task_id}/retry")
    assert retry_res.status_code == 400
    assert "maximum retry limit" in retry_res.json()["detail"].lower()


def test_retry_non_existent_task():
    """Verify 404 for retry on non-existent task."""
    res = client.post("/tasks/99999999/retry")
    assert res.status_code == 404
