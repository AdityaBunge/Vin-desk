from datetime import timedelta

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import DB, CurrentUser
from app.core.rate_limit import client_ip, limiter
from app.core.security import create_access_token, hash_token, new_refresh_token, verify_password
from app.core.utils import utcnow
from app.models import RefreshToken, User
from app.models.enums import RoleCode
from app.schemas.admin import LoginIn, MeOut, TokenOut
from app.services.common import audit

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "fsc_refresh"
INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
MECHANIC_NO_LOGIN = HTTPException(
    status.HTTP_403_FORBIDDEN,
    "Mechanics do not sign in to Vin Desk. The Service Manager records inspections and work on job cards.",
)


def me_out(user: User) -> MeOut:
    return MeOut.model_validate(user).model_copy(update={"permissions": sorted(user.permissions)})


def _issue(db, user: User, response: Response) -> TokenOut:
    s = get_settings()
    raw, token_hash = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=utcnow() + timedelta(days=s.refresh_token_days)))
    # httpOnly + SameSite=Strict: unreadable by scripts and never sent on cross-site requests.
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=s.refresh_token_days * 86400, httponly=True, samesite="strict",
        secure=s.is_production, path="/api/auth",
    )
    access, expires_in = create_access_token(user.id, user.role_code)
    return TokenOut(access_token=access, expires_in=expires_in, user=me_out(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    s = get_settings()
    limiter.check(f"login:{client_ip(request)}", s.login_rate_limit_per_minute)
    limiter.check(f"login-user:{body.email.lower()}", s.login_rate_limit_per_minute)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise INVALID
    if not user.is_active:
        raise INVALID
    if user.is_demo and s.is_production:
        # Demo accounts have published passwords; they can never be used in production.
        raise INVALID
    if user.role_code == RoleCode.MECHANIC:
        raise MECHANIC_NO_LOGIN
    user.last_login_at = utcnow()
    audit(db, user, "auth.login", "user", user.id, "Signed in")
    token = _issue(db, user, response)
    db.commit()
    return token


@router.post("/refresh", response_model=TokenOut)
def refresh(response: Response, db: DB, fsc_refresh: str | None = Cookie(default=None)):
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; please sign in again")
    if not fsc_refresh:
        raise unauthorised
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(fsc_refresh)).with_for_update())
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        raise unauthorised
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or (user.is_demo and get_settings().is_production):
        raise unauthorised
    if user.role_code == RoleCode.MECHANIC:
        raise unauthorised  # mechanics do not use the software
    row.revoked_at = utcnow()  # rotate: each refresh token is single-use
    token = _issue(db, user, response)
    db.commit()
    return token


@router.post("/logout", status_code=204)
def logout(response: Response, db: DB, fsc_refresh: str | None = Cookie(default=None)):
    if fsc_refresh:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(fsc_refresh)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser):
    return me_out(user)
