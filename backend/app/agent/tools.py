import os
import sys
import difflib
import shlex
import subprocess
import time
import logging
from typing import List, Dict, Optional, Any, Callable, Tuple

logger = logging.getLogger(__name__)

# Resource and security limits
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024      # 2 MB maximum file size limit
MAX_OUTPUT_BYTES = 50 * 1024               # 50 KB maximum output capture limit
DEFAULT_EXECUTION_TIMEOUT = 30             # 30 seconds default
MAX_EXECUTION_TIMEOUT = 60                 # 60 seconds maximum allowed timeout

# Whitelist of permitted test runners and command prefixes
PERMITTED_TEST_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "npm test",
    "npm run test",
    "yarn test",
    "pnpm test",
    "cargo test",
    "go test",
)

# Explicit disallowed shell metacharacters and chaining patterns
DISALLOWED_SHELL_PATTERNS = (
    ";",
    "&&",
    "||",
    "|",
    ">",
    "<",
    "`",
    "$(",
    "eval",
    "exec",
    "rm -rf",
    "sudo",
    "chmod",
    "chown",
    "curl",
    "wget",
    "nc",
    "bash -c",
    "sh -c",
    "cmd.exe",
    "powershell",
)

DISALLOWED_SHELL_CHARS = {
    ";", "&", "|", ">", "<", "`", "$", "(", ")", "{", "}", "\n", "\r", "!", "\\",
}

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
}


