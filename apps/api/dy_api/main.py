from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dy_api.cli_audit import (
    CliAuditMiddleware,
    DatabaseCliAuditSink,
    configure_cli_audit_logging,
)
from dy_api.cli_contract import install_cli_exception_handlers
from dy_api.routes import (
    admin,
    auth,
    cli,
    cli_auth,
    clues,
    dashboard,
    feedback,
    jobs,
    meta,
)


def create_app() -> FastAPI:
    configure_cli_audit_logging()
    app = FastAPI(title="Douyin Laike Dashboard API", version="0.1.0")
    app.state.cli_audit_sink = DatabaseCliAuditSink()

    allowed_origins = [
        origin.strip()
        for origin in os.getenv("DY_API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["*"],
        )

    app.add_middleware(CliAuditMiddleware)
    install_cli_exception_handlers(app)

    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(
        cli_auth.router, prefix="/api/v1/auth/cli", tags=["cli-auth"]
    )
    app.include_router(cli.router, prefix="/api/v1", tags=["cli-readonly"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(meta.router, prefix="/api/v1", tags=["metadata"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(clues.router, prefix="/api/v1", tags=["clues"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    return app


app = create_app()
