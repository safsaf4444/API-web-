import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# 1. Load config
config = context.config

# 2. Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 3. Import your models
from backend.models import SQLModel
target_metadata = SQLModel.metadata

def get_url():
    """Fetch URL from environment and fix the prefix for SQLAlchemy."""
    url = os.getenv("DATABASE_URL")
    if url:
        # Railway provides postgres:// but SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    # Use create_engine directly here to ensure the latest Env Var is used
    from sqlalchemy import create_engine
    connectable = create_engine(get_url())

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()