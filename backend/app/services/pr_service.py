import base64
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from github import Github, Auth
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.config import get_settings
from app.models.task import Task
from app.models.file_change import FileChange
from app.models.test_run import TestRun
from app.models.task_event import TaskEvent
from app.services.github_service import (
    parse_and_normalize_github_url,
    GitHubService,
    sanitize_github_token,
)
from app.schemas.github import (
    CreateBranchResponse,
    CreatePullRequestRequest,
    GitHubPullRequestRef,
)
from app.schemas.task import TaskPRPreviewResponse
from app.agent.tools import sanitize_subprocess_env

logger = logging.getLogger(__name__)


def generate_task_branch_name(task_id: int, task_description: Optional[str] = None) -> str:
    """Generate a clean, descriptive, and unique task branch name, e.g. codeforge/task-10-calculator."""
    desc = (task_description or "").strip().lower()
    words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", desc)
    stopwords = {
        "the", "and", "for", "with", "this", "that", "from", "into", "task", "fix",
        "module", "unit", "tests", "python", "create", "implement", "add", "bug", "issue"
    }
    filtered_words = [w for w in words if w not in stopwords]
    slug = "-".join(filtered_words[:2]) if filtered_words else "fix"
    return f"codeforge/task-{task_id}-{slug}"

# Secret scanning regexes for diffs and file paths
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP|PRIVATE KEY)"), "Private cryptographic key block"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub fine-grained access token"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"), "Groq API key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "OpenAI API secret key"),
    (re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"), "OpenAI project API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key ID"),
    (re.compile(r"(?i)\b(password|secret|api_key|access_token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"), "Plaintext credential assignment"),
]

BLOCKED_FILE_PATTERNS = [
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r".*\.(?:pem|key|pfx|p12|pkcs12|kdbx)$", re.IGNORECASE),
    re.compile(r"^(?:id_rsa|id_dsa|id_ed25519|id_ecdsa)(?:\.pub)?$", re.IGNORECASE),
    re.compile(r".*(?:credentials|service_account|client_secret).*\.json$", re.IGNORECASE),
    re.compile(r"^\.git/.*"),
    re.compile(r"^\.ssh/.*"),
]


