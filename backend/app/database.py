from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy domain models."""
    pass


engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_database() -> bool:
    """Check database connectivity with a lightweight query without leaking credentials."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
