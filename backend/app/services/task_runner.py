import logging
import threading
import time
import shutil
import base64
import subprocess
import concurrent.futures
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Set

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import SessionLocal
from app.models.task import Task, ACTIVE_RUNNING_STATUSES
from app.models.task_event import TaskEvent
from app.services.llm_service import LLMService, sanitize_groq_api_key
from app.services.github_service import (
    GitHubService,
    parse_and_normalize_github_url,
    sanitize_github_token,
)
from app.services.pr_service import PullRequestService, get_pr_service
from app.config import get_settings
from app.agent.state import AgentState
from app.agent.tools import WorkspaceTools, sanitize_subprocess_env
from app.agent.graph import create_codeforge_graph

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Execution engine that orchestrates the CodeForge AI LangGraph workflow for tasks.
    Manages database transitions, error handling, cancellation, timeout protection,
    and concurrent execution guards.
    """

    def __init__(
        self,
        db_factory: Optional[Callable[[], Session]] = None,
        llm_service: Optional[LLMService] = None,
        github_service: Optional[GitHubService] = None,
        pr_service: Optional[PullRequestService] = None,
        default_max_repairs: int = 2,
        default_timeout: Optional[int] = None,
    ):
        settings = get_settings()
        self.db_factory = db_factory or SessionLocal
        self.llm_service = llm_service or LLMService()
        self.github_service = github_service or GitHubService()
        self.pr_service = pr_service or PullRequestService(github_service=self.github_service)
        self.default_max_repairs = default_max_repairs
        self.default_timeout = default_timeout if default_timeout is not None else getattr(settings, "TASK_TIMEOUT", 300)
        self.graph = create_codeforge_graph()
        self._active_task_ids: Set[int] = set()
        self._lock = threading.Lock()

    def setup_task_workspace(
        self,
        task_id: int,
        repository_url: str,
        workspaces_dir: Optional[Path] = None,
        branch_name: Optional[str] = None,
    ) -> WorkspaceTools:
        """
        Create one isolated workspace per task under backend/workspaces/{task_id}.
        Clones only validated GitHub repositories, configures a task-specific working branch,
        and ensures GitHub credentials are kept out of repository configuration and subprocess environment.
        """
        # Validate repository URL
        try:
            owner, repo, normalized_url = parse_and_normalize_github_url(repository_url)
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            raise ValueError(f"Invalid repository URL '{repository_url}': {detail}")

        # Isolated directory under backend/workspaces/{task_id}
        if workspaces_dir is not None:
            workspaces_root = Path(workspaces_dir).resolve()
        else:
            backend_dir = Path(__file__).resolve().parent.parent.parent
            workspaces_root = backend_dir / "workspaces"

        task_workspace_dir = (workspaces_root / str(task_id)).resolve()
        task_workspace_dir.mkdir(parents=True, exist_ok=True)

        target_branch = branch_name or f"codeforge/task-{task_id}"
        git_dir = task_workspace_dir / ".git"

        clean_env = sanitize_subprocess_env()

        # Clone repository if not already cloned
        if not git_dir.is_dir():
            # Clean up any leftover or partial files in workspace before clone so that
            # git clone does not fail with 'already exists and is not an empty directory'
            for item in task_workspace_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    try:
                        item.unlink()
                    except OSError:
                        pass

            clone_cmd = ["git", "clone", "--depth", "1", "-c", "credential.helper="]
            token = getattr(self.github_service, "token", None)
            basic_auth = None
            if token and token.strip():
                # GitHub HTTPS git endpoint authenticates personal access tokens via Basic Auth:
                # Authorization: Basic base64("x-access-token:<token>")
                # Use in-memory extraheader so credentials are NEVER written to .git/config
                clean_tok = token.strip()
                basic_auth = base64.b64encode(f"x-access-token:{clean_tok}".encode()).decode()
                clone_cmd.extend(["-c", f"http.extraheader=AUTHORIZATION: basic {basic_auth}"])
            clone_cmd.extend([normalized_url, str(task_workspace_dir)])

            try:
                proc = subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=clean_env,
                )
                if proc.returncode != 0:
                    raw_stderr = proc.stderr.strip()
                    raw_stdout = proc.stdout.strip()
                    err_msg = sanitize_github_token(raw_stderr or "Unknown git error", token)
                    out_msg = sanitize_github_token(raw_stdout, token)
                    if basic_auth:
                        err_msg = err_msg.replace(basic_auth, "[REDACTED_AUTH]")
                        out_msg = out_msg.replace(basic_auth, "[REDACTED_AUTH]")
                    logger.error(
                        "git clone failed for task %s (exit code %d). stdout: %s | stderr: %s",
                        task_id,
                        proc.returncode,
                        out_msg,
                        err_msg,
                    )

                    # Clean up partial directory contents on failure so subsequent retries start clean
                    for item in task_workspace_dir.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            try:
                                item.unlink()
                            except OSError:
                                pass

                    # Provide an actionable, categorized error message
                    if "could not resolve host" in err_msg.lower() or "failed to connect" in err_msg.lower():
                        raise RuntimeError(
                            f"Network error during repository cloning (exit code {proc.returncode}): {err_msg}"
                        )
                    elif (
                        "repository not found" in err_msg.lower()
                        or "access denied" in err_msg.lower()
                        or "authentication failed" in err_msg.lower()
                    ):
                        raise RuntimeError(
                            f"Authentication or access error during repository cloning (exit code {proc.returncode}): {err_msg}"
                        )
                    else:
                        # Clean up persisted http.extraheader from local repo config so credentials are not on disk
                        subprocess.run(
                            ["git", "config", "--unset-all", "http.extraheader"],
                            cwd=str(task_workspace_dir),
                            capture_output=True,
                            check=False,
                            env=clean_env,
                        )
            except FileNotFoundError:
                logger.warning("git is not installed on host. Running in fallback directory workspace.")
                return WorkspaceTools(base_dir=str(task_workspace_dir), allow_host_runner=True)

        # Check out or create task-specific working branch
        if git_dir.is_dir():
            try:
                # Reset local working tree to clean default branch so task starts with clean diff
                subprocess.run(
                    ["git", "checkout", "-f", "main"],
                    cwd=str(task_workspace_dir),
                    capture_output=True,
                    timeout=15,
                    env=clean_env,
                    check=False,
                )
                subprocess.run(
                    ["git", "clean", "-fdx"],
                    cwd=str(task_workspace_dir),
                    capture_output=True,
                    timeout=15,
                    env=clean_env,
                    check=False,
                )
                subprocess.run(
                    ["git", "checkout", "-B", target_branch],
                    cwd=str(task_workspace_dir),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=clean_env,
                    check=False,
                )
            except Exception as exc:
                logger.warning("Failed to checkout task branch %s: %s", target_branch, str(exc))

        return WorkspaceTools(base_dir=str(task_workspace_dir), allow_host_runner=True)

    def run_task(
        self,
        task_id: int,
        workspace_tools: Optional[WorkspaceTools] = None,
        max_repairs: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> AgentState:
        """
        Execute the autonomous software engineering LangGraph for a specific task.
        Prevents concurrent duplicate executions, monitors timeouts, persists all
        lifecycle stages, and handles unhandled worker exceptions.
        """
        # Concurrency guard: reject if this task is already actively executing in this worker
        with self._lock:
            if task_id in self._active_task_ids:
                raise RuntimeError(
                    f"Task {task_id} is already actively running. Concurrent duplicate execution prevented."
                )
            self._active_task_ids.add(task_id)

        db = self.db_factory()
        effective_timeout = timeout or self.default_timeout

        try:
            task = db.scalar(select(Task).where(Task.id == task_id))
            if not task:
                raise ValueError(f"Task with ID {task_id} not found in database.")

            if task.status == "cancelled":
                logger.info("Task %s is marked cancelled; skipping execution.", task_id)
                return AgentState(
                    task_id=task.id,
                    status="cancelled",
                    current_stage="cancelled",
                    is_cancelled=True,
                )

            # Mark task running
            task.status = "running"
            task.current_agent_stage = "investigating"
            task.error_summary = None

            # Parse repository coordinates safely
            try:
                owner, repo, _ = parse_and_normalize_github_url(task.repository_url)
            except Exception:
                owner, repo = "unknown", "unknown"

            # Record initial execution event
            start_event = TaskEvent(
                task_id=task.id,
                stage="running",
                event_type="workflow_started",
                message=f"Autonomous agent started investigation for {owner}/{repo}.",
                structured_metadata={
                    "repository": f"{owner}/{repo}",
                    "issue_number": task.issue_number,
                },
            )
            db.add(start_event)
            db.commit()

            # Fetch real GitHub issue details if associated with an issue number
            issue_title = None
            issue_body = None
            if task.issue_number and owner != "unknown" and repo != "unknown":
                try:
                    gh_issue = self.github_service.get_issue(owner, repo, task.issue_number)
                    issue_title = gh_issue.title
                    issue_body = gh_issue.body
                    issue_event = TaskEvent(
                        task_id=task.id,
                        stage="running",
                        event_type="issue_retrieved",
                        message=f"Retrieved GitHub issue #{task.issue_number}: {issue_title}",
                        structured_metadata={
                            "issue_number": task.issue_number,
                            "issue_title": issue_title,
                            "has_body": bool(issue_body),
                        },
                    )
                    db.add(issue_event)
                    db.commit()
                except Exception as exc:
                    logger.warning("Could not fetch issue #%s for task %s: %s", task.issue_number, task.id, str(exc))

            # Initialize typed graph state
            target_max_repairs = max_repairs if max_repairs is not None else self.default_max_repairs
            initial_state: AgentState = {
                "task_id": task.id,
                "repository_url": task.repository_url,
                "owner": owner,
                "repo": repo,
                "issue_number": task.issue_number,
                "issue_title": issue_title,
                "issue_body": issue_body,
                "task_description": task.task_description,
                "acceptance_criteria": task.acceptance_criteria,
                "required_files": [],
                "required_symbols": [],
                "status": "running",
                "current_stage": "investigating",
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "repair_count": 0,
                "max_repairs": target_max_repairs,
                "is_cancelled": False,
                "relevant_files": [],
                "proposed_changes": {},
                "applied_changes": {},
                "original_contents": {},
                "file_diffs": {},
                "verification_passed": False,
                "safety_checks_passed": False,
                "events": [],
            }

            # Configure execution context with workspace isolation
            if workspace_tools is not None:
                effective_tools = workspace_tools
            else:
                from app.services.pr_service import generate_task_branch_name
                desc_for_slug = issue_title or task.task_description
                task_branch = task.source_branch or generate_task_branch_name(task.id, desc_for_slug)
                task.source_branch = task_branch
                db.commit()
                effective_tools = self.setup_task_workspace(task.id, task.repository_url, branch_name=task_branch)

            config = {
                "configurable": {
                    "db": db,
                    "workspace_tools": effective_tools,
                    "llm_service": self.llm_service,
                    "github_service": self.github_service,
                    "pr_service": self.pr_service,
                    "timeout": effective_timeout,
                }
            }

            # Execute LangGraph with thread-pool timeout protection
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.graph.invoke, initial_state, config)
                try:
                    final_state = future.result(timeout=effective_timeout)
                    return final_state
                except concurrent.futures.TimeoutError:
                    initial_state["is_cancelled"] = True
                    error_message = f"Task execution timed out after {effective_timeout} seconds."
                    logger.error("Task %s timed out: %s", task_id, error_message)

                    task = db.scalar(select(Task).where(Task.id == task_id))
                    if task:
                        task.status = "failed"
                        task.current_agent_stage = "failed"
                        task.error_summary = error_message
                        timeout_event = TaskEvent(
                            task_id=task.id,
                            stage="failed",
                            event_type="task_timeout",
                            message=error_message,
                            structured_metadata={"timeout_seconds": effective_timeout},
                        )
                        db.add(timeout_event)
                        db.commit()

                    return AgentState(
                        task_id=task_id,
                        status="failed",
                        current_stage="failed",
                        error_summary=error_message,
                        verification_passed=False,
                    )

        except Exception as exc:
            db.rollback()
            error_message = sanitize_groq_api_key(str(exc))
            logger.error("TaskRunner encountered exception on task %s: %s", task_id, error_message)

            try:
                task = db.scalar(select(Task).where(Task.id == task_id))
                if task:
                    task.status = "failed"
                    task.current_agent_stage = "failed"
                    task.error_summary = error_message
                    err_event = TaskEvent(
                        task_id=task.id,
                        stage="failed",
                        event_type="unhandled_exception",
                        message=f"Agent execution encountered an unhandled error: {error_message}",
                    )
                    db.add(err_event)
                    db.commit()
            except Exception as db_exc:
                logger.error("Failed to persist error state for task %s: %s", task_id, str(db_exc))

            return AgentState(
                task_id=task_id,
                status="failed",
                current_stage="failed",
                error_summary=error_message,
                verification_passed=False,
            )
        finally:
            with self._lock:
                self._active_task_ids.discard(task_id)
            db.close()

    def cancel_task(self, task_id: int) -> bool:
        """
        Request cancellation of an active or queued task, recording cancellation event and setting status.
        """
        db = self.db_factory()
        try:
            task = db.scalar(select(Task).where(Task.id == task_id))
            if not task:
                return False

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
            return True
        except Exception as exc:
            db.rollback()
            logger.error("Failed to cancel task %s: %s", task_id, str(exc))
            return False
        finally:
            db.close()

    def recover_stale_tasks(self, stale_threshold_seconds: int = 300) -> List[int]:
        """
        Recover orphaned or stalled tasks left in running state due to worker crashes or timeouts.
        Re-queues tasks if retry limit is not reached; marks them as failed otherwise.
        """
        db = self.db_factory()
        recovered_ids: List[int] = []
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)
            stmt = (
                select(Task)
                .where(Task.status.in_(ACTIVE_RUNNING_STATUSES))
                .where(Task.updated_at < cutoff)
                .with_for_update()
            )
            stale_tasks = db.scalars(stmt).all()
            for task in stale_tasks:
                # Do not recover if actively running in this process
                with self._lock:
                    if task.id in self._active_task_ids:
                        continue

                recovered_ids.append(task.id)
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = "queued"
                    task.current_agent_stage = "queued"
                    task.error_summary = "Recovered stale running task following worker crash/timeout; re-queued."
                    event = TaskEvent(
                        task_id=task.id,
                        stage="queued",
                        event_type="stale_task_recovered",
                        message=(
                            f"Stale running task recovered after crash/timeout; automatically re-queued "
                            f"(attempt {task.retry_count}/{task.max_retries})."
                        ),
                        structured_metadata={"retry_count": task.retry_count, "max_retries": task.max_retries},
                    )
                    db.add(event)
                else:
                    task.status = "failed"
                    task.current_agent_stage = "failed"
                    task.error_summary = "Task timed out or worker crashed without completion (max retries reached)."
                    event = TaskEvent(
                        task_id=task.id,
                        stage="failed",
                        event_type="stale_task_failed",
                        message=f"Stale running task failed after crash/timeout; maximum retries ({task.max_retries}) exhausted.",
                        structured_metadata={"retry_count": task.retry_count, "max_retries": task.max_retries},
                    )
                    db.add(event)

            db.commit()
            return recovered_ids
        except Exception as exc:
            db.rollback()
            logger.error("Error during recover_stale_tasks: %s", str(exc))
            return []
        finally:
            db.close()


class TaskWorker:
    """
    Durable background worker for autonomous coding tasks.
    Pulls queued tasks from PostgreSQL using SELECT ... FOR UPDATE SKIP LOCKED,
    guaranteeing safe concurrency across multiple workers or threads without race conditions.
    Decoupled from HTTP requests and handles crashes, timeouts, and stale tasks.
    """

    def __init__(
        self,
        task_runner: Optional[TaskRunner] = None,
        db_factory: Optional[Callable[[], Session]] = None,
        poll_interval: float = 1.0,
        stale_timeout_seconds: int = 300,
    ):
        self.db_factory = db_factory or SessionLocal
        self.task_runner = task_runner or TaskRunner(db_factory=self.db_factory)
        self.poll_interval = poll_interval
        self.stale_timeout_seconds = stale_timeout_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._lock = threading.Lock()
        self._last_stale_check = 0.0

    def notify_new_task(self, task_id: Optional[int] = None) -> None:
        """Signal the worker that a new task was placed in the queue."""
        self._wake_event.set()

    def claim_next_task(self, task_id: Optional[int] = None) -> Optional[int]:
        """
        Atomically claim the next queued task from the database.
        Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent duplicate execution across workers.
        """
        db = self.db_factory()
        try:
            stmt = select(Task).where(Task.status == "queued")
            if task_id is not None:
                stmt = stmt.where(Task.id == task_id)
            else:
                stmt = stmt.order_by(Task.created_at.asc())
            stmt = stmt.with_for_update(skip_locked=True)

            task = db.scalar(stmt)
            if not task:
                return None

            claimed_id = task.id
            task.status = "running"
            task.current_agent_stage = "investigating"
            db.commit()
            return claimed_id
        except Exception as exc:
            db.rollback()
            logger.error("Error claiming next task: %s", str(exc))
            return None
        finally:
            db.close()

    def process_next_task(
        self,
        task_id: Optional[int] = None,
        workspace_tools: Optional[WorkspaceTools] = None,
    ) -> Optional[int]:
        """
        Claim and execute the next queued task synchronously.
        Returns the task_id if a task was processed, or None if the queue was empty.
        """
        claimed_id = self.claim_next_task(task_id=task_id)
        if claimed_id is None:
            return None

        logger.info("Worker claimed task %s for execution.", claimed_id)
        try:
            self.task_runner.run_task(claimed_id, workspace_tools=workspace_tools)
        except Exception as exc:
            logger.error("Worker encountered error executing task %s: %s", claimed_id, str(exc))
        return claimed_id

    def start(self) -> None:
        """Start the background worker thread for in-process execution."""
        with self._lock:
            if self._is_running:
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._is_running = True
            self._worker_thread = threading.Thread(
                target=self._worker_thread_entry,
                name="CodeForgeWorkerThread",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("Background task worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background worker thread gracefully."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            self._stop_event.set()
            self._wake_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            logger.info("Background task worker stopped.")

    def _worker_thread_entry(self) -> None:
        self.run_worker_loop()

    def run_worker_loop(self, max_tasks: Optional[int] = None) -> None:
        """
        Run the worker loop continuously until stopped.
        Handles task processing, periodic stale task sweeps, and wake events.
        """
        tasks_processed = 0
        logger.info("Worker loop running (poll_interval=%.1fs)...", self.poll_interval)

        # Initial sweep for stale tasks on worker startup
        try:
            recovered = self.task_runner.recover_stale_tasks(self.stale_timeout_seconds)
            if recovered:
                logger.info("Initial stale task sweep recovered tasks: %s", recovered)
        except Exception as exc:
            logger.error("Error during initial stale task recovery: %s", str(exc))

        self._last_stale_check = time.time()

        while not self._stop_event.is_set():
            # Periodic stale task recovery sweep (every 60 seconds)
            now = time.time()
            if now - self._last_stale_check >= 60.0:
                try:
                    self.task_runner.recover_stale_tasks(self.stale_timeout_seconds)
                except Exception as exc:
                    logger.error("Error during periodic stale task sweep: %s", str(exc))
                self._last_stale_check = now

            # Process next task if available
            processed_id = self.process_next_task()
            if processed_id is not None:
                tasks_processed += 1
                if max_tasks is not None and tasks_processed >= max_tasks:
                    break
                # Continue draining queue immediately
                continue

            # Queue empty: wait on wake event or poll interval timeout
            self._wake_event.wait(timeout=self.poll_interval)
            self._wake_event.clear()


# Global worker singletons
_global_task_runner: Optional[TaskRunner] = None
_global_task_worker: Optional[TaskWorker] = None


def get_task_runner() -> TaskRunner:
    """Return the global TaskRunner instance."""
    global _global_task_runner
    if _global_task_runner is None:
        _global_task_runner = TaskRunner()
    return _global_task_runner


def get_task_worker() -> TaskWorker:
    """Return the global TaskWorker instance."""
    global _global_task_worker
    if _global_task_worker is None:
        _global_task_worker = TaskWorker(task_runner=get_task_runner())
    return _global_task_worker


def reset_task_worker_for_testing(worker: Optional[TaskWorker] = None) -> None:
    """Reset worker singletons (used in test fixtures)."""
    global _global_task_worker, _global_task_runner
    if _global_task_worker:
        is_running = getattr(_global_task_worker, "_is_running", False)
        if is_running is True:
            try:
                _global_task_worker.stop()
            except Exception:
                pass
    _global_task_worker = worker
    if worker is not None:
        _global_task_runner = getattr(worker, "task_runner", None)
    else:
        _global_task_runner = None
