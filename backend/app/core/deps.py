from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    unauthorised = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorised
    payload = decode_access_token(creds.credentials)
    if payload is None:
        raise unauthorised
    user = db.get(User, int(payload["sub"]))
    # Re-checked on every request so deactivation takes effect immediately.
    if user is None or not user.is_active:
        raise unauthorised
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*permissions: str):
    """Dependency: the user must hold at least one of the given permissions."""

    def checker(user: CurrentUser) -> User:
        if not user.permissions.intersection(permissions):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action"
            )
        return user

    return Depends(checker)