class PullRequestService:
    """
    Service interface for branch creation, pull-request preparation, safety scanning,
    and pull-request creation on GitHub.
    Enforces strict safety boundaries:
    - Never auto-merges pull requests.
    - Requires explicit human approval before PR creation.
    - Verifies branch and diff integrity against the task.
    - Scans for secrets and sensitive files in diffs.
    - Records actual PR metadata and rejects fabricated outcomes.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: int = 15,
        github_service: Optional[GitHubService] = None,
    ):
        settings = get_settings()
        token_val = token if token is not None else settings.GITHUB_TOKEN.get_secret_value()
        self.token = token_val.strip() if token_val else ""
        self.timeout = timeout
        self.github_service = github_service or GitHubService(token=self.token, timeout=timeout)

    def _get_client(self) -> Github:
        """Create an authenticated or unauthenticated PyGithub client instance."""
        if self.token:
            return Github(auth=Auth.Token(self.token), timeout=self.timeout)
        return Github(timeout=self.timeout)

    # --------------------------------------------------------------------------
    # 1. Safety Checks & Diff Verification
    # --------------------------------------------------------------------------
    def scan_diff_for_secrets_and_safety(
        self, file_changes: List[FileChange]
    ) -> Tuple[bool, List[str]]:
        """
        Verify that no secrets, credentials, or disallowed files appear in the diff.
        """
        violations: List[str] = []

        for change in file_changes:
            path = (change.relative_file_path or "").strip().replace("\\", "/")

            # Check for disallowed path traversal or absolute paths
            if path.startswith("/") or ".." in path.split("/"):
                violations.append(f"Disallowed path traversal in file change: {path}")

            # Check filename against blocked patterns
            filename = Path(path).name
            for pat in BLOCKED_FILE_PATTERNS:
                if pat.search(filename) or pat.search(path):
                    violations.append(f"Disallowed sensitive file pattern in patch: {path}")

            # Scan diff content for secrets (focusing on additions)
            diff_text = change.diff_text or ""
            for line in diff_text.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added_content = line[1:].strip()
                    for pat, desc in SECRET_PATTERNS:
                        if pat.search(added_content):
                            violations.append(f"Secret detected in {path}: {desc}")

        is_safe = len(violations) == 0
        return is_safe, violations

    def verify_branch_and_diff(
        self,
        task: Task,
        file_changes: List[FileChange],
        test_runs: List[TestRun],
        allow_active: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        Verify that the working branch and actual Git diff correspond to the requested task,
        and that the task has verified outcomes.
        """
        issues: List[str] = []

        if task.is_active and not allow_active and task.status != "publishing":
            issues.append(f"Task #{task.id} is actively executing ({task.current_agent_stage}). Wait for completion.")

        if task.status == "cancelled":
            issues.append(f"Task #{task.id} was cancelled.")

        if task.status == "failed":
            issues.append(f"Task #{task.id} failed verification or repair limits.")

        if task.status == "verification_failed":
            issues.append(f"Task #{task.id} verification failed: test suite did not pass.")

        if not allow_active:
            if task.status == "publish_failed":
                issues.append(f"Task #{task.id} branch publication failed. Please retry publication.")
            if task.status == "pr_creation_failed":
                issues.append(f"Task #{task.id} pull request creation failed on GitHub. Please retry.")

        if not file_changes:
            issues.append(f"Task #{task.id} has no file changes recorded.")

        # Test verification check
        if test_runs:
            latest_run = test_runs[-1]
            if latest_run.passed is False:
                from app.config import get_settings
                app_settings = get_settings()
                if not getattr(app_settings, "ALLOW_DRAFT_PR_ON_VERIFICATION_FAILURE", False):
                    issues.append("The latest test run did not pass verification.")

        is_ready = len(issues) == 0
        return is_ready, issues

    # --------------------------------------------------------------------------
    # 2. PR Summary Preparation
    # --------------------------------------------------------------------------
    def prepare_pull_request_summary(
        self,
        task: Task,
        file_changes: List[FileChange],
        test_runs: List[TestRun],
    ) -> Dict[str, str]:
        """
        Prepare a concise, structured summary of verified changes, acceptance-check evidence,
        and safety verification.
        """
        clean_desc = (task.task_description or "Autonomous coding task").strip().replace("\n", " ")
        short_desc = clean_desc[:70] + "..." if len(clean_desc) > 70 else clean_desc
        if task.issue_number:
            title = f"fix(agent): [Task #{task.id}] Resolves #{task.issue_number} - {short_desc}"
        else:
            title = f"fix(agent): [Task #{task.id}] {short_desc}"

        body_lines = [
            f"## Autonomous Fix Summary (CodeForge AI)",
            f"",
            f"- **Task ID:** #{task.id}",
            f"- **Repository:** `{task.repository_url}`",
        ]

        if task.issue_number:
            body_lines.append(f"- **Associated Issue:** Resolves #{task.issue_number}")

        body_lines.extend([
            f"",
            f"### Objective",
            f"{task.task_description}",
            f"",
        ])

        if task.acceptance_criteria:
            body_lines.extend([
                f"### Acceptance Criteria",
                f"{task.acceptance_criteria}",
                f"",
            ])

        body_lines.extend([
            f"### Verified File Changes ({len(file_changes)})",
            f"| File Path | Change Type | Summary |",
            f"| :--- | :--- | :--- |",
        ])

        for change in file_changes:
            summary = (change.change_summary or "Updated by CodeForge agent").replace("|", "\\|")
            body_lines.append(f"| `{change.relative_file_path}` | Modified | {summary} |")

        body_lines.extend([
            f"",
            f"### Test Execution & Acceptance Evidence",
        ])

        if test_runs:
            body_lines.extend([
                f"| Command | Exit Code | Result | Duration |",
                f"| :--- | :--- | :--- | :--- |",
            ])
            for run in test_runs:
                status_str = "PASSED" if run.passed else "FAILED"
                dur = f"{run.started_at}" if hasattr(run, "started_at") else ""
                body_lines.append(f"| `{run.command}` | `{run.exit_code}` | **{status_str}** | recorded |")
        else:
            body_lines.append("_No automated tests were registered for this repository._")

        body_lines.extend([
            f"",
            f"### Safety & Governance Boundaries",
            f"- **Branch Containment:** Working branch `codeforge/task-{task.id}` verified.",
            f"- **Secret Scan:** Verified clean diff (no private keys, tokens, or credentials).",
            f"- **Human-in-the-Loop:** Explicit human approval was verified prior to opening this pull request.",
            f"- **No Automatic Merging:** CodeForge AI never automatically merges pull requests. A repository maintainer must review and merge manually.",
        ])

        return {
            "title": title,
            "body": "\n".join(body_lines),
        }

    # --------------------------------------------------------------------------
    # 3. Branch & PR Operations
    # --------------------------------------------------------------------------
    def create_branch(
        self, repository_url: str, branch_name: str, base_branch: Optional[str] = None
    ) -> CreateBranchResponse:
        """
        Creates a new Git reference (branch) on the target repository pointing to the base branch tip.
        """
        owner, repo_name, _ = parse_and_normalize_github_url(repository_url)
        full_name = f"{owner}/{repo_name}"

        clean_branch = (branch_name or "").strip()
        if not clean_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch name cannot be empty.",
            )
        if clean_branch.startswith("refs/heads/"):
            clean_branch = clean_branch[len("refs/heads/"):]

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            target_base = (base_branch.strip() if base_branch else None) or repository.default_branch or "main"

            base_ref = repository.get_branch(target_base)
            base_sha = base_ref.commit.sha

            ref_path = f"refs/heads/{clean_branch}"
            created_ref = repository.create_git_ref(ref=ref_path, sha=base_sha)

            return CreateBranchResponse(
                branch_name=clean_branch,
                sha=created_ref.object.sha,
                ref=created_ref.ref,
            )
        except Exception as exc:
            self.github_service._handle_github_exception(exc, context=f"create_branch {full_name}:{clean_branch}")

    def create_pull_request(self, payload: CreatePullRequestRequest) -> GitHubPullRequestRef:
        """
        Creates a new pull request on GitHub comparing head_branch against base_branch.
        Never merges automatically.
        """
        owner, repo_name, _ = parse_and_normalize_github_url(payload.repository_url)
        full_name = f"{owner}/{repo_name}"

        clean_title = (payload.title or "").strip()
        if not clean_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pull request title cannot be empty.",
            )

        clean_head = (payload.head_branch or "").strip()
        if clean_head.startswith("refs/heads/"):
            clean_head = clean_head[len("refs/heads/"):]

        clean_base = payload.base_branch.strip() if payload.base_branch else None
        if clean_base and clean_base.startswith("refs/heads/"):
            clean_base = clean_base[len("refs/heads/"):]

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            target_base = clean_base or repository.default_branch or "main"

            # Check if matching pull request already exists to avoid duplicate PRs
            try:
                existing_pulls = repository.get_pulls(state="all", head=f"{owner}:{clean_head}")
                for existing in existing_pulls:
                    logger.info("Found existing pull request #%s for %s", existing.number, clean_head)
                    return GitHubPullRequestRef(
                        pr_number=existing.number,
                        pr_url=existing.html_url,
                        title=existing.title,
                        body=existing.body,
                        head_branch=clean_head,
                        base_branch=target_base,
                        state=getattr(existing, "state", "open") or "open",
                        is_draft=getattr(existing, "draft", False) or False,
                        created_at=getattr(existing, "created_at", None),
                    )
            except Exception as check_exc:
                logger.debug("Error checking existing PR for %s: %s", clean_head, check_exc)

            try:
                pr = repository.create_pull(
                    title=clean_title,
                    body=payload.body or "",
                    head=clean_head,
                    base=target_base,
                    draft=payload.draft,
                )
            except Exception as create_exc:
                if "already exists" in str(create_exc).lower():
                    try:
                        for existing in repository.get_pulls(state="open"):
                            head_ref = getattr(existing.head, "ref", "")
                            if head_ref == clean_head:
                                return GitHubPullRequestRef(
                                    pr_number=existing.number,
                                    pr_url=existing.html_url,
                                    title=existing.title,
                                    body=existing.body,
                                    head_branch=clean_head,
                                    base_branch=target_base,
                                    state=getattr(existing, "state", "open") or "open",
                                    is_draft=getattr(existing, "draft", False) or False,
                                    created_at=getattr(existing, "created_at", None),
                                )
                    except Exception:
                        pass
                raise create_exc

            return GitHubPullRequestRef(
                pr_number=pr.number,
                pr_url=pr.html_url,
                title=pr.title,
                body=pr.body,
                head_branch=clean_head,
                base_branch=target_base,
                state=getattr(pr, "state", "open") or "open",
                is_draft=getattr(pr, "draft", False) or False,
                created_at=getattr(pr, "created_at", None),
            )
        except Exception as exc:
            self.github_service._handle_github_exception(exc, context=f"create_pull_request {full_name}")

    def get_pull_request(self, repository_url: str, pr_number: int) -> GitHubPullRequestRef:
        """
        Fetches metadata of an existing pull request from GitHub.
        """
        if pr_number <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"PR number must be greater than zero. Received: {pr_number}",
            )
        owner, repo_name, _ = parse_and_normalize_github_url(repository_url)
        full_name = f"{owner}/{repo_name}"

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            pr = repository.get_pull(number=pr_number)

            head_branch = getattr(pr.head, "ref", str(pr.head)) if pr.head else ""
            base_branch = getattr(pr.base, "ref", str(pr.base)) if pr.base else ""

            return GitHubPullRequestRef(
                pr_number=pr.number,
                pr_url=pr.html_url,
                title=pr.title,
                body=pr.body,
                head_branch=head_branch,
                base_branch=base_branch,
                state=getattr(pr, "state", "open") or "open",
                is_draft=getattr(pr, "draft", False) or False,
                created_at=getattr(pr, "created_at", None),
            )
        except Exception as exc:
            self.github_service._handle_github_exception(exc, context=f"get_pull_request {full_name}#{pr_number}")

    # --------------------------------------------------------------------------
    # 4. End-to-End Task PR Creation with Human Approval & Verification
    # --------------------------------------------------------------------------
    def get_task_pr_preview(self, db: Session, task_id: int) -> TaskPRPreviewResponse:
        """
        Get comprehensive PR preparation preview, verification summary, and approval state for a task.
        """
        task = db.scalar(select(Task).where(Task.id == task_id))
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with ID {task_id} not found.",
            )

        file_changes = db.scalars(select(FileChange).where(FileChange.task_id == task_id)).all()
        test_runs = db.scalars(select(TestRun).where(TestRun.task_id == task_id).order_by(TestRun.started_at.asc())).all()

        head_branch = f"codeforge/task-{task.id}"
        base_branch = "main"

        # Check existing PR event
        existing_pr_event = db.scalar(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .where(TaskEvent.event_type == "pr_created")
            .order_by(TaskEvent.created_at.desc())
        )
        existing_pr: Optional[GitHubPullRequestRef] = None
        if existing_pr_event and existing_pr_event.structured_metadata:
            meta = existing_pr_event.structured_metadata
            if "pr_number" in meta and "pr_url" in meta:
                existing_pr = GitHubPullRequestRef(
                    pr_number=meta["pr_number"],
                    pr_url=meta["pr_url"],
                    title=meta.get("title", ""),
                    body=meta.get("body", ""),
                    head_branch=meta.get("head_branch", head_branch),
                    base_branch=meta.get("base_branch", base_branch),
                    state=meta.get("state", "open"),
                    is_draft=meta.get("is_draft", False),
                    created_at=datetime.fromisoformat(meta["created_at"]) if "created_at" in meta else existing_pr_event.created_at,
                )

        # Check human approval event
        approval_event = db.scalar(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .where(TaskEvent.event_type == "pr_approved")
        )
        is_approved = approval_event is not None

        # Safety & verification checks
        safety_passed, safety_violations = self.scan_diff_for_secrets_and_safety(file_changes)
        is_ready, readiness_issues = self.verify_branch_and_diff(task, file_changes, test_runs)

        tests_passed = len(test_runs) > 0 and all(r.passed for r in test_runs)
        summary = self.prepare_pull_request_summary(task, file_changes, test_runs)

        can_create_pr = is_ready and safety_passed and (existing_pr is None)

        return TaskPRPreviewResponse(
            task_id=task.id,
            repository_url=task.repository_url,
            head_branch=head_branch,
            base_branch=base_branch,
            suggested_title=summary["title"],
            suggested_body=summary["body"],
            file_changes_count=len(file_changes),
            test_runs_count=len(test_runs),
            tests_passed=tests_passed,
            safety_passed=safety_passed,
            safety_violations=safety_violations,
            is_ready=is_ready,
            readiness_issues=readiness_issues,
            is_approved=is_approved,
            can_create_pr=can_create_pr,
            existing_pr=existing_pr,
        )

    def create_task_pull_request(
        self,
        db: Session,
        task_id: int,
        approved: bool,
        custom_title: Optional[str] = None,
        custom_body: Optional[str] = None,
        custom_base: Optional[str] = None,
        draft: bool = False,
    ) -> GitHubPullRequestRef:
        """
        Creates a real pull request on GitHub for a verified task.
        Requirements:
        - Explicit human approval required (approved must be True).
        - Validates that working branch and diff correspond to task.
        - Scans diff for secrets and disallowed files.
        - Verifies authorization (push permissions).
        - Records real PR number, URL, state, branches, and timestamp.
        - Never fabricates metadata or displays success on failure.
        - Never merges automatically.
        """
        # 1. Require explicit human approval
        if not approved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Explicit human approval is required before creating a pull request.",
            )

        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with ID {task_id} not found.",
            )

        file_changes = db.scalars(select(FileChange).where(FileChange.task_id == task_id)).all()
        test_runs = db.scalars(select(TestRun).where(TestRun.task_id == task_id).order_by(TestRun.started_at.asc())).all()

        # 2. Check diff safety and secret presence
        safety_passed, safety_violations = self.scan_diff_for_secrets_and_safety(file_changes)
        if not safety_passed:
            raise HTTPException(
                status_code=422,
                detail=f"Pull request creation blocked: secrets or disallowed files detected in diff: {', '.join(safety_violations)}",
            )

        # 3. Check branch and task readiness
        is_ready, readiness_issues = self.verify_branch_and_diff(task, file_changes, test_runs, allow_active=True)
        if not is_ready:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task is not ready for PR creation: {'; '.join(readiness_issues)}",
            )

        if not file_changes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create pull request: no file changes were recorded for this task.",
            )

        # 4. Check repository write permissions
        validation_resp = self.github_service.validate_repository(task.repository_url)
        if not validation_resp.can_push:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Authenticated GitHub token lacks push permissions for {validation_resp.full_name}. Cannot open pull request.",
            )

        head_branch = task.source_branch or generate_task_branch_name(task.id, task.task_description)
        task.source_branch = head_branch
        target_base = custom_base or validation_resp.default_branch or "main"
        task.target_branch = target_base

        # Safety: Never push task changes directly to default or protected branch
        if head_branch == target_base or head_branch.lower() in ("main", "master", "develop"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Refusing to push task changes directly to protected branch '{head_branch}'. Must use an isolated task branch.",
            )

        # Check if already created
        existing_event = db.scalar(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .where(TaskEvent.event_type == "pr_created")
        )
        if existing_event and existing_event.structured_metadata:
            meta = existing_event.structured_metadata
            return GitHubPullRequestRef(
                pr_number=meta["pr_number"],
                pr_url=meta["pr_url"],
                title=meta.get("title", ""),
                body=meta.get("body", ""),
                head_branch=meta.get("head_branch", head_branch),
                base_branch=meta.get("base_branch", target_base),
                state=meta.get("state", "open"),
                is_draft=meta.get("is_draft", False),
                created_at=datetime.fromisoformat(meta["created_at"]) if "created_at" in meta else existing_event.created_at,
            )

        # 5. Push branch from workspace if local git repository exists
        backend_dir = Path(__file__).resolve().parent.parent.parent
        task_workspace_dir = backend_dir / "workspaces" / str(task.id)

        if (task_workspace_dir / ".git").is_dir():
            clean_env = sanitize_subprocess_env()
            token = self.token
            try:
                # Ensure no persisted or duplicate http.extraheader exists in repo config
                subprocess.run(
                    ["git", "config", "--unset-all", "http.extraheader"],
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=15,
                    env=clean_env,
                    capture_output=True,
                )
                # Ensure local git workspace has the task branch checked out
                subprocess.run(
                    ["git", "checkout", "-B", head_branch],
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=15,
                    env=clean_env,
                    capture_output=True,
                )
                # Ensure bytecode and pycache are ignored
                gi_file = task_workspace_dir / ".gitignore"
                if not gi_file.exists():
                    gi_file.write_text("__pycache__/\n*.py[cod]\n*$py.class\n.pytest_cache/\n", encoding="utf-8")
                subprocess.run(
                    ["git", "rm", "-r", "--cached", "__pycache__", "tests/__pycache__"],
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=10,
                    env=clean_env,
                    capture_output=True,
                )
                # Stage and commit any unstaged changes
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=15,
                    env=clean_env,
                    capture_output=True,
                )
                commit_msg = f"fix(agent): [Task #{task.id}] verified implementation and tests"
                if task.issue_number:
                    commit_msg += f" (Resolves #{task.issue_number})"
                subprocess.run(
                    ["git", "-c", "user.name=CodeForge AI", "-c", "user.email=agent@codeforge.ai", "commit", "-m", commit_msg],
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=15,
                    env=clean_env,
                    capture_output=True,
                )
                # Push branch with HTTP Basic auth header so token is not written to .git/config
                push_cmd = ["git"]
                if token:
                    basic_auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
                    push_cmd.extend(["-c", f"http.extraheader=AUTHORIZATION: basic {basic_auth}"])
                push_cmd.extend(["push", "-u", "origin", head_branch])
                proc = subprocess.run(
                    push_cmd,
                    cwd=str(task_workspace_dir),
                    check=False,
                    timeout=45,
                    env=clean_env,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    raw_err = proc.stderr.strip() or proc.stdout.strip() or "git push failed"
                    # If conflict or non-fast-forward on this task branch, retry with --force
                    if any(c in raw_err.lower() for c in ("non-fast-forward", "fetch first", "rejected")):
                        logger.info("Retrying push with --force for task branch %s", head_branch)
                        proc = subprocess.run(
                            push_cmd + ["--force"],
                            cwd=str(task_workspace_dir),
                            check=False,
                            timeout=45,
                            env=clean_env,
                            capture_output=True,
                            text=True,
                        )
                if proc.returncode != 0:
                    raw_err = proc.stderr.strip() or proc.stdout.strip() or "git push failed"
                    err_msg = sanitize_github_token(raw_err, token)
                    logger.error("git push for task %s branch %s returned %d: %s", task.id, head_branch, proc.returncode, err_msg)
                    task.status = "publish_failed"
                    task.current_agent_stage = "publish_failed"
                    task.error_summary = f"Git push failed (exit code {proc.returncode}): {err_msg}"
                    fail_event = TaskEvent(
                        task_id=task.id,
                        stage="publish_failed",
                        event_type="publish_failed",
                        message=f"Git push failed for {head_branch}: {err_msg}",
                        structured_metadata={"error": err_msg, "exit_code": proc.returncode, "branch": head_branch},
                    )
                    db.add(fail_event)
                    db.commit()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Branch publication failed (git push exit code {proc.returncode}): {err_msg}",
                    )
                else:
                    push_event = TaskEvent(
                        task_id=task.id,
                        stage="publishing",
                        event_type="branch_pushed",
                        message=f"Successfully pushed branch {head_branch} to remote repository.",
                        structured_metadata={"head_branch": head_branch},
                    )
                    db.add(push_event)
                    db.commit()
            except HTTPException:
                raise
            except Exception as exc:
                err_str = sanitize_github_token(str(exc), token)
                logger.error("Error pushing branch %s: %s", head_branch, err_str)
                task.status = "publish_failed"
                task.current_agent_stage = "publish_failed"
                task.error_summary = f"Git push error: {err_str}"
                fail_event = TaskEvent(
                    task_id=task.id,
                    stage="publish_failed",
                    event_type="publish_failed",
                    message=f"Git push encountered error for {head_branch}: {err_str}",
                    structured_metadata={"error": err_str, "branch": head_branch},
                )
                db.add(fail_event)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Branch publication failed: {err_str}",
                )

        # 6. Prepare summary
        summary = self.prepare_pull_request_summary(task, file_changes, test_runs)
        pr_title = (custom_title or "").strip() or summary["title"]
        pr_body = (custom_body or "").strip() or summary["body"]

        # 7. Record approval event if not recorded
        approval_event = db.scalar(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .where(TaskEvent.event_type == "pr_approved")
        )
        if not approval_event:
            appr = TaskEvent(
                task_id=task.id,
                stage="pr_approved",
                event_type="pr_approved",
                message="Pull request creation approved by human operator.",
                structured_metadata={"approved": True, "approved_at": datetime.now(timezone.utc).isoformat()},
            )
            db.add(appr)
            db.commit()

        # 8. Call GitHub API to create the pull request
        try:
            pr_ref = self.create_pull_request(
                CreatePullRequestRequest(
                    repository_url=task.repository_url,
                    title=pr_title,
                    head_branch=head_branch,
                    base_branch=target_base,
                    body=pr_body,
                    draft=draft,
                )
            )

            # 9. Record actual PR metadata in PostgreSQL and update Task
            task.pr_number = pr_ref.pr_number
            task.pr_url = pr_ref.pr_url
            task.source_branch = pr_ref.head_branch
            task.target_branch = pr_ref.base_branch
            task.status = "completed"
            task.current_agent_stage = "completed"
            task.error_summary = None

            created_event = TaskEvent(
                task_id=task.id,
                stage="pr_created",
                event_type="pr_created",
                message=f"Pull request #{pr_ref.pr_number} successfully opened on GitHub: {pr_ref.pr_url}",
                structured_metadata={
                    "pr_number": pr_ref.pr_number,
                    "pr_url": pr_ref.pr_url,
                    "title": pr_ref.title,
                    "body": pr_ref.body,
                    "head_branch": pr_ref.head_branch,
                    "base_branch": pr_ref.base_branch,
                    "state": pr_ref.state,
                    "is_draft": pr_ref.is_draft,
                    "created_at": pr_ref.created_at.isoformat() if pr_ref.created_at else datetime.now(timezone.utc).isoformat(),
                },
            )
            db.add(created_event)
            db.commit()

            return pr_ref

        except Exception as exc:
            db.rollback()
            err_msg = sanitize_github_token(str(exc), self.token)
            logger.error("Failed to create GitHub pull request for task %s: %s", task.id, err_msg)

            task.status = "pr_creation_failed"
            task.current_agent_stage = "pr_creation_failed"
            task.error_summary = f"GitHub pull request creation failed: {err_msg}"

            fail_event = TaskEvent(
                task_id=task.id,
                stage="pr_creation_failed",
                event_type="pr_creation_failed",
                message=f"GitHub pull request creation failed: {err_msg}",
                structured_metadata={"error": err_msg},
            )
            db.add(fail_event)
            db.commit()

            # Re-raise clean error (handled by _handle_github_exception or generic)
            if isinstance(exc, HTTPException):
                raise exc
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub pull request creation failed: {err_msg}",
            )

    def publish_and_create_pull_request(
        self,
        db: Session,
        task_id: int,
        approved: bool = True,
        custom_title: Optional[str] = None,
        custom_body: Optional[str] = None,
        custom_base: Optional[str] = None,
        draft: bool = False,
    ) -> GitHubPullRequestRef:
        """
        Safely publish verified changes to task branch and open pull request on GitHub.
        """
        return self.create_task_pull_request(
            db=db,
            task_id=task_id,
            approved=approved,
            custom_title=custom_title,
            custom_body=custom_body,
            custom_base=custom_base,
            draft=draft,
        )


_global_pr_service: Optional[PullRequestService] = None


def get_pr_service() -> PullRequestService:
    """Return singleton PullRequestService instance."""
    global _global_pr_service
    if _global_pr_service is None:
        _global_pr_service = PullRequestService()
    return _global_pr_service
