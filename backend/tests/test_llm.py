import os
import socket
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
import groq

from app.main import app
from app.services.llm_service import LLMService, sanitize_groq_api_key
from app.schemas.llm import LLMTestRequest
from app.agent.prompts import (
    INVESTIGATION_PROMPT,
    PLANNING_PROMPT,
    PATCH_GENERATION_PROMPT,
    TEST_DIAGNOSIS_PROMPT,
)

client = TestClient(app)


def test_llm_status_configured():
    """Verify /llm/status reports configured state and verified active model."""
    mock_models = MagicMock()
    mock_item1 = MagicMock()
    mock_item1.id = "openai/gpt-oss-120b"
    mock_item2 = MagicMock()
    mock_item2.id = "openai/gpt-oss-20b"
    mock_models.data = [mock_item1, mock_item2]

    with patch("app.services.llm_service.Groq") as mock_groq_class:
        mock_groq_instance = MagicMock()
        mock_groq_instance.models.list.return_value = mock_models
        mock_groq_class.return_value = mock_groq_instance

        res = client.get("/llm/status")
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "groq"
        assert data["is_configured"] is True
        assert data["configured_model"] == "openai/gpt-oss-120b"
        assert data["active_model"] == "openai/gpt-oss-120b"
        assert "openai/gpt-oss-120b" in data["available_models"]
        assert "ready" in data["message"].lower()

        # Check alias endpoint /llm/health
        alias_res = client.get("/llm/health")
        assert alias_res.status_code == 200
        assert alias_res.json()["is_configured"] is True


def test_llm_status_unconfigured():
    """Verify status reports unconfigured state when API key is missing."""
    service = LLMService(api_key="", model_name="openai/gpt-oss-120b")
    status_resp = service.get_status()
    assert status_resp.is_configured is False
    assert status_resp.active_model is None
    assert status_resp.available_models == []
    assert "not configured" in status_resp.message.lower()


def test_llm_status_model_not_found():
    """Verify status reports when configured model is not in available models."""
    mock_models = MagicMock()
    mock_item1 = MagicMock()
    mock_item1.id = "openai/gpt-oss-20b"
    mock_models.data = [mock_item1]

    service = LLMService(
        api_key=os.getenv("TEST_GROQ_API_KEY", "fake-test-groq-key-value-12345"),
        model_name="obsolete-model-id",
    )
    with patch("app.services.llm_service.Groq") as mock_groq_class:
        mock_groq_instance = MagicMock()
        mock_groq_instance.models.list.return_value = mock_models
        mock_groq_class.return_value = mock_groq_instance

        status_resp = service.get_status()
        assert status_resp.is_configured is True
        assert status_resp.active_model is None
        assert "not found" in status_resp.message.lower()


def test_llm_test_completion_success():
    """Verify POST /llm/test returns completion and token metadata without executing code."""
    mock_response = MagicMock()
    mock_response.content = "def add(a, b): return a + b"
    mock_response.response_metadata = {
        "model_name": "openai/gpt-oss-120b",
        "token_usage": {
            "prompt_tokens": 15,
            "completion_tokens": 20,
            "total_tokens": 35,
        },
    }

    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = mock_response
        mock_chat_groq.return_value = mock_llm_instance

        payload = {
            "prompt": "Write a python function to add two numbers.",
            "temperature": 0.1,
            "max_tokens": 256,
        }
        res = client.post("/llm/test", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["model"] == "openai/gpt-oss-120b"
        assert data["response"] == "def add(a, b): return a + b"
        assert data["prompt_tokens"] == 15
        assert data["completion_tokens"] == 20
        assert data["total_tokens"] == 35


def test_llm_test_with_system_prompt():
    """Verify system prompt and custom parameters are properly passed to ChatGroq."""
    mock_response = MagicMock()
    mock_response.content = "System instructions acknowledged."
    mock_response.response_metadata = {}

    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = mock_response
        mock_chat_groq.return_value = mock_llm_instance

        payload = {
            "prompt": "Hello!",
            "system_prompt": "You are a senior python engineer.",
            "temperature": 0.5,
            "max_tokens": 128,
        }
        res = client.post("/llm/test", json=payload)
        assert res.status_code == 200
        assert res.json()["response"] == "System instructions acknowledged."

        # Verify messages passed to invoke
        args, _ = mock_llm_instance.invoke.call_args
        messages = args[0]
        assert len(messages) == 2
        assert messages[0].content == "You are a senior python engineer."
        assert messages[1].content == "Hello!"


def test_llm_test_empty_prompt_rejected():
    """Verify empty or whitespace-only prompt is rejected with 422 or 400."""
    res1 = client.post("/llm/test", json={"prompt": ""})
    assert res1.status_code == 422

    res2 = client.post("/llm/test", json={"prompt": "    "})
    assert res2.status_code == 400
    assert "empty" in res2.json()["detail"].lower()


def test_llm_test_unconfigured_service():
    """Verify attempting to test when unconfigured returns 401."""
    service = LLMService(api_key="")
    with pytest.raises(Exception) as exc_info:
        service.generate_test_completion(LLMTestRequest(prompt="Test"))
    assert exc_info.value.status_code == 401
    assert "not configured" in exc_info.value.detail.lower()


def test_llm_test_authentication_error():
    """Verify provider 401 authentication failure maps to HTTP 401."""
    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = groq.AuthenticationError(
            message="Invalid API Key",
            response=MagicMock(status_code=401),
            body={"error": {"message": "Invalid API Key"}},
        )
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 401
        assert "Invalid or expired Groq API key" in res.json()["detail"]


def test_llm_test_rate_limit_error():
    """Verify provider rate limit error maps to HTTP 429."""
    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = groq.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body={"error": {"message": "Rate limit exceeded"}},
        )
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()


