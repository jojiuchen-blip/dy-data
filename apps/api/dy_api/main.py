from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dy_api.routes import admin, auth, cli_auth, clues, dashboard, feedback, jobs, meta


def create_app() -> FastAPI:
    app = FastAPI(title="Douyin Laike Dashboard API", version="0.1.0")

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

    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(
        cli_auth.router, prefix="/api/v1/auth/cli", tags=["cli-auth"]
    )
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(meta.router, prefix="/api/v1", tags=["metadata"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(clues.router, prefix="/api/v1", tags=["clues"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    return app


app = create_app()
