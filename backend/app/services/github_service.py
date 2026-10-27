import logging
import re
import socket
from typing import Tuple, List, Optional
import requests
import urllib3
from github import (
    Github,
    Auth,
    GithubException,
    BadCredentialsException,
    RateLimitExceededException,
    UnknownObjectException,
)
from fastapi import HTTPException, status

from app.config import get_settings
from app.schemas.github import (
    ValidateRepositoryResponse,
    InspectRepositoryResponse,
    GitHubIssue,
)

logger = logging.getLogger(__name__)

GITHUB_URL_PATTERNS = [
    # git@github.com:owner/repo(.git)?
    re.compile(r"^git@github\.com:([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?/?$"),
    # ssh://(git@)?github.com/owner/repo(.git)?
    re.compile(r"^ssh://(?:git@)?github\.com/([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?/?$"),
    # git://github.com/owner/repo(.git)?
    re.compile(r"^git://github\.com/([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?/?$"),
    # https?://(www\.)?github\.com/owner/repo
    re.compile(r"^https?://(?:www\.)?github\.com/([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?(?:/.*)?$"),
    # (www\.)?github\.com/owner/repo
    re.compile(r"^(?:www\.)?github\.com/([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?(?:/.*)?$"),
    # owner/repo
    re.compile(r"^([^/\s:#?]+)/([^/\s:#?]+?)(?:\.git)?/?$"),
]


