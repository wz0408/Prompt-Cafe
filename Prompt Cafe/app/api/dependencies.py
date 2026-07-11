import base64
import hashlib
import hmac
import json
import os
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import SessionLocal


ACCESS_TOKEN_EXPIRE_SECONDS = 3600
REFRESH_TOKEN_EXPIRE_SECONDS = 2592000
DEFAULT_JWT_SECRET_KEY = "prompt-cafe-dev-secret"
JWT_SECRET_KEY = os.getenv("PROMPT_CAFE_JWT_SECRET", DEFAULT_JWT_SECRET_KEY)
APP_ENV = os.getenv("PROMPT_CAFE_ENV", os.getenv("APP_ENV", os.getenv("ENV", ""))).lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}
if IS_PRODUCTION and JWT_SECRET_KEY == DEFAULT_JWT_SECRET_KEY:
    raise RuntimeError("PROMPT_CAFE_JWT_SECRET must be configured in production")
if JWT_SECRET_KEY == DEFAULT_JWT_SECRET_KEY:
    warnings.warn(
        "PROMPT_CAFE_JWT_SECRET is not configured; using the development JWT secret.",
        RuntimeWarning,
        stacklevel=2,
    )
JWT_ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)
PASSWORD_HASH_ITERATIONS = 100000
REVOKED_ACCESS_TOKENS: set[str] = set()
REVOKED_REFRESH_TOKENS: set[str] = set()


@dataclass
class AuthContext:
    is_guest: bool
    token_valid: bool
    user_id: str | None = None
    role: str = "guest"
    token_type: str | None = None
    token_error: str | None = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = hashed_password.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(derived.hex(), digest_hex)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _utc_from_timestamp(value: int | float) -> datetime:
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)


def _is_token_revoked(jti: str, db: Session | None = None) -> bool:
    if jti in REVOKED_ACCESS_TOKENS or jti in REVOKED_REFRESH_TOKENS:
        return True

    owns_session = db is None
    session = db or SessionLocal()
    try:
        return session.query(models.RevokedToken).filter(models.RevokedToken.jti == jti).first() is not None
    finally:
        if owns_session:
            session.close()


def _store_revoked_token(payload: dict[str, Any], db: Session | None = None) -> None:
    jti = payload.get("jti")
    token_type = payload.get("tokenType")
    exp = payload.get("exp")
    if not jti or not token_type or exp is None:
        return

    owns_session = db is None
    session = db or SessionLocal()
    try:
        existing = session.query(models.RevokedToken).filter(models.RevokedToken.jti == jti).first()
        if existing:
            return

        user_id = None
        subject = payload.get("sub")
        if subject:
            try:
                user_id = uuid.UUID(str(subject))
            except ValueError:
                user_id = None

        session.add(
            models.RevokedToken(
                jti=str(jti),
                token_type=str(token_type),
                user_id=user_id,
                expires_at=_utc_from_timestamp(exp),
                revoked_at=datetime.utcnow(),
            )
        )
        if owns_session:
            session.commit()
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def create_jwt_token(subject: str, role: str, token_type: Literal["access", "refresh"], expires_in: int) -> str:
    now = datetime.now(timezone.utc)
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": subject,
        "role": role,
        "tokenType": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": str(uuid.uuid4()),
    }

    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), default=_json_default).encode("utf-8")
    )
    signature = hmac.new(
        JWT_SECRET_KEY.encode("utf-8"),
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = _b64url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def decode_jwt_token(
    token: str,
    expected_type: Literal["access", "refresh"] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Malformed token") from exc

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_signature = hmac.new(
        JWT_SECRET_KEY.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise ValueError("Invalid token signature")

    payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    exp = payload.get("exp")
    if exp is None or datetime.now(timezone.utc).timestamp() >= exp:
        raise ValueError("Token expired")

    token_type = payload.get("tokenType")
    if expected_type and token_type != expected_type:
        raise ValueError("Unexpected token type")

    jti = payload.get("jti")
    if jti and _is_token_revoked(str(jti), db):
        raise ValueError("Token has been revoked")

    return payload


def build_auth_tokens(user: models.User) -> dict[str, Any]:
    subject = str(user.id)
    return {
        "accessToken": create_jwt_token(subject, user.role, "access", ACCESS_TOKEN_EXPIRE_SECONDS),
        "refreshToken": create_jwt_token(subject, user.role, "refresh", REFRESH_TOKEN_EXPIRE_SECONDS),
        "accessTokenExpiresIn": ACCESS_TOKEN_EXPIRE_SECONDS,
        "refreshTokenExpiresIn": REFRESH_TOKEN_EXPIRE_SECONDS,
        "user": user,
    }


def revoke_jwt_token(
    token: str,
    expected_type: Literal["access", "refresh"] | None = None,
    db: Session | None = None,
) -> None:
    payload = decode_jwt_token(token, expected_type=expected_type, db=db)
    jti = payload.get("jti")
    token_type = payload.get("tokenType")
    if not jti or not token_type:
        return
    if token_type == "access":
        REVOKED_ACCESS_TOKENS.add(jti)
    elif token_type == "refresh":
        REVOKED_REFRESH_TOKENS.add(jti)
    _store_revoked_token(payload, db)


def load_auth_context(request: Request) -> AuthContext:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return AuthContext(is_guest=True, token_valid=False, token_error="Missing bearer token")

    token = auth_header[len("Bearer ") :].strip()
    if not token:
        return AuthContext(is_guest=True, token_valid=False, token_error="Empty bearer token")

    try:
        payload = decode_jwt_token(token, expected_type="access")
    except ValueError as exc:
        return AuthContext(is_guest=True, token_valid=False, token_error=str(exc))

    return AuthContext(
        is_guest=False,
        token_valid=True,
        user_id=payload.get("sub"),
        role=payload.get("role", "user"),
        token_type=payload.get("tokenType"),
    )


def load_auth_context_from_token(token: str | None) -> AuthContext:
    if not token:
        return AuthContext(is_guest=True, token_valid=False, token_error="Missing bearer token")

    token = token.strip()
    if not token:
        return AuthContext(is_guest=True, token_valid=False, token_error="Empty bearer token")

    try:
        payload = decode_jwt_token(token, expected_type="access")
    except ValueError as exc:
        return AuthContext(is_guest=True, token_valid=False, token_error=str(exc))

    return AuthContext(
        is_guest=False,
        token_valid=True,
        user_id=payload.get("sub"),
        role=payload.get("role", "user"),
        token_type=payload.get("tokenType"),
    )


async def auth_context_middleware(request: Request, call_next):
    request.state.auth_context = load_auth_context(request)
    response = await call_next(request)
    return response


def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthContext:
    context = getattr(request.state, "auth_context", None)
    if context is None:
        context = load_auth_context_from_token(credentials.credentials if credentials else None)
        request.state.auth_context = context
    return context


def get_current_user(
    auth_context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> models.User:
    if auth_context.is_guest or not auth_context.token_valid or not auth_context.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required or token is invalid",
        )

    try:
        user_id = uuid.UUID(auth_context.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is invalid",
        ) from exc

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User does not exist or session has expired",
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current account is unavailable",
        )
    return user

def require_admin(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin privilege required")
    return user
