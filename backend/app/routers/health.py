from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from app.database import ping_database

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    database: str


@router.get("/health", response_model=HealthResponse)
def health_check(response: Response):
    """
    Report application and database health status separately.
    Returns HTTP 503 Service Unavailable if the database check fails.
    """
    db_ok = ping_database()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            app="healthy",
            database="disconnected",
        )

    return HealthResponse(
        status="healthy",
        app="healthy",
        database="connected",
    )
