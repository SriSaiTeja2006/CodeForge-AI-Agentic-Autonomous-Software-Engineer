import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from github import (
    GithubException,
    BadCredentialsException,
    RateLimitExceededException,
    UnknownObjectException,
)

from app.main import app
from app.services.pr_service import PullRequestService
from app.schemas.github import CreatePullRequestRequest

client = TestClient(app)


def _create_mock_repo(
    full_name="octocat/Hello-World",
    default_branch="main",
    private=False,
    description="My sample repository",
    can_push=True,
    can_pull=True,
    language="Python",
    open_issues_count=5,
    stargazers_count=42,
    forks_count=7,
):
    """Helper to generate a mock PyGithub Repository instance."""
    mock_repo = MagicMock()
    mock_repo.full_name = full_name
    mock_repo.default_branch = default_branch
    mock_repo.private = private
    mock_repo.description = description
    mock_repo.language = language
    mock_repo.open_issues_count = open_issues_count
    mock_repo.stargazers_count = stargazers_count
    mock_repo.forks_count = forks_count

    mock_perms = MagicMock()
    mock_perms.push = can_push
    mock_perms.pull = can_pull
    mock_repo.permissions = mock_perms
    return mock_repo


def test_validate_repository_success():
    """Verify repository validation endpoint returns accurate metadata."""
    mock_repo = _create_mock_repo()

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is True
        assert data["owner"] == "octocat"
        assert data["repo"] == "Hello-World"
        assert data["full_name"] == "octocat/Hello-World"
        assert data["normalized_url"] == "https://github.com/octocat/Hello-World"
        assert data["default_branch"] == "main"
        assert data["is_private"] is False
        assert data["can_push"] is True
        assert data["can_pull"] is True


def test_validate_repository_ssh_and_shorthand():
    """Verify URL normalization for SSH and shorthand owner/repo notations."""
    mock_repo = _create_mock_repo()

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        # Test SSH format
        ssh_res = client.post(
            "/github/validate-repository",
            json={"repository_url": "git@github.com:octocat/Hello-World.git"},
        )
        assert ssh_res.status_code == 200
        assert ssh_res.json()["normalized_url"] == "https://github.com/octocat/Hello-World"

        # Test shorthand format
        short_res = client.post(
            "/github/validate-repository",
            json={"repository_url": "octocat/Hello-World"},
        )
        assert short_res.status_code == 200
        assert short_res.json()["normalized_url"] == "https://github.com/octocat/Hello-World"


def test_validate_repository_invalid_url():
    """Verify invalid repository URL formats return actionable HTTP 400."""
    res = client.post(
        "/github/validate-repository",
        json={"repository_url": "invalid-url-without-slash"},
    )
    assert res.status_code == 400
    assert "Invalid GitHub repository URL" in res.json()["detail"]


def test_validate_repository_not_found():
    """Verify inaccessible or nonexistent repositories return HTTP 404."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = GithubException(status=404, data={"message": "Not Found"})
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/nonexistent/repo"},
        )
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


def test_validate_repository_rate_limit():
    """Verify rate limit errors return HTTP 429."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = RateLimitExceededException(status=403, data={"message": "API rate limit exceeded"})
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()


