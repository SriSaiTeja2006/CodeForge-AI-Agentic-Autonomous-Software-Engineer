"""
Main entrypoint alias for running the FastAPI backend.
The primary application definition is located in `app.main`.
"""
from app.main import app

__all__ = ["app"]
