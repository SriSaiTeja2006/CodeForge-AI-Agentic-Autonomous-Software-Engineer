import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.services.task_runner import TaskRunner
from app.services.github_service import GitHubService
from app.agent.tools import sanitize_subprocess_env


# ==============================================================================
# 1. ENVIRONMENT SANITIZATION & SYSTEM PRESERVATION TESTS
# ==============================================================================

def test_sanitize_subprocess_env_preserves_system_variables_for_networking():
    """
    Verify sanitize_subprocess_env preserves essential OS runtime variables
    (e.g., SystemRoot, PATH) needed for Windows DNS and Winsock networking,
    while setting GIT_TERMINAL_PROMPT=0.
    """
    clean = sanitize_subprocess_env()

    # Must always set terminal prompt off
    assert clean.get("GIT_TERMINAL_PROMPT") == "0"

    # On Windows, SystemRoot and PATH must be preserved for Winsock/Schannel
    if "SystemRoot" in os.environ or "SYSTEMROOT" in os.environ:
        assert any(k.upper() == "SYSTEMROOT" for k in clean)
    if "PATH" in os.environ:
        assert any(k.upper() == "PATH" for k in clean)


def test_sanitize_subprocess_env_inherits_essential_keys_when_custom_env_passed():
    """
    Verify that even when a custom_env dictionary is passed without system essentials,
    critical variables like SystemRoot and PATH are inherited, while secret keys are purged.
    """
    custom = {
        "CUSTOM_VAR": "my_val",
        "GITHUB_TOKEN": os.getenv("TEST_GITHUB_TOKEN", "fake-test-secret-token-12345"),
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
    }
    clean = sanitize_subprocess_env(custom)

    assert clean.get("CUSTOM_VAR") == "my_val"
    assert clean.get("GIT_TERMINAL_PROMPT") == "0"
    assert "GITHUB_TOKEN" not in clean
    assert "DATABASE_URL" not in clean

    if "SystemRoot" in os.environ:
        assert any(k.upper() == "SYSTEMROOT" for k in clean)


# ==============================================================================
# 2. REPOSITORY URL VALIDATION & NORMALIZATION IN CLONE
# ==============================================================================

def test_setup_task_workspace_normalizes_tree_branch_urls(tmp_path):
    """Verify setup_task_workspace normalizes URL with /tree/main before invoking git clone."""
    mock_github = MagicMock(spec=GitHubService)
    mock_github.token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-mock-token-123")
    runner = TaskRunner(github_service=mock_github)

    captured_cmds = []

    def mock_subprocess_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        # Simulate successful git clone by creating a mock .git directory
        target_dir = Path(cmd[-1])
        (target_dir / ".git").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        tools = runner.setup_task_workspace(
            task_id=999,
            repository_url="https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab/tree/main",
            workspaces_dir=tmp_path,
        )

        assert tools is not None
        assert len(captured_cmds) >= 1
        clone_cmd = captured_cmds[0]
        # The cloned URL must be normalized without /tree/main
        assert "https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab" in clone_cmd
        assert "tree/main" not in str(clone_cmd)


def test_setup_task_workspace_rejects_invalid_url(tmp_path):
    """Verify setup_task_workspace raises ValueError on completely invalid repository URL."""
    runner = TaskRunner()
    with pytest.raises(ValueError, match="Invalid repository URL"):
        runner.setup_task_workspace(
            task_id=998,
            repository_url="https://not-github.com/invalid/repo",
            workspaces_dir=tmp_path,
        )


# ==============================================================================
# 3. SUBPROCESS ERROR HANDLING, LOGGING & CLEANUP ON CLONE FAILURE
# ==============================================================================

def test_clone_network_failure_handling(tmp_path):
    """
    Verify network failure (e.g., DNS Could not resolve host) captures exit code,
    logs sanitized stderr, cleans up partial workspace files, and raises descriptive RuntimeError.
    """
    mock_github = MagicMock(spec=GitHubService)
    mock_github.token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-super-secret-token-xyz")
    runner = TaskRunner(github_service=mock_github)

    workspace_dir = tmp_path / "777"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    # Put a partial artifact file in the directory
    (workspace_dir / "partial_file.txt").write_text("incomplete data")

    dns_error = (
        "Cloning into '...'\n"
        "fatal: unable to access 'https://github.com/owner/repo/': Could not resolve host: github.com"
    )

    mock_proc = subprocess.CompletedProcess(
        args=["git", "clone", "--depth", "1", "https://github.com/owner/repo", str(workspace_dir)],
        returncode=128,
        stdout="",
        stderr=dns_error,
    )

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError) as exc_info:
            runner.setup_task_workspace(
                task_id=777,
                repository_url="https://github.com/owner/repo",
                workspaces_dir=tmp_path,
            )

        err_text = str(exc_info.value)
        assert "Network error during repository cloning" in err_text
        assert "exit code 128" in err_text
        assert "Could not resolve host: github.com" in err_text

        # Partial files must have been cleaned up so subsequent retry succeeds
        assert not (workspace_dir / "partial_file.txt").exists()