def test_validate_repository_bad_credentials():
    """Verify bad authentication credentials return HTTP 401."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = BadCredentialsException(status=401, data={"message": "Bad credentials"})
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 401
        assert "Invalid GitHub authentication token" in res.json()["detail"]


def test_inspect_repository_success():
    """Verify repository inspection retrieves statistics, language, and branch without mutation."""
    mock_repo = _create_mock_repo(
        language="TypeScript",
        open_issues_count=12,
        stargazers_count=150,
        forks_count=25,
    )

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/repositories/inspect",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "TypeScript"
        assert data["open_issues_count"] == 12
        assert data["stars_count"] == 150
        assert data["forks_count"] == 25


def test_list_issues_filters_pull_requests():
    """Verify issues endpoint returns genuine issues and ignores pull requests."""
    mock_repo = MagicMock()

    # Issue 1: genuine issue
    mock_issue = MagicMock()
    mock_issue.number = 1
    mock_issue.title = "Bug in login flow"
    mock_issue.body = "Steps to reproduce..."
    mock_issue.state = "open"
    mock_issue.html_url = "https://github.com/octocat/Hello-World/issues/1"
    mock_issue.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_issue.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    mock_issue.pull_request = None

    mock_label = MagicMock()
    mock_label.name = "bug"
    mock_issue.labels = [mock_label]

    # Issue 2: pull request disguised as issue in GitHub API
    mock_pr_as_issue = MagicMock()
    mock_pr_as_issue.pull_request = MagicMock()  # not None, indicates PR

    mock_repo.get_issues.return_value = [mock_issue, mock_pr_as_issue]

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues?repository=octocat/Hello-World&state=open")
        assert res.status_code == 200
        issues = res.json()
        assert len(issues) == 1
        assert issues[0]["number"] == 1
        assert issues[0]["title"] == "Bug in login flow"
        assert issues[0]["labels"] == ["bug"]


def test_get_individual_issue_and_not_found():
    """Verify fetching individual issue details and 404 handling."""
    mock_repo = MagicMock()
    mock_issue = MagicMock()
    mock_issue.number = 42
    mock_issue.title = "Specific issue title"
    mock_issue.body = "Detailed description"
    mock_issue.state = "open"
    mock_issue.html_url = "https://github.com/octocat/Hello-World/issues/42"
    mock_issue.created_at = None
    mock_issue.updated_at = None
    mock_issue.labels = []
    mock_repo.get_issue.return_value = mock_issue

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        # Existing issue
        res = client.get("/github/issues/octocat/Hello-World/42")
        assert res.status_code == 200
        assert res.json()["number"] == 42
        assert res.json()["title"] == "Specific issue title"

        # Missing issue
        mock_repo.get_issue.side_effect = UnknownObjectException(status=404, data={"message": "Not Found"})
        missing_res = client.get("/github/issues/octocat/Hello-World/9999")
        assert missing_res.status_code == 404


def test_pr_service_interfaces():
    """Verify PullRequestService interface logic for branch and PR creation."""
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"

    # Branch mock
    mock_branch = MagicMock()
    mock_branch.commit.sha = "abc123sha"
    mock_repo.get_branch.return_value = mock_branch

    mock_git_ref = MagicMock()
    mock_git_ref.ref = "refs/heads/codeforge/feature-1"
    mock_git_ref.object.sha = "abc123sha"
    mock_repo.create_git_ref.return_value = mock_git_ref

    # PR mock
    mock_pr = MagicMock()
    mock_pr.number = 101
    mock_pr.html_url = "https://github.com/octocat/Hello-World/pull/101"
    mock_pr.title = "CodeForge generated changes"
    mock_pr.body = "Fix summary..."
    mock_pr.state = "open"
    mock_pr.draft = False
    mock_pr.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_repo.create_pull.return_value = mock_pr

    service = PullRequestService(token="mock_token")
    with patch.object(service, "_get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        # Test branch creation
        branch_resp = service.create_branch("octocat/Hello-World", "codeforge/feature-1")
        assert branch_resp.branch_name == "codeforge/feature-1"
        assert branch_resp.sha == "abc123sha"
        mock_repo.create_git_ref.assert_called_once_with(ref="refs/heads/codeforge/feature-1", sha="abc123sha")

        # Test PR creation
        pr_req = CreatePullRequestRequest(
            repository_url="octocat/Hello-World",
            title="CodeForge generated changes",
            head_branch="codeforge/feature-1",
            base_branch="main",
            body="Fix summary...",
        )
        pr_resp = service.create_pull_request(pr_req)
        assert pr_resp.pr_number == 101
        assert pr_resp.pr_url == "https://github.com/octocat/Hello-World/pull/101"
        assert pr_resp.head_branch == "codeforge/feature-1"
        mock_repo.create_pull.assert_called_once_with(
            title="CodeForge generated changes",
            body="Fix summary...",
            head="codeforge/feature-1",
            base="main",
            draft=False,
        )


def test_validate_repository_url_variants():
    """Verify HTTP, domain-only, git://, and URLs with query/fragment are normalized."""
    mock_repo = _create_mock_repo()

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        variants = [
            "http://github.com/octocat/Hello-World",
            "github.com/octocat/Hello-World",
            "git://github.com/octocat/Hello-World.git",
            "https://github.com/octocat/Hello-World?tab=readme-ov-file#installation",
            "https://www.github.com/octocat/Hello-World/",
        ]
        for var in variants:
            res = client.post("/github/validate-repository", json={"repository_url": var})
            assert res.status_code == 200, f"Failed for variant: {var}"
            data = res.json()
            assert data["owner"] == "octocat"
            assert data["repo"] == "Hello-World"
            assert data["normalized_url"] == "https://github.com/octocat/Hello-World"


def test_validate_repository_foreign_hosts_and_empty():
    """Verify non-GitHub hosts and empty strings are rejected with actionable 400 errors."""
    # Non-GitHub host
    res1 = client.post(
        "/github/validate-repository",
        json={"repository_url": "https://gitlab.com/octocat/Hello-World"},
    )
    assert res1.status_code == 400
    assert "Only GitHub repositories are supported" in res1.json()["detail"]

    # Empty URL
    res2 = client.post(
        "/github/validate-repository",
        json={"repository_url": "   "},
    )
    assert res2.status_code == 400
    assert "Repository URL cannot be empty" in res2.json()["detail"]


