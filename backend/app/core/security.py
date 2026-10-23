import hashlib
import hmac
import secrets
from datetime import timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.utils import utcnow


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    s = get_settings()
    expires_in = s.access_token_minutes * 60
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": utcnow(),
        "exp": utcnow() + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), expires_in


def decode_access_token(token: str) -> dict | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == "access" else None


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the cookie, sha256 hash stored in the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Customer invoice-link tokens: "<public_id>.<hmac>" ---------------------------------


def new_public_id() -> str:
    return secrets.token_urlsafe(32)


def _link_signature(public_id: str) -> str:
    key = get_settings().link_secret.encode("utf-8")
    return hmac.new(key, f"invoice-link:{public_id}".encode(), hashlib.sha256).hexdigest()[:40]


def sign_link_token(public_id: str) -> str:
    return f"{public_id}.{_link_signature(public_id)}"


def verify_link_token(token: str) -> str | None:
    """Returns the public_id when the signature is valid."""
    public_id, sep, signature = token.rpartition(".")
    if not sep or not public_id:
        return None
    if not hmac.compare_digest(signature, _link_signature(public_id)):
        return None
    return public_id


def sign_webhook(body: bytes) -> str:
    key = get_settings().webhook_secret.encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()