def test_llm_test_model_not_found_error():
    """Verify unavailable model maps to HTTP 404."""
    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = groq.NotFoundError(
            message="Model does not exist",
            response=MagicMock(status_code=404),
            body={"error": {"message": "Model does not exist"}},
        )
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 404
        assert "not found or unavailable" in res.json()["detail"].lower()


def test_llm_test_timeout_error():
    """Verify timeout maps to HTTP 504 Gateway Timeout."""
    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = socket.timeout("timed out")
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 504
        assert "timed out" in res.json()["detail"].lower()


def test_llm_test_connection_error():
    """Verify connection errors map to HTTP 502 Bad Gateway."""
    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = groq.APIConnectionError(request=MagicMock())
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 502
        assert "Failed to connect to Groq API" in res.json()["detail"]


def test_llm_test_empty_response_fails():
    """Verify that returning empty content never reports success."""
    mock_response = MagicMock()
    mock_response.content = None

    with patch("app.services.llm_service.ChatGroq") as mock_chat_groq:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_chat_groq.return_value = mock_llm

        res = client.post("/llm/test", json={"prompt": "Test"})
        assert res.status_code == 502
        assert "empty or invalid" in res.json()["detail"].lower()


def test_groq_api_key_sanitization():
    """Verify that sensitive Groq API keys are redacted from logs and errors."""
    secret_key = os.getenv("TEST_GROQ_API_KEY", "fake-test-groq-key-value-12345")
    dirty = f"Groq request failed for key {secret_key} with header api_key: {secret_key}"
    cleaned = sanitize_groq_api_key(dirty, secret_key)
    assert secret_key not in cleaned
    assert "[REDACTED_KEY]" in cleaned


def test_prompt_templates_formatting():
    """Verify all 4 core agent prompt templates format cleanly with expected input variables."""
    # 1. Investigation prompt
    inv_messages = INVESTIGATION_PROMPT.format_messages(
        repository_name="octocat/Hello-World",
        task_description="Fix null pointer exception",
        acceptance_criteria="App does not crash",
        code_context="def run(): pass",
    )
    assert len(inv_messages) == 2
    assert "Fix null pointer exception" in inv_messages[1].content

    # 2. Planning prompt
    plan_messages = PLANNING_PROMPT.format_messages(
        task_description="Implement auth check",
        investigation_summary="Missing token check in middleware",
        relevant_files="app/middleware/auth.py",
    )
    assert len(plan_messages) == 2
    assert "Missing token check in middleware" in plan_messages[1].content

    # 3. Patch generation prompt
    patch_messages = PATCH_GENERATION_PROMPT.format_messages(
        file_path="app/config.py",
        change_description="Add new environment variable",
        original_content="class Settings: pass",
    )
    assert len(patch_messages) == 2
    assert "Add new environment variable" in patch_messages[1].content

    # 4. Test failure diagnosis prompt
    diag_messages = TEST_DIAGNOSIS_PROMPT.format_messages(
        test_command="pytest tests/test_auth.py",
        exit_code=1,
        stdout="FAILED test_auth.py",
        stderr="",
        recent_changes="Added line 10",
    )
    assert len(diag_messages) == 2
    assert "FAILED test_auth.py" in diag_messages[1].content
