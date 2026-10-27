"""
Package alias so that both `uvicorn main:app` and `uvicorn app.main:app` work.
"""
from app.main import app

__all__ = ["app"]
