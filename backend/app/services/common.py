"""Cross-cutting helpers: audit trail, staff notifications, document numbering."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models import AuditLog, DocumentCounter, Notification, Role, User


def audit(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    summary: str = "",
    details: dict | None = None,
) -> None:
    """Append an audit entry in the caller's transaction (it commits or rolls back with it)."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else "system",
            actor_role=actor.role_code if actor else "SYSTEM",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            summary=summary,
            details=details,
        )
    )


def notify_user(
    db: Session,
    user_id: int | None,
    type_: str,
    title: str,
    message: str = "",
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    if user_id is None:
        return
    db.add(
        Notification(
            recipient_id=user_id,
            type=type_,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )


def notify_role(
    db: Session,
    role_code: str,
    type_: str,
    title: str,
    message: str = "",
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    user_ids = db.scalars(
        select(User.id).join(Role).where(Role.code == role_code, User.is_active.is_(True))
    ).all()
    for uid in user_ids:
        notify_user(db, uid, type_, title, message, entity_type, entity_id)


def next_number(db: Session, scope: str, prefix: str, width: int = 4, yearly: bool = True) -> str:
    """Allocate the next running number, e.g. SC-2026-0001.

    The upsert takes a row lock on the counter that is held until the surrounding transaction
    ends, so concurrent callers queue up and numbers are unique and gap-free.
    """
    year = utcnow().year if yearly else 0
    stmt = (
        pg_insert(DocumentCounter)
        .values(scope=scope, year=year, last_value=1)
        .on_conflict_do_update(
            index_elements=[DocumentCounter.scope, DocumentCounter.year],
            set_={"last_value": DocumentCounter.last_value + 1},
        )
        .returning(DocumentCounter.last_value)
    )
    value = db.execute(stmt).scalar_one()
    if yearly:
        return f"{prefix}-{year}-{value:0{width}d}"
    return f"{prefix}-{value:0{width}d}"
