from typing import List, Optional
from fastapi import APIRouter, Query, Path, Depends, status

from app.schemas.github import (
    ValidateRepositoryRequest,
    ValidateRepositoryResponse,
    InspectRepositoryRequest,
    InspectRepositoryResponse,
    GitHubIssue,
    CreatePullRequestRequest,
    GitHubPullRequestRef,
)
from app.services.github_service import GitHubService
from app.services.pr_service import PullRequestService, get_pr_service

router = APIRouter(prefix="/github", tags=["GitHub"])


def get_github_service() -> GitHubService:
    """Dependency providing a configured GitHubService instance."""
    return GitHubService()


@router.post("/validate-repository", response_model=ValidateRepositoryResponse)
def validate_repository(
    payload: ValidateRepositoryRequest,
    service: GitHubService = Depends(get_github_service),
):
    """
    Validate repository URL format, check existence, and verify token accessibility and permissions.
    Does not clone the repository or mutate branches.
    """
    return service.validate_repository(payload.repository_url)


@router.post("/repositories/inspect", response_model=InspectRepositoryResponse)
def inspect_repository(
    payload: InspectRepositoryRequest,
    service: GitHubService = Depends(get_github_service),
):
    """
    Retrieve repository metadata, default branch, statistics, and visibility.
    """
    return service.inspect_repository(payload.repository_url)


@router.get("/issues", response_model=List[GitHubIssue])
def list_repository_issues(
    repository: str = Query(
        ...,
        description="Repository URL or owner/repo identifier",
        examples=["octocat/Hello-World", "https://github.com/octocat/Hello-World"],
    ),
    state: str = Query("open", pattern="^(open|closed|all)$", description="Issue state to filter by"),
    limit: int = Query(30, ge=1, le=100, description="Maximum number of issues to return"),
    service: GitHubService = Depends(get_github_service),
):
    """
    Fetch genuine issues for a GitHub repository, returning titles, bodies, labels, and states.
    Filters out pull requests.
    """
    return service.get_repository_issues(repository, state=state, limit=limit)


@router.get("/issues/{owner}/{repo}/{issue_number}", response_model=GitHubIssue)
def get_issue(
    owner: str,
    repo: str,
    issue_number: int = Path(..., ge=1, description="GitHub issue number"),
    service: GitHubService = Depends(get_github_service),
):
    """
    Fetch full details for an individual GitHub issue by repository and issue number.
    """
    return service.get_issue(owner, repo, issue_number)


@router.post("/pull-requests", response_model=GitHubPullRequestRef, status_code=status.HTTP_201_CREATED)
def create_pull_request(
    payload: CreatePullRequestRequest,
    pr_service: PullRequestService = Depends(get_pr_service),
):
    """
    Create a new pull request on GitHub comparing head_branch against base_branch.
    Never merges automatically.
    """
    return pr_service.create_pull_request(payload)


@router.get("/pull-requests/{owner}/{repo}/{pr_number}", response_model=GitHubPullRequestRef)
def get_pull_request(
    owner: str,
    repo: str,
    pr_number: int = Path(..., ge=1, description="GitHub pull request number"),
    pr_service: PullRequestService = Depends(get_pr_service),
):
    """
    Fetch metadata of an existing pull request on GitHub.
    """
    repository_url = f"https://github.com/{owner}/{repo}"
    return pr_service.get_pull_request(repository_url, pr_number)

