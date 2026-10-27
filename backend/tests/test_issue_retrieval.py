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
from app.services.github_service import GitHubService
from app.schemas.github import GitHubIssue

client = TestClient(app)


# ==============================================================================
# 1. SUCCESSFUL ISSUE RETRIEVAL TESTS
# ==============================================================================

def test_retrieve_issue_success():
    """
    Verify successful retrieval of a GitHub issue with its real title,
    description/body, issue number, and canonical HTML URL.
    """
    mock_issue = MagicMock()
    mock_issue.number = 1
    mock_issue.title = "The add function returns an incorrect result"
    mock_issue.body = "The add(a, b) function in calculator.py returns an incorrect result..."
    mock_issue.state = "open"
    mock_issue.html_url = "https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab/issues/1"
    mock_issue.created_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    mock_issue.updated_at = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    mock_issue.labels = []

    mock_repo = MagicMock()
    mock_repo.get_issue.return_value = mock_issue

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/1")
        assert res.status_code == 200
        data = res.json()

        assert data["number"] == 1
        assert data["title"] == "The add function returns an incorrect result"
        assert "The add(a, b) function in calculator.py" in data["body"]
        assert data["state"] == "open"
        assert data["html_url"] == "https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab/issues/1"

        # Verify exact repository and issue requested from PyGithub
        mock_gh.get_repo.assert_called_once_with("kuruvadhonendravarma-spec/codeforge-test-lab")
        mock_repo.get_issue.assert_called_once_with(number=1)


# ==============================================================================
# 2. ERROR HANDLING AND NON-INVENTION TESTS
# ==============================================================================

def test_retrieve_issue_nonexistent_returns_404():
    """
    Verify requesting a nonexistent issue returns HTTP 404 with a clear error
    and never invents a fabricated issue or placeholder.
    """
    mock_repo = MagicMock()
    mock_repo.get_issue.side_effect = UnknownObjectException(status=404, data={"message": "Not Found"})

    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/99999")
        assert res.status_code == 404
        data = res.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        # Verify no fabricated issue payload
        assert "title" not in data
        assert "body" not in data


def test_retrieve_issue_inaccessible_repository_returns_404():
    """
    Verify requesting an issue from a private or nonexistent repository
    returns HTTP 404 without leaking internal state.
    """
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = GithubException(status=404, data={"message": "Not Found"})
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues/kuruvadhonendravarma-spec/private-repo/1")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


def test_retrieve_issue_rate_limit_exceeded_returns_429():
    """Verify GitHub API rate limit errors return HTTP 429."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = RateLimitExceededException(
            status=403, data={"message": "API rate limit exceeded"}
        )
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/1")
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()


def test_retrieve_issue_bad_credentials_returns_401():
    """Verify expired or invalid GitHub tokens return HTTP 401."""
    with patch("app.services.github_service.GitHubService._get_client") as mock_get_client:
        mock_gh = MagicMock()
        mock_gh.get_repo.side_effect = BadCredentialsException(
            status=401, data={"message": "Bad credentials"}
        )
        mock_get_client.return_value = mock_gh

        res = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/1")
        assert res.status_code == 401
        assert "Invalid GitHub authentication token" in res.json()["detail"]


def test_retrieve_issue_invalid_parameters():
    """Verify invalid parameters (e.g. non-positive issue numbers) return HTTP 422 validation error."""
    res_zero = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/0")
    assert res_zero.status_code == 422

    res_negative = client.get("/github/issues/kuruvadhonendravarma-spec/codeforge-test-lab/-5")
    assert res_negative.status_code == 422
