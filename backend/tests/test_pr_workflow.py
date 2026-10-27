import os
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models.task import Task
from app.models.task_event import TaskEvent
from app.models.file_change import FileChange
from app.models.test_run import TestRun
from app.schemas.github import ValidateRepositoryResponse, CreatePullRequestRequest
from app.services.pr_service import PullRequestService, get_pr_service

client = TestClient(app)


@pytest.fixture
def test_db():
    """Provide a database session for test setup and assertions."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_sample_task(
    db,
    status="completed",
    stage="verifying",
    description="Fix arithmetic subtraction in calculator module.",
    repo="https://github.com/octocat/Hello-World",
):
    """Helper to create a persisted task with associated events, file changes, and test runs."""
    task = Task(
        repository_url=repo,
        task_description=description,
        acceptance_criteria="Unit tests pass without errors.",
        issue_number=42,
        status=status,
        current_agent_stage=stage,
        retry_count=0,
        max_retries=3,
    )
    db.add(task)
    db.flush()

    # Initial creation event
    db.add(
        TaskEvent(
            task_id=task.id,
            stage="queued",
            event_type="task_created",
            message="Task initialized",
        )
    )

    db.commit()
    db.refresh(task)
    return task


# ==============================================================================
# 1. PR PREVIEW & READINESS TESTS
# ==============================================================================

def test_pr_preview_for_completed_verified_task(test_db):
    """Verify GET /tasks/{id}/pr prepares a complete summary, test evidence, and clean safety scan."""
    task = create_sample_task(test_db, status="completed", stage="completed")

    # Add verified file change
    fc = FileChange(
        task_id=task.id,
        relative_file_path="calculator/calc.py",
        diff_text="--- a/calculator/calc.py\n+++ b/calculator/calc.py\n@@ -1,2 +1,2 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b\n",
        change_summary="Fixed operator from minus to plus in add function",
    )
    test_db.add(fc)

    # Add passing test run
    tr = TestRun(
        task_id=task.id,
        command="pytest tests/test_calc.py",
        exit_code=0,
        passed=True,
        stdout="1 passed in 0.05s",
        stderr="",
    )
    test_db.add(tr)
    test_db.commit()

    res = client.get(f"/tasks/{task.id}/pr")
    assert res.status_code == 200
    data = res.json()

    assert data["task_id"] == task.id
    assert data["head_branch"] == f"codeforge/task-{task.id}"
    assert data["base_branch"] == "main"
    assert "fix(agent):" in data["suggested_title"]
    assert "calculator/calc.py" in data["suggested_body"]
    assert "pytest tests/test_calc.py" in data["suggested_body"]
    assert data["file_changes_count"] == 1
    assert data["test_runs_count"] == 1
    assert data["tests_passed"] is True
    assert data["safety_passed"] is True
    assert len(data["safety_violations"]) == 0
    assert data["is_ready"] is True
    assert data["can_create_pr"] is True
    assert data["is_approved"] is False
    assert data["existing_pr"] is None


def test_pr_preview_blocks_unverified_failing_task(test_db):
    """Verify GET /tasks/{id}/pr reports not ready when agent failed tests."""
    task = create_sample_task(test_db, status="failed", stage="failed")

    # Add failing test run
    tr = TestRun(
        task_id=task.id,
        command="pytest tests/test_calc.py",
        exit_code=1,
        passed=False,
        stdout="FAILED",
        stderr="AssertionError: expected 3 got -1",
    )
    test_db.add(tr)
    test_db.commit()

    res = client.get(f"/tasks/{task.id}/pr")
    assert res.status_code == 200
    data = res.json()

    assert data["is_ready"] is False
    assert data["can_create_pr"] is False
    assert any("failed" in issue.lower() for issue in data["readiness_issues"])


# ==============================================================================
# 2. DIFF SAFETY & SECRET SCANNING TESTS
# ==============================================================================

def test_pr_creation_rejects_diff_containing_secrets(test_db):
    """Verify secret scanner detects sensitive tokens/keys in diffs and blocks PR creation."""
    task = create_sample_task(test_db, status="completed", stage="completed")

    # Add file change with simulated Groq API key and OpenAI secret key
    dummy_groq = "g" + "sk_" + "12345678901234567890abcdef"
    dummy_openai = "s" + "k-" + "12345678901234567890abcdef"
    fc = FileChange(
        task_id=task.id,
        relative_file_path="config/keys.py",
        diff_text=f"--- a/config/keys.py\n+++ b/config/keys.py\n@@ -0,0 +1,2 @@\n+GROQ_KEY = '{dummy_groq}'\n+OPENAI_KEY = '{dummy_openai}'\n",
        change_summary="Accidentally committed provider keys",
    )
    test_db.add(fc)
    test_db.commit()

    # Check preview detects violations
    preview_res = client.get(f"/tasks/{task.id}/pr")
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert preview_data["safety_passed"] is False
    assert len(preview_data["safety_violations"]) >= 2
    assert any("Groq API key" in v for v in preview_data["safety_violations"])

    # Attempting to create PR must be rejected with HTTP 422
    create_res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
    assert create_res.status_code == 422
    assert "secrets or disallowed files detected" in create_res.json()["detail"].lower()


def test_pr_creation_rejects_disallowed_file_names(test_db):
    """Verify secret scanner rejects patches that modify .env or private key files."""
    task = create_sample_task(test_db, status="completed", stage="completed")

    fc = FileChange(
        task_id=task.id,
        relative_file_path=".env.production",
        diff_text="--- /dev/null\n+++ b/.env.production\n@@ -0,0 +1 @@\n+DATABASE_URL=postgres://...\n",
        change_summary="Added production credentials file",
    )
    test_db.add(fc)
    test_db.commit()

    res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
    assert res.status_code == 422
    assert "disallowed sensitive file" in res.json()["detail"].lower()


# ==============================================================================
# 3. HUMAN APPROVAL GATE TESTS
# ==============================================================================

def test_pr_creation_requires_explicit_human_approval(test_db):
    """Verify POST /tasks/{id}/pr/create strictly rejects requests without approved=True."""
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="safe_code.py",
        diff_text="--- a/safe_code.py\n+++ b/safe_code.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n",
        change_summary="Safe constant change",
    )
    test_db.add(fc)
    test_db.commit()

    # Missing or false approved flag must be rejected
    res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": False})
    assert res.status_code == 400
    assert "explicit human approval is required" in res.json()["detail"].lower()


def test_explicit_approval_endpoint(test_db):
    """Verify POST /tasks/{id}/pr/approve records approval event."""
    task = create_sample_task(test_db, status="completed", stage="completed")

    res = client.post(
        f"/tasks/{task.id}/pr/approve",
        json={"approved": True, "comment": "Reviewed by lead engineer. Looks solid."},
    )
    assert res.status_code == 200
    assert res.json()["approved"] is True

    # Verify event stored in database
    events = test_db.scalars(
        select(TaskEvent).where(TaskEvent.task_id == task.id).where(TaskEvent.event_type == "pr_approved")
    ).all()
    assert len(events) == 1
    assert "pr_approved" == events[0].event_type
    assert events[0].structured_metadata["comment"] == "Reviewed by lead engineer. Looks solid."


# ==============================================================================
# 4. AUTHORIZATION CHECKS & REAL PR CREATION WITH MOCKS
# ==============================================================================

def test_pr_creation_rejects_lacking_push_permissions(test_db):
    """Verify user without push/write permissions cannot open a pull request (HTTP 403)."""
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="lib.py",
        diff_text="--- a/lib.py\n+++ b/lib.py\n@@ -1 +1 @@\n-x\n+y\n",
        change_summary="Valid edit",
    )
    test_db.add(fc)
    test_db.commit()

    pr_service = get_pr_service()
    with patch.object(pr_service.github_service, "validate_repository") as mock_validate:
        # Mock repository validation returning can_push=False
        mock_validate.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=False,  # NO WRITE PERMISSION
            can_pull=True,
            description="Test repo",
        )

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 403
        assert "lacks push permissions" in res.json()["detail"].lower()


def test_pr_creation_end_to_end_success(test_db):
    """Verify successful end-to-end pull request creation, event persistence, and non-fabrication."""
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="calculator/calc.py",
        diff_text="--- a/calculator/calc.py\n+++ b/calculator/calc.py\n@@ -1 +1 @@\n-x\n+y\n",
        change_summary="Fixed calculation bug",
    )
    tr = TestRun(
        task_id=task.id,
        command="pytest",
        exit_code=0,
        passed=True,
        stdout="All tests pass",
        stderr="",
    )
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    # Mock PyGithub repo and PR objects
    mock_gh_repo = MagicMock()
    mock_gh_repo.default_branch = "main"

    mock_pr = MagicMock()
    mock_pr.number = 420
    mock_pr.html_url = "https://github.com/octocat/Hello-World/pull/420"
    mock_pr.title = f"fix(agent): [Task #{task.id}] verified changes"
    mock_pr.body = "Detailed summary..."
    mock_pr.state = "open"
    mock_pr.draft = False
    mock_pr.created_at = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    mock_gh_repo.create_pull.return_value = mock_pr

    with patch.object(pr_service.github_service, "validate_repository") as mock_validate, \
         patch.object(pr_service, "_get_client") as mock_get_client:

        mock_validate.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )

        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_gh_repo
        mock_get_client.return_value = mock_gh

        res = client.post(
            f"/tasks/{task.id}/pr/create",
            json={
                "approved": True,
                "title": f"fix: [Task #{task.id}] verified calculator fix",
                "body": "PR markdown description",
                "draft": False,
            },
        )

        assert res.status_code == 201
        data = res.json()
        assert data["pr_number"] == 420
        assert data["pr_url"] == "https://github.com/octocat/Hello-World/pull/420"
        assert data["head_branch"].startswith(f"codeforge/task-{task.id}")
        assert data["base_branch"] == "main"
        assert data["state"] == "open"
        assert data["is_draft"] is False

        # Verify actual PR metadata recorded in PostgreSQL
        events = test_db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .where(TaskEvent.event_type == "pr_created")
        ).all()
        assert len(events) == 1
        meta = events[0].structured_metadata
        assert meta["pr_number"] == 420
        assert meta["pr_url"] == "https://github.com/octocat/Hello-World/pull/420"
        assert meta["head_branch"].startswith(f"codeforge/task-{task.id}")

        # Verify task stage updated
        test_db.refresh(task)
        assert task.current_agent_stage in ("completed", "pr_created")


def test_pr_creation_github_api_failure_handled_without_fabrication(test_db):
    """Verify PyGithub API errors (e.g. rate limit, network failure) return real errors and never fabricate success."""
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="calc.py",
        diff_text="--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-a\n+b\n",
        change_summary="Clean edit",
    )
    test_db.add(fc)
    test_db.commit()

    pr_service = get_pr_service()
    with patch.object(pr_service.github_service, "validate_repository") as mock_validate, \
         patch.object(pr_service, "create_pull_request") as mock_create_pr:

        mock_validate.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )

        from fastapi import HTTPException
        mock_create_pr.side_effect = HTTPException(status_code=429, detail="GitHub API rate limit exceeded.")

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()

        # Ensure NO pr_created event was recorded
        created_events = test_db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .where(TaskEvent.event_type == "pr_created")
        ).all()
        assert len(created_events) == 0

        # Failure event was recorded
        fail_events = test_db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .where(TaskEvent.event_type == "pr_creation_failed")
        ).all()
        assert len(fail_events) == 1


# ==============================================================================
# 5. PHASE 7 SECURITY & AUTHORIZATION INVARIANT TESTS
# ==============================================================================

def test_denied_or_missing_approval_prevents_github_write(test_db):
    """
    Verify Phase 7 Requirements 2 and 9:
    - Denied or missing approval strictly prevents branch push and GitHub PR creation.
    - Neither git push nor GitHub API write operations are invoked.
    """
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="calculator/calc.py",
        diff_text="--- a/calculator/calc.py\n+++ b/calculator/calc.py\n@@ -1 +1 @@\n-x\n+y\n",
        change_summary="Fixed operator",
    )
    test_db.add(fc)
    test_db.commit()

    with patch("subprocess.run") as mock_subproc, \
         patch.object(get_pr_service(), "create_pull_request") as mock_create_pr:

        # 1. approved=False
        res_false = client.post(f"/tasks/{task.id}/pr/create", json={"approved": False})
        assert res_false.status_code == 400
        assert "explicit human approval is required" in res_false.json()["detail"].lower()
        mock_subproc.assert_not_called()
        mock_create_pr.assert_not_called()

        # 2. unapproved flag omitted (Pydantic validation rejects or defaults False)
        res_empty = client.post(f"/tasks/{task.id}/pr/create", json={})
        assert res_empty.status_code in (400, 422)
        mock_subproc.assert_not_called()
        mock_create_pr.assert_not_called()


def test_never_merge_automatically_invariant():
    """
    Verify Phase 7 Requirement 3:
    CodeForge AI never automatically merges pull requests.
    Inspect PR service interface to ensure no merge method exists and maintainer review is mandated.
    """
    pr_service = get_pr_service()
    assert not hasattr(pr_service, "merge_pull_request")
    assert not hasattr(pr_service, "auto_merge")
    assert not hasattr(pr_service, "merge")


def test_authorization_boundary_forbidden_push_prevents_branch_push(test_db):
    """
    Verify Phase 7 Requirement 8:
    When token lacks push authorization, branch push is aborted and HTTP 403 returned.
    """
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="main.py",
        diff_text="--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-0\n+1\n",
        change_summary="Edit",
    )
    test_db.add(fc)
    test_db.commit()

    pr_service = get_pr_service()
    with patch.object(pr_service.github_service, "validate_repository") as mock_validate, \
         patch("subprocess.run") as mock_subproc:

        mock_validate.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=False,  # Denied write access
            can_pull=True,
        )

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 403
        assert "lacks push permissions" in res.json()["detail"].lower()
        mock_subproc.assert_not_called()


def test_credentials_sanitization_in_errors_and_events(test_db):
    """
    Verify Phase 7 Requirement 4:
    GitHub tokens and Groq API keys are redacted from error responses and persisted events.
    """
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="main.py",
        diff_text="--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-0\n+1\n",
        change_summary="Edit",
    )
    test_db.add(fc)
    test_db.commit()

    pr_service = get_pr_service()
    secret_token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-super-secret-token-12345")
    original_token = pr_service.token
    pr_service.token = secret_token

    try:
        with patch.object(pr_service.github_service, "validate_repository") as mock_validate, \
             patch.object(pr_service, "create_pull_request") as mock_create_pr:

            mock_validate.return_value = ValidateRepositoryResponse(
                valid=True,
                owner="octocat",
                repo="Hello-World",
                full_name="octocat/Hello-World",
                normalized_url="https://github.com/octocat/Hello-World",
                default_branch="main",
                is_private=False,
                can_push=True,
                can_pull=True,
            )

            # Simulate GitHub error that includes the secret token in the exception string
            mock_create_pr.side_effect = RuntimeError(f"Connection error to https://{secret_token}@api.github.com")

            res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
            assert res.status_code in (500, 502)
            response_text = res.text
            assert secret_token not in response_text
            assert "[REDACTED_TOKEN]" in response_text

            # Verify database event does not leak secret
            events = test_db.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task.id)
                .where(TaskEvent.event_type == "pr_creation_failed")
            ).all()
            assert len(events) == 1
            assert secret_token not in events[0].message
            assert "[REDACTED_TOKEN]" in events[0].message
    finally:
        pr_service.token = original_token


# ==============================================================================
# 5. MOCKED GITHUB WORKFLOW END-TO-END SPECIFIC TESTS (Requirement 6)
# ==============================================================================

def test_mocked_github_successful_publication_and_pr_creation(test_db):
    """
    Test successful publication and PR creation with mocked GitHub API.
    Verifies task record persistence: pr_number, pr_url, source_branch, target_branch, status=completed.
    """
    task = create_sample_task(test_db, status="completed", stage="verifying", description="Implement calculator module")
    fc = FileChange(
        task_id=task.id,
        relative_file_path="calculator.py",
        diff_text="--- /dev/null\n+++ b/calculator.py\n@@ -0,0 +1,6 @@\n+def add(a, b): return a + b\n+def subtract(a, b): return a - b\n",
        change_summary="Add calculator module",
    )
    tr = TestRun(
        task_id=task.id,
        command="pytest",
        exit_code=0,
        passed=True,
        stdout="2 passed in 0.01s",
        stderr="",
    )
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    mock_gh_repo = MagicMock()
    mock_gh_repo.default_branch = "main"

    mock_pr = MagicMock()
    mock_pr.number = 77
    mock_pr.html_url = "https://github.com/octocat/Hello-World/pull/77"
    mock_pr.title = f"fix(agent): [Task #{task.id}] Resolves #{task.issue_number}"
    mock_pr.body = "Verified changes and tests"
    mock_pr.state = "open"
    mock_pr.draft = False
    mock_pr.created_at = datetime.now(timezone.utc)
    mock_gh_repo.create_pull.return_value = mock_pr
    mock_gh_repo.get_pulls.return_value = []

    with patch.object(pr_service.github_service, "validate_repository") as mock_val, \
         patch.object(pr_service, "_get_client") as mock_client, \
         patch("subprocess.run") as mock_subproc:

        mock_val.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_gh_repo
        mock_client.return_value = mock_gh

        mock_subproc.return_value = MagicMock(returncode=0, stdout="Everything up-to-date", stderr="")

        pr_ref = pr_service.publish_and_create_pull_request(
            db=test_db,
            task_id=task.id,
            approved=True,
        )

        assert pr_ref.pr_number == 77
        assert pr_ref.pr_url == "https://github.com/octocat/Hello-World/pull/77"

        test_db.refresh(task)
        assert task.status == "completed"
        assert task.pr_number == 77
        assert task.pr_url == "https://github.com/octocat/Hello-World/pull/77"
        assert task.source_branch.startswith(f"codeforge/task-{task.id}")
        assert task.target_branch == "main"


def test_mocked_github_insufficient_permissions(test_db):
    """
    Test that insufficient repository permissions (can_push=False) halts PR creation
    with HTTP 403 Forbidden.
    """
    task = create_sample_task(test_db, status="completed", stage="verifying")
    fc = FileChange(task_id=task.id, relative_file_path="calculator.py", diff_text="+code\n", change_summary="Add code")
    tr = TestRun(task_id=task.id, command="pytest", exit_code=0, passed=True)
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    with patch.object(pr_service.github_service, "validate_repository") as mock_val:
        mock_val.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=False,  # Insufficient push permissions
            can_pull=True,
        )

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 403
        assert "push permissions" in res.json()["detail"].lower()


def test_mocked_github_push_failure_sets_publish_failed(test_db):
    """
    Test that a git push error sets task status to 'publish_failed' and records
    a publish_failed event without creating a PR on GitHub.
    """
    task = create_sample_task(test_db, status="needs_human_review", stage="needs_human_review")
    fc = FileChange(task_id=task.id, relative_file_path="calculator.py", diff_text="+code\n", change_summary="Add code")
    tr = TestRun(task_id=task.id, command="pytest", exit_code=0, passed=True)
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    with patch.object(pr_service.github_service, "validate_repository") as mock_val, \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("subprocess.run") as mock_subproc:

        mock_val.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )

        # Mock checkout and add to succeed, but push to fail
        def subproc_side_effect(cmd, *args, **kwargs):
            if "push" in cmd:
                return MagicMock(returncode=128, stdout="", stderr="fatal: remote rejected (pre-receive hook declined)")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = subproc_side_effect

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 502

        test_db.refresh(task)
        assert task.status == "publish_failed"
        assert task.current_agent_stage == "publish_failed"
        assert "pre-receive hook declined" in task.error_summary


def test_mocked_github_existing_pr_reuse(test_db):
    """
    Test that an existing PR for the head branch is detected and returned without duplicate PR error.
    """
    task = create_sample_task(test_db, status="completed", stage="completed")
    fc = FileChange(task_id=task.id, relative_file_path="calculator.py", diff_text="+code\n", change_summary="Add code")
    tr = TestRun(task_id=task.id, command="pytest", exit_code=0, passed=True)
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    mock_existing_pr = MagicMock()
    mock_existing_pr.number = 99
    mock_existing_pr.html_url = "https://github.com/octocat/Hello-World/pull/99"
    mock_existing_pr.title = "Existing PR title"
    mock_existing_pr.body = "Existing PR body"
    mock_existing_pr.state = "open"
    mock_existing_pr.draft = False
    mock_existing_pr.created_at = datetime.now(timezone.utc)

    mock_gh_repo = MagicMock()
    mock_gh_repo.default_branch = "main"
    mock_gh_repo.get_pulls.return_value = [mock_existing_pr]

    with patch.object(pr_service.github_service, "validate_repository") as mock_val, \
         patch.object(pr_service, "_get_client") as mock_client, \
         patch("subprocess.run") as mock_subproc:

        mock_val.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_gh_repo
        mock_client.return_value = mock_gh
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 201
        data = res.json()
        assert data["pr_number"] == 99
        assert data["pr_url"] == "https://github.com/octocat/Hello-World/pull/99"


def test_mocked_github_verification_failure_blocks_pr(test_db):
    """
    Test that a task ending in 'verification_failed' blocks PR creation and explains the reason.
    """
    task = create_sample_task(test_db, status="verification_failed", stage="verification_failed")
    fc = FileChange(task_id=task.id, relative_file_path="calculator.py", diff_text="+code\n", change_summary="Add code")
    tr = TestRun(task_id=task.id, command="pytest", exit_code=1, passed=False, stderr="AssertionError: 2 != 3")
    test_db.add(fc)
    test_db.add(tr)
    test_db.commit()

    pr_service = get_pr_service()

    with patch.object(pr_service.github_service, "validate_repository") as mock_val:
        mock_val.return_value = ValidateRepositoryResponse(
            valid=True,
            owner="octocat",
            repo="Hello-World",
            full_name="octocat/Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
            default_branch="main",
            is_private=False,
            can_push=True,
            can_pull=True,
        )

        res = client.post(f"/tasks/{task.id}/pr/create", json={"approved": True})
        assert res.status_code == 400
        assert "verification failed" in res.json()["detail"].lower()


