import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the app's own settings/engine config and every module that defines
# ORM models. The import of app.models.url is for its *side effect*:
# defining Url and Click registers their tables on Base.metadata, which is
# what target_metadata below needs in order for `--autogenerate` to see them.
# A models package that grows more model modules later needs each new one
# imported here too (or imported from app/models/__init__.py, then just that
# import kept here) -- forgetting this is the single most common reason
# autogenerate "sees no changes" for a table that very much exists in code.
from app.config import get_settings
from app.database import Base
import app.models.url  # noqa: F401  (imported for side effect: registers models)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Overrides whatever placeholder is in alembic.ini with the real URL from
# .env, via the same Settings the app itself uses (app/config.py) -- one
# source of truth for the connection string, and Neon's password never has
# to be written into alembic.ini.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Base.metadata now includes Url and Click (registered by the import above).
# This is what makes `alembic revision --autogenerate` a real diff against
# your models instead of producing an empty migration.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # Same reasoning as app/database.py: asyncpg has no concept of the
    # `sslmode` query param (that's a libpq/psycopg2 thing), and Neon (or
    # any managed Postgres) requires TLS -- so SSL is turned on via
    # connect_args instead of embedding it in the URL.
    connect_args = {"ssl": True} if settings.db_requires_ssl else {}

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
