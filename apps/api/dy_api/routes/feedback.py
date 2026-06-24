from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import generated_at, get_session_dependency
from dy_api.schemas import (
    FeedbackSubmissionRequest,
    FeedbackSubmissionResponseData,
    dump_model,
)
from apps.api.dy_api.models import UserFeedbackSubmission


router = APIRouter()


@router.post("/feedback")
def submit_feedback(
    payload: FeedbackSubmissionRequest,
    current_user: AuthContext = Depends(get_current_user),
    session=Depends(get_session_dependency),
):
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )

    now = generated_at()
    row = UserFeedbackSubmission(
        feedback_id=uuid4().hex,
        category=payload.category,
        content=payload.content,
        contact=payload.contact,
        page_path=payload.page_path,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role,
        status="new",
        created_at=now,
    )
    session.add(row)
    session.commit()

    data = FeedbackSubmissionResponseData(
        feedback_id=row.feedback_id,
        category=row.category,
        status=row.status,
        created_at=row.created_at,
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
