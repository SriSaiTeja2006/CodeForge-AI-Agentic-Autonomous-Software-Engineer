from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class LLMStatusResponse(BaseModel):
    """Status information on the configured LLM provider and available models."""

    provider: str = Field("groq", description="LLM provider name")
    is_configured: bool = Field(..., description="Whether API key is supplied and authenticated")
    configured_model: str = Field(..., description="Model ID configured in application settings")
    active_model: Optional[str] = Field(None, description="Model ID actively validated with provider")
    available_models: List[str] = Field(default_factory=list, description="List of provider active chat models")
    message: str = Field(..., description="Status summary message")

    model_config = ConfigDict(from_attributes=True)


class LLMTestRequest(BaseModel):
    """Request payload for executing a test prompt."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Test input prompt for the LLM",
        examples=["Hello, CodeForge AI!"],
    )
    system_prompt: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional system instruction override",
    )
    temperature: Optional[float] = Field(
        0.2,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    max_tokens: Optional[int] = Field(
        512,
        ge=1,
        le=4096,
        description="Maximum output tokens for test execution",
    )


class LLMTestResponse(BaseModel):
    """Response payload containing generated text and token statistics."""

    model: str = Field(..., description="Model ID that generated the completion")
    response: str = Field(..., description="Generated text completion from the model")
    prompt_tokens: Optional[int] = Field(None, description="Input prompt tokens consumed")
    completion_tokens: Optional[int] = Field(None, description="Completion tokens consumed")
    total_tokens: Optional[int] = Field(None, description="Total tokens consumed")

    model_config = ConfigDict(from_attributes=True)