def sanitize_github_token(text: str, token: Optional[str] = None) -> str:
    """Ensure no GitHub personal access tokens or bearer tokens leak into logs or responses."""
    if not text:
        return ""
    sanitized = text
    if token and len(token) > 4:
        sanitized = sanitized.replace(token, "[REDACTED_TOKEN]")
    sanitized = re.sub(r"ghp_[A-Za-z0-9_]{30,}", "[REDACTED_TOKEN]", sanitized)
    sanitized = re.sub(r"github_pat_[A-Za-z0-9_]{50,}", "[REDACTED_TOKEN]", sanitized)
    sanitized = re.sub(
        r"(token|Bearer)\s+[A-Za-z0-9_.-]+",
        r"\1 [REDACTED_TOKEN]",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def parse_and_normalize_github_url(url: str) -> Tuple[str, str, str]:
    """
    Parses various GitHub repository formats into (owner, repo, normalized_https_url).
    Supports HTTPS, HTTP, SSH, git://, domain-only, owner/repo, with or without .git suffix.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository URL cannot be empty.",
        )

    # Explicitly reject non-GitHub domains if a domain/scheme is provided
    if ("://" in cleaned or "@" in cleaned) and "github.com" not in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub repository URL: '{cleaned}'. Only GitHub repositories are supported.",
        )

    # Strip web query parameters and fragments
    base_url = cleaned.split("?")[0].split("#")[0].rstrip("/")

    for pattern in GITHUB_URL_PATTERNS:
        match = pattern.match(base_url) or pattern.match(cleaned)
        if match:
            owner, repo = match.group(1), match.group(2)
            if repo.endswith(".git"):
                repo = repo[:-4]
            # Owner cannot be a domain name like gitlab.com
            if "." in owner:
                continue
            if owner and repo:
                normalized_url = f"https://github.com/{owner}/{repo}"
                return owner, repo, normalized_url

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Invalid GitHub repository URL: '{cleaned}'. "
            "Supported formats: 'https://github.com/owner/repo', "
            "'git@github.com:owner/repo.git', or 'owner/repo'."
        ),
    )


def extract_repository_permissions(repository) -> Tuple[bool, bool]:
    """
    Safely extract (can_push, can_pull) permissions from a repository instance
    without assuming public access defaults or crashing on missing permission blocks.
    """
    perms = getattr(repository, "permissions", None)
    if perms is None:
        # In unauthenticated context, public repositories can be pulled/cloned, but not pushed
        is_private = getattr(repository, "private", False)
        return (False, not is_private)

    if isinstance(perms, dict):
        can_push = bool(perms.get("push", False) or perms.get("admin", False))
        can_pull = bool(perms.get("pull", True))
        return (can_push, can_pull)

    # For objects or MagicMocks, safely extract boolean flags
    raw_push = getattr(perms, "push", False)
    raw_admin = getattr(perms, "admin", False)
    raw_pull = getattr(perms, "pull", True)

    can_push = (raw_push is True) or (raw_admin is True)
    can_pull = raw_pull is not False
    return (can_push, can_pull)



class GitHubService:
    """Service encapsulating interactions with GitHub API using PyGithub."""

    def __init__(self, token: Optional[str] = None, timeout: int = 15):
        settings = get_settings()
        if token is not None:
            token_val = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
        elif settings.GITHUB_TOKEN:
            token_val = settings.GITHUB_TOKEN.get_secret_value()
        else:
            token_val = ""
        self.token = token_val.strip() if token_val else ""
        self.timeout = timeout

    def _get_client(self) -> Github:
        """Create an authenticated or unauthenticated PyGithub client instance."""
        if self.token:
            return Github(auth=Auth.Token(self.token), timeout=self.timeout)
        return Github(timeout=self.timeout)

    def _handle_github_exception(self, exc: Exception, context: str = "") -> None:
        """Translates GitHub exceptions into actionable HTTPExceptions without leaking tokens."""
        sanitized_context = sanitize_github_token(context, self.token)
        logger.warning(
            "GitHub operation exception for '%s': %s",
            sanitized_context,
            sanitize_github_token(str(exc), self.token),
        )

        if isinstance(exc, BadCredentialsException):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub authentication token. Please verify GITHUB_TOKEN.",
            )
        if isinstance(exc, RateLimitExceededException):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="GitHub API rate limit exceeded. Please wait before retrying.",
            )
        if isinstance(exc, UnknownObjectException):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Resource not found on GitHub ({sanitized_context}). Ensure repository exists and token has access.",
            )
        if isinstance(exc, GithubException):
            if exc.status == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository not found or private without token access ({sanitized_context}).",
                )
            if exc.status == 403:
                message = str(exc.data) if hasattr(exc, "data") else ""
                if "rate limit" in message.lower() or "secondary rate limit" in message.lower():
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="GitHub API rate limit exceeded.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access forbidden by GitHub for {sanitized_context}. Verify token scopes and repository permissions.",
                )
            if exc.status == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired GitHub authentication token.",
                )
            if exc.status == 422:
                raw_msg = (
                    exc.data.get("message", "Validation failed")
                    if hasattr(exc, "data") and isinstance(exc.data, dict)
                    else "Validation failed"
                )
                clean_msg = sanitize_github_token(raw_msg, self.token)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"GitHub validation error for {sanitized_context}: {clean_msg}",
                )
            raw_msg = (
                exc.data.get("message", "Upstream error")
                if hasattr(exc, "data") and isinstance(exc.data, dict)
                else "Upstream error"
            )
            clean_msg = sanitize_github_token(raw_msg, self.token)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API error: {clean_msg}",
            )
        if isinstance(exc, (requests.exceptions.Timeout, urllib3.exceptions.TimeoutError, socket.timeout, TimeoutError)):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"GitHub API request timed out after {self.timeout}s.",
            )
        if isinstance(exc, (requests.exceptions.ConnectionError, urllib3.exceptions.HTTPError)):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to GitHub API. Upstream network error.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred while communicating with GitHub.",
        )

    def validate_repository(self, repository_url: str) -> ValidateRepositoryResponse:
        """
        Validate repository format, verify existence, check accessibility and permissions.
        Does not clone repository or modify branches.
        """
        owner, repo, normalized_url = parse_and_normalize_github_url(repository_url)
        full_name = f"{owner}/{repo}"

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            can_push, can_pull = extract_repository_permissions(repository)

            return ValidateRepositoryResponse(
                valid=True,
                owner=owner,
                repo=repo,
                full_name=repository.full_name or full_name,
                normalized_url=normalized_url,
                default_branch=repository.default_branch or "main",
                is_private=bool(repository.private),
                can_push=can_push,
                can_pull=can_pull,
                description=repository.description,
            )
        except Exception as exc:
            self._handle_github_exception(exc, context=full_name)

    def inspect_repository(self, repository_url: str) -> InspectRepositoryResponse:
        """
        Fetch repository metadata, statistics, and branch details without cloning or mutating.
        """
        owner, repo, normalized_url = parse_and_normalize_github_url(repository_url)
        full_name = f"{owner}/{repo}"

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            can_push, can_pull = extract_repository_permissions(repository)

            return InspectRepositoryResponse(
                owner=owner,
                repo=repo,
                full_name=repository.full_name or full_name,
                normalized_url=normalized_url,
                default_branch=repository.default_branch or "main",
                is_private=bool(repository.private),
                description=repository.description,
                language=repository.language,
                open_issues_count=repository.open_issues_count or 0,
                stars_count=repository.stargazers_count or 0,
                forks_count=repository.forks_count or 0,
                can_push=can_push,
                can_pull=can_pull,
            )
        except Exception as exc:
            self._handle_github_exception(exc, context=full_name)

    def get_repository_issues(
        self, repository_identifier: str, state: str = "open", limit: int = 30
    ) -> List[GitHubIssue]:
        """
        Fetch real issue list (title, body, labels, state) for the repository.
        Excludes pull requests so only genuine issues are returned.
        """
        owner, repo, _ = parse_and_normalize_github_url(repository_identifier)
        full_name = f"{owner}/{repo}"

        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            issues_paginated = repository.get_issues(state=state)

            results: List[GitHubIssue] = []
            max_to_inspect = min(limit * 4, 200)
            inspected = 0

            for issue in issues_paginated:
                inspected += 1
                # GitHub issues API returns pull requests as well; filter them out
                if getattr(issue, "pull_request", None) is not None:
                    if inspected >= max_to_inspect:
                        break
                    continue

                label_names = [label.name for label in issue.labels] if issue.labels else []
                results.append(
                    GitHubIssue(
                        number=issue.number,
                        title=issue.title,
                        body=issue.body,
                        labels=label_names,
                        state=issue.state or state,
                        html_url=issue.html_url,
                        created_at=issue.created_at,
                        updated_at=issue.updated_at,
                    )
                )
                if len(results) >= limit or inspected >= max_to_inspect:
                    break

            return results
        except Exception as exc:
            self._handle_github_exception(exc, context=full_name)

    def get_issue(self, owner: str, repo: str, issue_number: int) -> GitHubIssue:
        """
        Fetch real issue details by issue number.
        """
        clean_owner = (owner or "").strip()
        clean_repo = (repo or "").strip()
        if not clean_owner or not clean_repo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Owner and repository name cannot be empty.",
            )
        if issue_number <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Issue number must be greater than zero. Received: {issue_number}",
            )

        full_name = f"{clean_owner}/{clean_repo}"
        gh = self._get_client()
        try:
            repository = gh.get_repo(full_name)
            issue = repository.get_issue(number=issue_number)

            label_names = [label.name for label in issue.labels] if issue.labels else []
            return GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body,
                labels=label_names,
                state=issue.state or "open",
                html_url=issue.html_url,
                created_at=issue.created_at,
                updated_at=issue.updated_at,
            )
        except Exception as exc:
            self._handle_github_exception(exc, context=f"{full_name}#{issue_number}")

