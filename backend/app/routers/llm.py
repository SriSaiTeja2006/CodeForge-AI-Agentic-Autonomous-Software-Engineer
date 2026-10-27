from fastapi import APIRouter, Depends, status

from app.schemas.llm import (
    LLMStatusResponse,
    LLMTestRequest,
    LLMTestResponse,
)
from app.services.llm_service import LLMService

router = APIRouter(prefix="/llm", tags=["LLM"])


def get_llm_service() -> LLMService:
    """Dependency providing a configured LLMService instance."""
    return LLMService()


@router.get("/status", response_model=LLMStatusResponse)
def get_llm_status(service: LLMService = Depends(get_llm_service)):
    """
    Check the configuration status of the LLM service and verify model availability
    without exposing credentials.
    """
    return service.get_status()


@router.get("/health", response_model=LLMStatusResponse)
def get_llm_health(service: LLMService = Depends(get_llm_service)):
    """
    Health check alias for LLM service status and model connectivity.
    """
    return service.get_status()


@router.post("/test", response_model=LLMTestResponse, status_code=status.HTTP_200_OK)
def test_llm_completion(
    payload: LLMTestRequest,
    service: LLMService = Depends(get_llm_service),
):
    """
    Execute a test prompt through the configured Groq chat model and return the generated completion.
    Does not execute generated code.
    """
    return service.generate_test_completion(payload)
