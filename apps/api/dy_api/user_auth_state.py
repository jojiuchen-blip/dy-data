"""Central mutations for authorization-sensitive user scope state."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from apps.api.dy_api.models import User, UserStoreScope


def bump_user_auth_generation(session: Session, user_id: str) -> None:
    """Atomically advance and synchronize one user's authorization generation."""
    user = session.get(User, user_id)
    if user is None:
        return
    result = session.execute(
        update(User)
        .where(User.user_id == user_id)
        .values(auth_generation=User.auth_generation + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RuntimeError("User authorization generation update failed")
    session.expire(user, ["auth_generation"])


def replace_user_store_scopes(
    session: Session, user_id: str, store_ids: list[str]
) -> None:
    """Replace store membership and invalidate prior authorization when it changes."""
    desired_store_ids = set(store_ids)
    current_store_ids = set(
        session.scalars(
            select(UserStoreScope.store_id).where(UserStoreScope.user_id == user_id)
        ).all()
    )
    if current_store_ids == desired_store_ids:
        return

    session.execute(delete(UserStoreScope).where(UserStoreScope.user_id == user_id))
    for store_id in sorted(desired_store_ids):
        session.add(UserStoreScope(user_id=user_id, store_id=store_id))
    session.flush()
    bump_user_auth_generation(session, user_id)