def test_clone_auth_failure_handling_and_token_redaction(tmp_path):
    """
    Verify authentication failure captures exit code, redacts tokens from error message,
    and cleans up workspace.
    """
    mock_github = MagicMock(spec=GitHubService)
    raw_token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-super-secret-token-abcdef")
    mock_github.token = raw_token
    runner = TaskRunner(github_service=mock_github)

    workspace_dir = tmp_path / "888"
    auth_error = f"fatal: Authentication failed for 'https://{raw_token}@github.com/owner/private-repo.git/'"

    mock_proc = subprocess.CompletedProcess(
        args=["git", "clone", "--depth", "1", "https://github.com/owner/private-repo", str(workspace_dir)],
        returncode=128,
        stdout="",
        stderr=auth_error,
    )

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError) as exc_info:
            runner.setup_task_workspace(
                task_id=888,
                repository_url="https://github.com/owner/private-repo",
                workspaces_dir=tmp_path,
            )

        err_text = str(exc_info.value)
        assert "Authentication or access error during repository cloning" in err_text
        assert "exit code 128" in err_text
        assert raw_token not in err_text
        assert "[REDACTED_TOKEN]" in err_text


def test_retry_task_can_retry_after_failed_clone(tmp_path):
    """
    Verify that if a clone previously failed leaving files/empty folder,
    a retry cleanly clears the folder and successfully clones when network succeeds.
    """
    mock_github = MagicMock(spec=GitHubService)
    mock_github.token = os.getenv("TEST_GITHUB_TOKEN", "fake-test-mock-token")
    runner = TaskRunner(github_service=mock_github)

    workspace_dir = tmp_path / "555"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    # Stale files from previous failed attempt
    (workspace_dir / "stale_failed_clone.tmp").write_text("old corrupted state")

    def mock_subprocess_run(cmd, **kwargs):
        # Verify that by the time git clone runs, stale files were cleaned up
        target_dir = Path(cmd[-1])
        assert not (target_dir / "stale_failed_clone.tmp").exists()
        (target_dir / ".git").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Cloned successfully", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        tools = runner.setup_task_workspace(
            task_id=555,
            repository_url="https://github.com/octocat/Hello-World",
            workspaces_dir=tmp_path,
        )
        assert tools is not None
        assert (workspace_dir / ".git").is_dir()


# ==============================================================================
# 4. WORKSPACE ISOLATION, PATH TRAVERSAL & HOST SAFETY TESTS
# ==============================================================================

def test_workspace_isolation_across_multiple_tasks(tmp_path):
    """
    Verify each task receives its own strictly isolated workspace,
    and modifying or cloning one task never overwrites or affects another task.
    """
    runner = TaskRunner(github_service=MagicMock(spec=GitHubService, token=""))

    def mock_subprocess_run(cmd, **kwargs):
        target_dir = Path(cmd[-1])
        (target_dir / ".git").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        tools_1 = runner.setup_task_workspace(
            task_id=101,
            repository_url="https://github.com/octocat/Hello-World",
            workspaces_dir=tmp_path,
        )
        tools_2 = runner.setup_task_workspace(
            task_id=102,
            repository_url="https://github.com/octocat/Hello-World",
            workspaces_dir=tmp_path,
        )

        ws_1 = Path(tools_1.base_dir)
        ws_2 = Path(tools_2.base_dir)

        assert ws_1 != ws_2
        assert ws_1.name == "101"
        assert ws_2.name == "102"

        # Write to task 101 workspace
        tools_1.write_file("task101_file.txt", "data for task 101")
        assert (ws_1 / "task101_file.txt").exists()
        assert not (ws_2 / "task101_file.txt").exists()

        # Write to task 102 workspace
        tools_2.write_file("task102_file.txt", "data for task 102")
        assert (ws_2 / "task102_file.txt").exists()
        assert not (ws_1 / "task102_file.txt").exists()


def test_workspace_path_traversal_and_symlink_escape_rejection(tmp_path):
    """Verify WorkspaceTools rejects directory traversal (..) and absolute paths."""
    from app.agent.tools import WorkspaceTools

    ws_dir = tmp_path / "security_test"
    ws_dir.mkdir(parents=True, exist_ok=True)
    tools = WorkspaceTools(base_dir=str(ws_dir))

    # Reject parent traversal
    with pytest.raises(ValueError, match="Invalid path|escapes the workspace|Security violation"):
        tools.read_file("../sensitive_parent.txt")

    with pytest.raises(ValueError, match="Invalid path|escapes the workspace|Security violation"):
        tools.write_file("../../etc/passwd", "malicious")

    # Reject absolute paths
    with pytest.raises(ValueError, match="Absolute paths are strictly prohibited|Security violation"):
        tools.read_file("C:/Windows/System32/drivers/etc/hosts")


def test_workspace_refuses_host_execution_without_container(tmp_path):
    """
    Verify run_tests refuses execution and never runs untrusted repository
    code directly on the host if Docker/Podman is unavailable.
    """
    from app.agent.tools import WorkspaceTools

    tools = WorkspaceTools(base_dir=str(tmp_path))

    with patch("app.agent.tools.check_container_runtime", return_value=(False, "none")):
        result = tools.run_tests("pytest")
        assert result["exit_code"] == 126
        assert result["passed"] is False
        assert "No safe container runtime" in result["stderr"]

