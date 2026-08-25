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
        migration_driver_connection = None
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET statement_timeout = '10min'")
            connection.commit()
            # Acquire the session lock on the same DBAPI connection that
            # Alembic will use for the migration. A separate raw connection
            # can release the lock's coverage when Alembic switches the
            # migration connection into an autocommit block for
            # CREATE INDEX CONCURRENTLY. Raw DBAPI autocommit keeps a waiting
            # process outside SQLAlchemy's virtual transaction while keeping
            # the lock attached to the migration session.
            migration_driver_connection = connection.connection.driver_connection
            try:
                migration_driver_connection.autocommit = True
                with migration_driver_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_lock(%s)",
                        (MIGRATION_ADVISORY_LOCK_KEY,),
                    )
                migration_lock_acquired = True
            except BaseException:
                raise
            finally:
                if not migration_lock_acquired:
                    migration_driver_connection.autocommit = False
            migration_driver_connection.autocommit = False

        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if migration_lock_acquired:
                try:
                    if connection.in_transaction():
                        connection.rollback()
                    migration_driver_connection.autocommit = True
                    with migration_driver_connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock(%s)",
                            (MIGRATION_ADVISORY_LOCK_KEY,),
                        )
                finally:
                    migration_driver_connection.autocommit = False


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
