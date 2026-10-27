import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Ensure backend root is on sys.path so app modules can be imported
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import get_settings
from app.database import Base
import app.models  # noqa: F401 - ensure models are registered with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# Escape % for configparser interpolation safety
escaped_url = settings.sync_database_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", escaped_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.sync_database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.sync_database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
