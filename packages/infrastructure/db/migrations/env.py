"""Alembic environment — auto-detects models and reads DATABASE_URL from env."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Make repo root importable so `packages.*` resolves correctly.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[4]  # career-openclaw-v2/
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Import models so Alembic's autogenerate sees the metadata.
# ---------------------------------------------------------------------------
from packages.infrastructure.db.models import Base  # noqa: E402

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Alembic Config object (gives access to alembic.ini values).
# ---------------------------------------------------------------------------
config = context.config

# Inject DATABASE_URL from environment (overrides alembic.ini sqlalchemy.url).
_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://career:career@localhost:5432/career_openclaw",
)
config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
