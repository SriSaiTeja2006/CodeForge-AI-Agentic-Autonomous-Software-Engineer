import logging
import re
import socket
from typing import Optional, List, Tuple
from fastapi import HTTPException, status
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from groq import Groq
import groq

from app.config import get_settings
from app.schemas.llm import (
    LLMStatusResponse,
    LLMTestRequest,
    LLMTestResponse,
)

logger = logging.getLogger(__name__)


def sanitize_groq_api_key(text: str, key: Optional[str] = None) -> str:
    """Ensure no Groq API keys or Bearer credentials leak into logs or error messages."""
    if not text:
        return ""
    sanitized = text
    if key and len(key) > 4:
        sanitized = sanitized.replace(key, "[REDACTED_KEY]")
    # Redact standard Groq api keys (gsk_...)
    sanitized = re.sub(r"gsk_[A-Za-z0-9_]{20,}", "[REDACTED_KEY]", sanitized)
    sanitized = re.sub(
        r"(Bearer|api_key|api-key)\s+[A-Za-z0-9_.-]+",
        r"\1 [REDACTED_KEY]",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


class LLMService:
    """
    Service layer encapsulating LLM configuration, model verification,
    and completion generation using LangChain and Groq.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: int = 30,
    ):
        settings = get_settings()
        key_val = api_key if api_key is not None else settings.GROQ_API_KEY.get_secret_value()
        self.api_key = key_val.strip() if key_val else ""
        self.configured_model = (model_name if model_name is not None else settings.GROQ_MODEL).strip()
        self.timeout = timeout
        self._available_models: Optional[List[str]] = None

    def _get_chat_model(
        self,
        temperature: float = 0.2,
        max_tokens: int = 512,
        model: Optional[str] = None,
    ) -> ChatGroq:
        """Create and configure a LangChain ChatGroq instance."""
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GROQ_API_KEY is not configured. Please supply a valid Groq API key in environment settings.",
            )
        target_model = (model or self.configured_model).strip()
        return ChatGroq(
            api_key=self.api_key,
            model_name=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self.timeout,
            max_retries=1,
        )

    def get_available_models(self) -> List[str]:
        """
        Query provider for active models to verify configured model against supported identifiers.
        Filters out pure audio/speech models.
        """
        if not self.api_key:
            return []
        if self._available_models is not None:
            return self._available_models
        try:
            client = Groq(api_key=self.api_key, timeout=min(self.timeout, 10))
            models_response = client.models.list()
            chat_models = [
                m.id for m in models_response.data
                if not m.id.startswith("whisper-")
            ]
            self._available_models = chat_models
            return chat_models
        except Exception as exc:
            sanitized_err = sanitize_groq_api_key(str(exc), self.api_key)
            logger.warning("Could not list Groq models: %s", sanitized_err)
            return []

    def verify_model(self, model: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Verify whether the requested model is supported by Groq.
        """
        target = (model or self.configured_model).strip()
        available = self.get_available_models()
        if not available:
            # When provider model list is unreachable (e.g. offline or test environment),
            # accept configured model identifier if non-empty
            return bool(target), target if target else None
        if target in available:
            return True, target
        return False, None

    def get_status(self) -> LLMStatusResponse:
        """
        Report LLM service status and model configuration without exposing credentials.
        """
        is_configured = bool(self.api_key and len(self.api_key) > 5)
        if not is_configured:
            return LLMStatusResponse(
                provider="groq",
                is_configured=False,
                configured_model=self.configured_model,
                active_model=None,
                available_models=[],
                message="GROQ_API_KEY is not configured.",
            )

        models = self.get_available_models()
        is_valid, active = self.verify_model(self.configured_model)

        if is_valid and active:
            msg = f"Groq LLM service is configured and ready with active model '{active}'."
        elif models:
            msg = f"Configured model '{self.configured_model}' was not found among active provider models."
        else:
            active = self.configured_model
            msg = f"Groq LLM service is configured with model '{self.configured_model}'."

        return LLMStatusResponse(
            provider="groq",
            is_configured=True,
            configured_model=self.configured_model,
            active_model=active,
            available_models=models,
            message=msg,
        )

    def generate_test_completion(self, request: LLMTestRequest) -> LLMTestResponse:
        """
        Execute a test prompt through the configured Groq chat model.
        Returns generated text and token consumption without executing code.
        """
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GROQ_API_KEY is not configured. Please supply a valid Groq API key in environment settings.",
            )

        # Enforce reasonable input limits
        clean_prompt = (request.prompt or "").strip()
        if not clean_prompt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prompt cannot be empty or whitespace only.",
            )

        messages: List[BaseMessage] = []
        if request.system_prompt and request.system_prompt.strip():
            messages.append(SystemMessage(content=request.system_prompt.strip()))
        messages.append(HumanMessage(content=clean_prompt))

        llm = self._get_chat_model(
            temperature=request.temperature or 0.2,
            max_tokens=request.max_tokens or 512,
        )

        try:
            response = llm.invoke(messages)
            if not response or not hasattr(response, "content") or response.content is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Groq LLM returned an empty or invalid response.",
                )

            # Extract token metadata safely
            meta = getattr(response, "response_metadata", {}) or {}
            usage = meta.get("token_usage", {}) or {}
            usage_meta = getattr(response, "usage_metadata", {}) or {}

            prompt_tokens = usage.get("prompt_tokens") or usage_meta.get("input_tokens")
            completion_tokens = usage.get("completion_tokens") or usage_meta.get("output_tokens")
            total_tokens = usage.get("total_tokens") or usage_meta.get("total_tokens")

            model_name = meta.get("model_name") or self.configured_model

            return LLMTestResponse(
                model=model_name,
                response=str(response.content),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except Exception as exc:
            self._handle_groq_exception(exc, context="generate_test_completion")

    def invoke_prompt(
        self,
        prompt_template: ChatPromptTemplate,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """
        Helper method to format a LangChain ChatPromptTemplate and invoke the Groq model.
        Prepares the service for agent stage workflows without executing any code.
        """
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GROQ_API_KEY is not configured.",
            )

        llm = self._get_chat_model(temperature=temperature, max_tokens=max_tokens)
        chain = prompt_template | llm
        try:
            result = chain.invoke(kwargs)
            if not result or not hasattr(result, "content") or result.content is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Groq LLM returned an empty response.",
                )
            return str(result.content)
        except Exception as exc:
            self._handle_groq_exception(exc, context="invoke_prompt")

    def _handle_groq_exception(self, exc: Exception, context: str = "") -> None:
        """
        Translates provider and LangChain exceptions into actionable HTTPExceptions.
        Redacts API keys to prevent credential leakage.
        """
        if isinstance(exc, HTTPException):
            raise exc

        sanitized_msg = sanitize_groq_api_key(str(exc), self.api_key)
        logger.warning("Groq operation failed for %s: %s", context, sanitized_msg)

        err_text = str(exc).lower()
        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)

        if (
            isinstance(exc, groq.AuthenticationError)
            or status_code == 401
            or "invalid api key" in err_text
            or "unauthorized" in err_text
            or "invalid_api_key" in err_text
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Groq API key. Please check your GROQ_API_KEY configuration.",
            )

        if isinstance(exc, groq.PermissionDeniedError) or status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden by Groq API. Check account access permissions.",
            )

        if (
            isinstance(exc, groq.NotFoundError)
            or status_code == 404
            or "model_not_found" in err_text
            or "does not exist" in err_text
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configured Groq model '{self.configured_model}' not found or unavailable.",
            )

        if (
            isinstance(exc, groq.RateLimitError)
            or status_code == 429
            or "rate limit" in err_text
            or "tokens per minute" in err_text
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Groq API rate limit exceeded. Please wait before retrying.",
            )

        if (
            isinstance(exc, (groq.APITimeoutError, socket.timeout, TimeoutError))
            or status_code == 504
            or "timed out" in err_text
        ):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Groq API request timed out after {self.timeout}s.",
            )

        if isinstance(exc, (groq.APIConnectionError,)) or "connection error" in err_text:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to Groq API. Upstream connection error.",
            )

        if isinstance(exc, groq.BadRequestError) or status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bad request to Groq API: {sanitized_msg}",
            )

        if isinstance(exc, (groq.GroqError, groq.APIError)) or (status_code and status_code >= 500):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Groq upstream provider error: {sanitized_msg}",
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred while communicating with the LLM provider.",
        )
