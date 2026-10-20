"""HTTP boundary for read-only analytical publications.

Authorization stays in each business route. Resolving an ID never grants a
data scope, schedules work, or silently substitutes a newer publication.
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError


@contextmanager
def publication_read(session, module: str, publication_id: str | None = None):
    from apps.api.dy_api.dashboard_publications.lifecycle import (
        PublicationError,
        resolve_publication,
    )

    if session is None:
        raise HTTPException(503, detail={
            "code": "DATABASE_UNAVAILABLE", "message": "数据库暂不可用",
        })
    try:
        publication = resolve_publication(session, module, publication_id)
        yield publication
    except PublicationError as exc:
        raise HTTPException(exc.http_status, detail={
            "code": exc.code, "message": str(exc),
        }) from exc
    except DBAPIError as exc:
        session.rollback()
        raise HTTPException(503, detail={
            "code": "PUBLICATION_QUERY_UNAVAILABLE",
            "message": "已发布数据暂时无法读取，请稍后重试",
        }) from exc


def attach_publication(payload: dict, publication) -> dict:
    payload.setdefault("meta", {})["publication"] = publication.meta()
    return payload
