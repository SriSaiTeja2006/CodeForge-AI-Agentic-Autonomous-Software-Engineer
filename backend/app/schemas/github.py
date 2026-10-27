from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict, AliasChoices


class ValidateRepositoryRequest(BaseModel):
    """Request payload to validate GitHub repository access and format."""

    repository_url: str = Field(
        ...,
        validation_alias=AliasChoices("repository_url", "repository", "url"),
        description="GitHub repository URL in HTTPS, SSH, or owner/repo format",
        examples=["https://github.com/octocat/Hello-World", "git@github.com:octocat/Hello-World.git", "octocat/Hello-World"],
    )


class ValidateRepositoryResponse(BaseModel):
    """Validation response including parsed coordinates, permissions, and visibility."""

    valid: bool = Field(True, description="Whether the repository exists and is accessible")
    owner: str = Field(..., description="Repository owner or organization")
    repo: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository path (owner/repo)")
    normalized_url: str = Field(..., description="Canonical HTTPS clone/browse URL")
    default_branch: str = Field(..., description="Default repository branch (e.g., main or master)")
    is_private: bool = Field(..., description="Whether the repository is private")
    can_push: bool = Field(..., description="Whether the authenticated token has push/write permissions")
    can_pull: bool = Field(..., description="Whether the authenticated token has read/pull permissions")
    description: Optional[str] = Field(None, description="Repository description")

    model_config = ConfigDict(from_attributes=True)


class InspectRepositoryRequest(BaseModel):
    """Request payload to inspect a repository's metadata."""

    repository_url: str = Field(
        ...,
        validation_alias=AliasChoices("repository_url", "repository", "url"),
        description="GitHub repository URL in HTTPS, SSH, or owner/repo format",
        examples=["https://github.com/octocat/Hello-World"],
    )


class InspectRepositoryResponse(BaseModel):
    """Comprehensive repository metadata without cloning or mutating branches."""

    owner: str = Field(..., description="Repository owner or organization")
    repo: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository path (owner/repo)")
    normalized_url: str = Field(..., description="Canonical HTTPS clone/browse URL")
    default_branch: str = Field(..., description="Default repository branch")
    is_private: bool = Field(..., description="Whether the repository is private")
    description: Optional[str] = Field(None, description="Repository description")
    language: Optional[str] = Field(None, description="Primary programming language")
    open_issues_count: int = Field(0, description="Total count of open issues and PRs")
    stars_count: int = Field(0, description="Star/stargazer count")
    forks_count: int = Field(0, description="Fork count")
    can_push: bool = Field(..., description="Whether the authenticated token has push permissions")
    can_pull: bool = Field(..., description="Whether the authenticated token has pull permissions")

    model_config = ConfigDict(from_attributes=True)


class GitHubIssue(BaseModel):
    """Representation of a GitHub issue."""

    number: int = Field(..., description="Issue number")
    title: str = Field(..., description="Issue title")
    body: Optional[str] = Field(None, description="Issue body markdown description")
    labels: List[str] = Field(default_factory=list, description="List of label names applied to the issue")
    state: str = Field("open", description="Issue state (open, closed)")
    html_url: Optional[str] = Field(None, description="Direct web URL to the issue on GitHub")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class CreateBranchRequest(BaseModel):
    """Request payload to create a new Git branch."""

    repository_url: str = Field(
        ...,
        validation_alias=AliasChoices("repository_url", "repository", "url"),
        description="Repository URL",
    )
    branch_name: str = Field(..., description="Name for the new branch to create")
    base_branch: Optional[str] = Field(None, description="Base branch to branch off from (defaults to repository default branch)")


class CreateBranchResponse(BaseModel):
    """Response payload following branch creation."""

    branch_name: str
    sha: str
    ref: str


class CreatePullRequestRequest(BaseModel):
    """Request payload to open a pull request."""

    repository_url: str = Field(
        ...,
        validation_alias=AliasChoices("repository_url", "repository", "url"),
        description="Repository URL",
    )
    title: str = Field(..., description="Pull request title")
    head_branch: str = Field(..., description="Branch containing the proposed changes")
    base_branch: Optional[str] = Field(None, description="Base branch to merge into (defaults to default branch)")
    body: Optional[str] = Field(None, description="Pull request description body markdown")
    draft: bool = Field(False, description="Whether to open the pull request as a draft")


class GitHubPullRequestRef(BaseModel):
    """Representation of an opened or referenced pull request."""

    pr_number: int = Field(..., description="Pull request number")
    pr_url: str = Field(..., description="Direct web URL to the pull request on GitHub")
    title: str = Field(..., description="Pull request title")
    body: Optional[str] = Field(None, description="Pull request body description")
    head_branch: str = Field(..., description="Feature branch containing changes")
    base_branch: str = Field(..., description="Target base branch")
    state: str = Field("open", description="Pull request state (open, closed, merged)")
    is_draft: bool = Field(False, description="Whether the PR is currently a draft")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)

