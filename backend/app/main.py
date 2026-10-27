from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routers import health, tasks, github, llm
from app.services.task_runner import get_task_worker

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    if settings.ENABLE_IN_PROCESS_WORKER:
        worker = get_task_worker()
        worker.poll_interval = settings.WORKER_POLL_INTERVAL
        worker.stale_timeout_seconds = settings.WORKER_STALE_TIMEOUT
        worker.start()
    yield
    if settings.ENABLE_IN_PROCESS_WORKER:
        worker = get_task_worker()
        worker.stop()


app = FastAPI(
    title="CodeForge AI API",
    version="0.1.0",
    description="Backend API for CodeForge AI autonomous software engineering agent",
    lifespan=lifespan,
)

# Configure CORS using configured frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(github.router)
app.include_router(llm.router)