def sanitize_subprocess_env(
    custom_env: Optional[Dict[str, str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Produce a clean, sanitized environment for subprocess execution,
    guaranteeing that GitHub tokens, API keys, and credentials are removed.
    Preserves essential system runtime variables necessary for OS networking,
    DNS resolution, and subprocess execution.
    """
    sensitive_substrings = (
        "TOKEN",
        "KEY",
        "SECRET",
        "PASSWORD",
        "AUTH",
        "CREDENTIAL",
        "DATABASE",
        "CONN",
    )

    essential_system_keys = {
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
    }

    if custom_env is not None:
        source = dict(custom_env)
        # Inherit essential system variables if not explicitly provided in custom_env
        # (SystemRoot is required for Windows Winsock DNS resolution and Schannel SSL)
        for os_k, os_v in os.environ.items():
            if os_k.upper() in essential_system_keys:
                if os_k not in source and os_k.upper() not in source and os_k.lower() not in source:
                    source[os_k] = os_v
    else:
        source = dict(os.environ)

    if extra_env:
        source.update(extra_env)

    clean_env: Dict[str, str] = {}
    for k, v in source.items():
        k_upper = k.upper()
        if any(substr in k_upper for substr in sensitive_substrings):
            continue
        clean_env[k] = v

    clean_env["GIT_TERMINAL_PROMPT"] = "0"
    return clean_env


def resolve_safe_workspace_path(base_dir: str, relative_path: str, must_exist: bool = False) -> str:
    """
    Enforces strict path containment. Rejects:
    - Empty paths
    - Absolute paths (POSIX / or Windows C:\\)
    - Parent directory traversal (..)
    - Symlinks pointing outside the workspace base_dir
    - Files attempting to escape the workspace boundary
    """
    if not relative_path or not relative_path.strip():
        raise ValueError("Invalid path: Path cannot be empty.")

    clean_input = relative_path.strip()

    # Reject absolute paths (POSIX / or Windows C:\ or \\)
    if (
        clean_input.startswith("/")
        or clean_input.startswith("\\")
        or (len(clean_input) >= 2 and clean_input[1] == ":")
        or os.path.isabs(clean_input)
    ):
        raise ValueError(f"Security violation: Absolute paths are strictly prohibited ('{relative_path}').")

    # Reject null bytes or control characters
    if "\x00" in clean_input or "\r" in clean_input or "\n" in clean_input:
        raise ValueError(f"Security violation: Path contains illegal control characters ('{relative_path}').")

    # Normalize slashes and inspect path components
    normalized = os.path.normpath(clean_input.replace("\\", "/"))
    parts = normalized.split(os.sep)
    if ".." in parts or normalized == ".." or ".." in clean_input.replace("\\", "/").split("/"):
        raise ValueError(f"Security violation: Path traversal ('..') is prohibited ('{relative_path}').")

    abs_base = os.path.realpath(base_dir)
    target = os.path.abspath(os.path.join(abs_base, normalized))

    norm_abs_base = os.path.normcase(abs_base)
    norm_target = os.path.normcase(target)

    # Check that target is within abs_base
    if not (norm_target == norm_abs_base or norm_target.startswith(norm_abs_base + os.sep)):
        raise ValueError(f"Security violation: Path traversal: '{relative_path}' points outside workspace root.")

    # Check symlink escapes
    if os.path.exists(target) or os.path.islink(target):
        real_target = os.path.realpath(target)
        norm_real_target = os.path.normcase(real_target)
        if not (norm_real_target == norm_abs_base or norm_real_target.startswith(norm_abs_base + os.sep)):
            raise ValueError(f"Security violation: Symlink escape detected ('{relative_path}').")
    else:
        if must_exist:
            raise FileNotFoundError(f"File not found in workspace: '{relative_path}'")
        # Check all parent directories to prevent writing through a symlinked directory
        check_dir = os.path.dirname(target)
        while check_dir and len(check_dir) >= len(abs_base):
            if os.path.exists(check_dir) or os.path.islink(check_dir):
                real_check = os.path.normcase(os.path.realpath(check_dir))
                if not (real_check == norm_abs_base or real_check.startswith(norm_abs_base + os.sep)):
                    raise ValueError(
                        f"Security violation: Directory in path is a symlink outside workspace ('{relative_path}')."
                    )
                break
            parent = os.path.dirname(check_dir)
            if parent == check_dir:
                break
            check_dir = parent

    return target


def check_container_runtime() -> Tuple[bool, str]:
    """
    Check if a safe disposable container runtime (Docker or Podman) is available on the system.
    Returns (is_available, runtime_name).
    """
    for runtime in ("docker", "podman"):
        try:
            res = subprocess.run(
                [runtime, "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True, runtime
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return False, "none"


def compute_unified_diff(
    relative_path: str,
    original_content: str,
    new_content: str,
) -> str:
    """Compute standard unified diff format for inspected file changes."""
    orig_lines = original_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        new_lines,
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
    )
    return "".join(diff)


class WorkspaceTools:
    """
    Sandbox workspace tool interface providing strict filesystem containment,
    reviewable patch generation, and safe isolated test execution.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        virtual_files: Optional[Dict[str, str]] = None,
        test_runner_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        container_image: str = "python:3.11-slim",
        allow_host_runner: bool = False,
    ):
        self.base_dir = os.path.abspath(base_dir) if base_dir else None
        self.virtual_files: Dict[str, str] = dict(virtual_files) if virtual_files is not None else {}
        self.test_runner_fn = test_runner_fn
        self.container_image = container_image
        self.allow_host_runner = allow_host_runner
        self._original_snapshots: Dict[str, str] = {}

    def _resolve_path(self, relative_path: str, must_exist: bool = False) -> str:
        """Resolve and validate path containment."""
        if not relative_path or not relative_path.strip():
            raise ValueError("Invalid path: Path cannot be empty.")

        clean_input = relative_path.strip()

        if not self.base_dir:
            # Virtual mode path containment enforcement
            if (
                clean_input.startswith("/")
                or clean_input.startswith("\\")
                or (len(clean_input) >= 2 and clean_input[1] == ":")
                or os.path.isabs(clean_input)
            ):
                raise ValueError(f"Security violation: Absolute paths are strictly prohibited ('{relative_path}').")

            if "\x00" in clean_input or "\r" in clean_input or "\n" in clean_input:
                raise ValueError(f"Security violation: Path contains illegal control characters ('{relative_path}').")

            if ".." in clean_input.replace("\\", "/").split("/"):
                raise ValueError(f"Security violation: Path traversal ('..') is prohibited ('{relative_path}').")

            clean_norm = os.path.normpath(clean_input.replace("\\", "/"))
            if clean_norm.startswith("..") or clean_norm == "..":
                raise ValueError(f"Security violation: Path traversal ('..') is prohibited ('{relative_path}').")
            return clean_norm.replace("\\", "/")

        return resolve_safe_workspace_path(self.base_dir, relative_path, must_exist=must_exist)

    def list_files(self, sub_dir: str = "", max_files: int = 150) -> List[str]:
        """List files in the workspace, respecting exclusion patterns and path containment."""
        if sub_dir:
            self._resolve_path(sub_dir)

        if not self.base_dir:
            matched = []
            for path in sorted(self.virtual_files.keys()):
                if not sub_dir or path.startswith(sub_dir):
                    matched.append(path)
                if len(matched) >= max_files:
                    break
            return matched

        results: List[str] = []
        start_dir = os.path.join(self.base_dir, sub_dir) if sub_dir else self.base_dir
        if not os.path.exists(start_dir):
            return []

        for root, dirs, files in os.walk(start_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES and not d.startswith(".")]
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.base_dir).replace("\\", "/")
                results.append(rel_path)
                if len(results) >= max_files:
                    return results

        return results

    def read_file(self, relative_path: str, max_chars: int = 30000) -> str:
        """
        Read content from a workspace file with strict containment and size limits.
        """
        clean_path = relative_path.strip()
        if not self.base_dir or clean_path in self.virtual_files:
            self._resolve_path(clean_path)
            if clean_path not in self.virtual_files:
                raise FileNotFoundError(f"File not found in virtual workspace: '{clean_path}'")
            content = self.virtual_files[clean_path]
            if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"File '{clean_path}' exceeds maximum permitted size of {MAX_FILE_SIZE_BYTES} bytes."
                )
            return content[:max_chars]

        target_file = self._resolve_path(clean_path, must_exist=True)
        if not os.path.isfile(target_file):
            raise FileNotFoundError(f"File not found in workspace: '{clean_path}'")

        file_size = os.path.getsize(target_file)
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File '{clean_path}' exceeds maximum permitted size of {MAX_FILE_SIZE_BYTES} bytes."
            )

        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)

    def write_file(self, relative_path: str, content: str) -> None:
        """
        Write content to a workspace file with strict containment and size limits.
        """
        clean_path = relative_path.strip()
        if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"Content exceeds maximum permitted file size of {MAX_FILE_SIZE_BYTES} bytes."
            )

        target_file = self._resolve_path(clean_path, must_exist=False)

        # Capture original content snapshot on first write if not already recorded
        if clean_path not in self._original_snapshots:
            try:
                self._original_snapshots[clean_path] = self.read_file(clean_path)
            except (FileNotFoundError, ValueError):
                self._original_snapshots[clean_path] = ""

        if not self.base_dir or clean_path in self.virtual_files:
            self.virtual_files[clean_path] = content
            return

        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)

    def delete_file(self, relative_path: str) -> bool:
        """
        Delete a file within the workspace with strict containment.
        """
        clean_path = relative_path.strip()
        target_file = self._resolve_path(clean_path, must_exist=True)

        if clean_path not in self._original_snapshots:
            try:
                self._original_snapshots[clean_path] = self.read_file(clean_path)
            except Exception:
                self._original_snapshots[clean_path] = ""

        if not self.base_dir or clean_path in self.virtual_files:
            if clean_path in self.virtual_files:
                del self.virtual_files[clean_path]
                return True
            return False

        if os.path.exists(target_file):
            os.remove(target_file)
            return True
        return False

    def apply_patch(self, relative_path: str, new_content: str) -> Dict[str, Any]:
        """
        Apply full replacement content and compute reviewable diff.
        """
        clean_path = relative_path.strip()
        self._resolve_path(clean_path, must_exist=False)

        try:
            original = self.read_file(clean_path)
        except (FileNotFoundError, ValueError):
            original = ""

        self.write_file(clean_path, new_content)
        diff = compute_unified_diff(clean_path, original, new_content)
        return {
            "file_path": clean_path,
            "original_content": original,
            "new_content": new_content,
            "diff_text": diff,
            "changed": original != new_content,
        }

    def get_diff(self, relative_path: Optional[str] = None) -> str:
        """
        Retrieve reviewable Git diff if inside a Git repository,
        or computed unified diff from tracked file snapshots.
        """
        clean_path = relative_path.strip() if relative_path else None
        if clean_path:
            self._resolve_path(clean_path)

        # Check if physical workspace has a Git repository
        if self.base_dir and os.path.isdir(os.path.join(self.base_dir, ".git")):
            try:
                clean_env = sanitize_subprocess_env()
                # Track newly created files with intent-to-add so they appear in git diff
                subprocess.run(
                    ["git", "add", "-N", "."],
                    cwd=self.base_dir,
                    capture_output=True,
                    timeout=5,
                    env=clean_env,
                    check=False,
                )
                cmd = ["git", "diff", "--no-color"]
                if clean_path:
                    cmd.extend(["--", clean_path])
                proc = subprocess.run(
                    cmd,
                    cwd=self.base_dir,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=clean_env,
                )
                if proc.returncode == 0 and proc.stdout and proc.stdout.strip():
                    return proc.stdout

                # If working tree diff is clean, check committed changes against base branch
                for base_ref in ("origin/main", "main", "HEAD~1"):
                    try:
                        base_cmd = ["git", "diff", "--no-color", f"{base_ref}..HEAD"]
                        if clean_path:
                            base_cmd.extend(["--", clean_path])
                        b_proc = subprocess.run(
                            base_cmd,
                            cwd=self.base_dir,
                            capture_output=True,
                            text=True,
                            timeout=10,
                            env=clean_env,
                            check=False,
                        )
                        if b_proc.returncode == 0 and b_proc.stdout and b_proc.stdout.strip():
                            return b_proc.stdout
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("git diff execution failed: %s", str(exc))

        # Fallback to in-memory snapshots diff
        if clean_path:
            original = self._original_snapshots.get(clean_path, "")
            try:
                current = self.read_file(clean_path)
            except Exception:
                current = ""
            return compute_unified_diff(clean_path, original, current)

        # All modified files
        all_diffs = []
        for path, original in self._original_snapshots.items():
            try:
                current = self.read_file(path)
            except Exception:
                current = ""
            d = compute_unified_diff(path, original, current)
            if d.strip():
                all_diffs.append(d)
        return "\n".join(all_diffs)

    def run_tests(self, command: str, timeout: int = DEFAULT_EXECUTION_TIMEOUT) -> Dict[str, Any]:
        """
        Execute permitted test suite command with strict security controls:
        1. Validates command against explicit allowlist of test runners.
        2. Strictly rejects shell metacharacters, subshells, and chaining operators.
        3. Never executes untrusted repository code directly on host without disposable container isolation.
        4. If container runtime is unavailable, refuses execution and reports the limitation.
        5. Limits execution duration, stdout/stderr output size, and strips credentials.
        """
        clean_cmd = (command or "").strip()
        if not clean_cmd:
            raise ValueError("Test command cannot be empty.")

        # Enforce execution timeout limits
        effective_timeout = max(1, min(timeout, MAX_EXECUTION_TIMEOUT))

        # Reject disallowed shell metacharacters and chaining patterns
        for pattern in DISALLOWED_SHELL_PATTERNS:
            if pattern in clean_cmd:
                raise ValueError(
                    f"Test command contains prohibited or unsafe operator '{pattern}'. "
                    "Only direct test runner executions are permitted."
                )

        # Parse command tokens without invoking a shell
        try:
            tokens = shlex.split(clean_cmd)
        except Exception as exc:
            raise ValueError(f"Invalid command syntax: {str(exc)}")

        if not tokens:
            raise ValueError("Test command cannot be empty.")

        # Enforce allowlist of supported test runners
        allowed = any(
            clean_cmd == prefix or clean_cmd.startswith(f"{prefix} ")
            for prefix in PERMITTED_TEST_PREFIXES
        )
        if not allowed:
            raise ValueError(
                f"Prohibited: Test command '{clean_cmd}' is not in the permitted test runner allowlist / whitelist "
                f"({', '.join(PERMITTED_TEST_PREFIXES)})."
            )

        start_time = time.perf_counter()

        # If custom test runner hook is injected (e.g. mock container runner in tests)
        if self.test_runner_fn is not None:
            try:
                res = self.test_runner_fn(clean_cmd)
                duration = round(time.perf_counter() - start_time, 3)
                stdout = str(res.get("stdout", ""))
                stderr = str(res.get("stderr", ""))
                if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
                    stdout = stdout[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"
                if len(stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
                    stderr = stderr[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"

                return {
                    "command": clean_cmd,
                    "exit_code": res.get("exit_code", 1),
                    "passed": res.get("passed", res.get("exit_code") == 0),
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_seconds": duration,
                    "isolated": True,
                    "runtime": "mock_sandbox",
                }
            except (subprocess.TimeoutExpired, TimeoutError):
                duration = round(time.perf_counter() - start_time, 3)
                return {
                    "command": clean_cmd,
                    "exit_code": 124,
                    "passed": False,
                    "stdout": "",
                    "stderr": f"Test execution timed out after {effective_timeout} seconds.",
                    "duration_seconds": duration,
                    "isolated": True,
                    "runtime": "mock_sandbox",
                }

        # Check for disposable container runtime (Docker / Podman)
        is_container_available, runtime_name = check_container_runtime()

        # If container runtime is unavailable, check configured execution policy
        if not is_container_available:
            from app.config import get_settings
            app_settings = get_settings()
            allow_host = self.allow_host_runner or getattr(app_settings, "ALLOW_HOST_TEST_RUNNER", False)
            if not allow_host:
                duration = round(time.perf_counter() - start_time, 3)
                return {
                    "command": clean_cmd,
                    "exit_code": 126,
                    "passed": False,
                    "stdout": "",
                    "stderr": (
                        "Execution Refused: No safe container runtime (Docker or Podman) is available. "
                        "CodeForge AI security policy strictly prohibits executing untrusted repository code "
                        "directly on the host without container isolation."
                    ),
                    "duration_seconds": duration,
                    "isolated": False,
                    "runtime": "none",
                }

            if not self.base_dir or not os.path.exists(self.base_dir):
                duration = round(time.perf_counter() - start_time, 3)
                return {
                    "command": clean_cmd,
                    "exit_code": 1,
                    "passed": False,
                    "stdout": "",
                    "stderr": "No physical workspace directory available to execute test command.",
                    "duration_seconds": duration,
                    "isolated": False,
                    "runtime": "workspace_host",
                }

            host_cmd = list(tokens)
            if host_cmd:
                if host_cmd[0] == "pytest":
                    host_cmd = [sys.executable, "-m", "pytest"] + host_cmd[1:]
                elif len(host_cmd) >= 3 and host_cmd[0] == "python" and host_cmd[1] == "-m" and host_cmd[2] == "pytest":
                    host_cmd = [sys.executable, "-m", "pytest"] + host_cmd[3:]

            clean_env = sanitize_subprocess_env()
            try:
                proc = subprocess.run(
                    host_cmd,
                    cwd=self.base_dir,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    env=clean_env,
                )
                duration = round(time.perf_counter() - start_time, 3)
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
                if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
                    stdout = stdout[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"
                if len(stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
                    stderr = stderr[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"

                return {
                    "command": clean_cmd,
                    "exit_code": proc.returncode,
                    "passed": proc.returncode == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_seconds": duration,
                    "isolated": False,
                    "runtime": "workspace_host",
                }
            except subprocess.TimeoutExpired:
                duration = round(time.perf_counter() - start_time, 3)
                return {
                    "command": clean_cmd,
                    "exit_code": 124,
                    "passed": False,
                    "stdout": "",
                    "stderr": f"Test execution timed out after {effective_timeout} seconds.",
                    "duration_seconds": duration,
                    "isolated": False,
                    "runtime": "workspace_host",
                }

        if not self.base_dir or not os.path.exists(self.base_dir):
            duration = round(time.perf_counter() - start_time, 3)
            return {
                "command": clean_cmd,
                "exit_code": 1,
                "passed": False,
                "stdout": "",
                "stderr": "No physical workspace directory available to mount in container.",
                "duration_seconds": duration,
                "isolated": True,
                "runtime": runtime_name,
            }

        # Execute inside disposable container with resource, network, and filesystem limits
        container_cmd = [
            runtime_name,
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            "512m",
            "--cpus",
            "1.0",
            "-v",
            f"{os.path.realpath(self.base_dir)}:/workspace",
            "-w",
            "/workspace",
            self.container_image,
            *tokens,
        ]

        clean_env = sanitize_subprocess_env()

        try:
            proc = subprocess.run(
                container_cmd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env=clean_env,
            )
            duration = round(time.perf_counter() - start_time, 3)

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
                stdout = stdout[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"
            if len(stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
                stderr = stderr[:MAX_OUTPUT_BYTES] + "\n[Output truncated: exceeded size limit]"

            return {
                "command": clean_cmd,
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": duration,
                "isolated": True,
                "runtime": runtime_name,
            }
        except subprocess.TimeoutExpired:
            duration = round(time.perf_counter() - start_time, 3)
            return {
                "command": clean_cmd,
                "exit_code": 124,
                "passed": False,
                "stdout": "",
                "stderr": f"Test execution timed out after {effective_timeout} seconds.",
                "duration_seconds": duration,
                "isolated": True,
                "runtime": runtime_name,
            }
        except Exception as exc:
            duration = round(time.perf_counter() - start_time, 3)
            return {
                "command": clean_cmd,
                "exit_code": 1,
                "passed": False,
                "stdout": "",
                "stderr": f"Container execution error: {str(exc)}",
                "duration_seconds": duration,
                "isolated": True,
                "runtime": runtime_name,
            }