def test_validate_repository_forbidden_permissions():
    """Verify 403 Forbidden translates to an actionable error explaining token permissions."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = GithubException(status=403, data={"message": "Must have admin rights"})
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 403
        assert "Access forbidden by GitHub" in res.json()["detail"]


def test_validate_repository_timeout_and_network_error():
    """Verify timeouts return 504 Gateway Timeout and connection errors return 502."""
    import socket
    import requests

    # Timeout
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = socket.timeout("timed out")
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 504
        assert "timed out" in res.json()["detail"].lower()

    # Network Connection Error
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = requests.exceptions.ConnectionError("Failed to resolve github.com")
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 502
        assert "Failed to connect to GitHub API" in res.json()["detail"]


def test_github_token_is_never_leaked():
    """Verify that sensitive GitHub tokens are never exposed in error responses or logs."""
    from app.services.github_service import sanitize_github_token

    secret_pat = os.getenv("TEST_GITHUB_PAT", "fake-test-pat-token-value-98765")
    secret_ghp = os.getenv("TEST_GITHUB_GHP", "fake-test-ghp-token-value-12345")

    # Direct sanitizer test
    dirty_string = f"Error communicating with {secret_pat} and header Authorization: Bearer {secret_ghp}"
    cleaned = sanitize_github_token(dirty_string, secret_pat)
    assert secret_pat not in cleaned
    assert secret_ghp not in cleaned
    assert "[REDACTED_TOKEN]" in cleaned

    # In endpoint error response
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = GithubException(
            status=500,
            data={"message": f"Server crash using token {secret_pat}"},
        )
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 502
        detail = res.json()["detail"]
        assert secret_pat not in detail
        assert "[REDACTED_TOKEN]" in detail


def test_private_repository_permissions_without_push():
    """Verify private repository validation handles read-only tokens and permissions."""
    mock_repo = _create_mock_repo(private=True, can_push=False, can_pull=True)

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/validate-repository",
            json={"repository_url": "https://github.com/octocat/Private-Repo"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_private"] is True
        assert data["can_push"] is False
        assert data["can_pull"] is True


def test_inspect_repository_invalid_url_and_timeout():
    """Verify inspect_repository validates URL and handles timeouts cleanly."""
    import socket

    # Invalid URL
    res = client.post("/github/repositories/inspect", json={"repository_url": "bad-url"})
    assert res.status_code == 400

    # Timeout
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = socket.timeout("timeout")
        mock_get_client.return_value = mock_gh

        res = client.post(
            "/github/repositories/inspect",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        assert res.status_code == 504


def test_get_individual_issue_validation():
    """Verify issue_number <= 0 is rejected with 422 Unprocessable Entity."""
    res = client.get("/github/issues/octocat/Hello-World/0")
    assert res.status_code == 422

    res_neg = client.get("/github/issues/octocat/Hello-World/-5")
    assert res_neg.status_code == 422


def test_pr_service_ref_handling_and_validation():
    """Verify PR service handles branch prefix normalization and input validation."""
    service = PullRequestService(token="test_token")

    # Empty branch name
    with pytest.raises(Exception) as exc_info:
        service.create_branch("octocat/Hello-World", "   ")
    assert "Branch name cannot be empty" in str(exc_info.value)

    # Empty PR title
    with pytest.raises(Exception) as exc_info2:
        service.create_pull_request(
            CreatePullRequestRequest(
                repository_url="octocat/Hello-World",
                title="   ",
                head_branch="feature",
            )
        )
    assert "Pull request title cannot be empty" in str(exc_info2.value)

    # Invalid PR number
    with pytest.raises(Exception) as exc_info3:
        service.get_pull_request("octocat/Hello-World", 0)
    assert "PR number must be greater than zero" in str(exc_info3.value)

    # Verify branch ref normalization (refs/heads/ stripped before ref creation to prevent refs/heads/refs/heads/)
    mock_repo = MagicMock()
    mock_branch = MagicMock()
    mock_branch.commit.sha = "123sha"
    mock_repo.get_branch.return_value = mock_branch
    mock_ref = MagicMock()
    mock_ref.ref = "refs/heads/my-feature"
    mock_ref.object.sha = "123sha"
    mock_repo.create_git_ref.return_value = mock_ref

    with patch.object(service, "_get_client") as mock_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_client.return_value = mock_gh

        res = service.create_branch("octocat/Hello-World", "refs/heads/my-feature")
        assert res.branch_name == "my-feature"
        mock_repo.create_git_ref.assert_called_once_with(
            ref="refs/heads/my-feature",
            sha="123sha",
        )

