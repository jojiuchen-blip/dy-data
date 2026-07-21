"""Central mutations for authorization-sensitive user scope state."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import User, UserStoreScope


def bump_user_auth_generation(session: Session, user_id: str) -> None:
    """Advance one user's authorization generation inside the current transaction."""
    user = session.get(User, user_id)
    if user is not None:
        user.auth_generation = (user.auth_generation or 1) + 1


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
    if not desired_store_ids:
        # Bulk deletes bypass ORM membership events, so an empty replacement
        # needs an explicit authorization-generation increment.
        bump_user_auth_generation(session, user_id)
    session.flush()
