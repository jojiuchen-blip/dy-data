from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from apps.api.dy_api.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
MIGRATION_ADVISORY_LOCK_KEY = 294903237518183233


def database_url() -> str:
    return os.getenv("DY_DATABASE_URL") or os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        migration_lock_acquired = False
        migration_lock_connection = None
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET statement_timeout = '10min'")
            connection.commit()
            # Use a raw psycopg connection with explicit DBAPI autocommit.
            # SQLAlchemy's execution_options can still expose a virtual
            # transaction while a lock waiter is blocked; that transaction
            # interferes with historical CREATE INDEX CONCURRENTLY steps.
            migration_lock_connection = connectable.raw_connection()
            try:
                driver_connection = migration_lock_connection.driver_connection
                driver_connection.autocommit = True
                with driver_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_lock(%s)",
                        (MIGRATION_ADVISORY_LOCK_KEY,),
                    )
                migration_lock_acquired = True
            except BaseException:
                migration_lock_connection.close()
                migration_lock_connection = None
                raise

        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if migration_lock_acquired:
                try:
                    driver_connection = migration_lock_connection.driver_connection
                    driver_connection.autocommit = True
                    with driver_connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock(%s)",
                            (MIGRATION_ADVISORY_LOCK_KEY,),
                        )
                finally:
                    migration_lock_connection.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
