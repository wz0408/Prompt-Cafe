from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import (
    ACCESS_TOKEN_EXPIRE_SECONDS,
    build_auth_tokens,
    create_jwt_token,
    decode_jwt_token,
    get_current_user,
    get_db,
    hash_password,
    revoke_jwt_token,
    verify_password,
)
from app.db import models
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    SuccessResponse,
)
from app.schemas.user import UserRegisterRequest, UserResponse


router = APIRouter()


def _add_audit_log(
    db: Session,
    action: str,
    actor_id: UUID | None,
    actor_role: str | None,
    detail: dict,
) -> None:
    db.add(
        models.AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type="auth",
            target_id=actor_id or UUID("00000000-0000-0000-0000-000000000000"),
            detail=detail,
        )
    )


@router.post("/register", response_model=AuthResponse, summary="Register")
def register(
    request: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    existing_user = db.query(models.User).filter(
        or_(models.User.email == request.email, models.User.username == request.username)
    ).first()
    if existing_user:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": status.HTTP_409_CONFLICT,
                "message": "error",
                "detail": "\u7528\u6237\u540D\u6216\u8005\u90AE\u7BB1\u91CD\u590D",
            },
        )

    new_user = models.User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "code": 0,
        "message": "success",
        "data": build_auth_tokens(new_user),
    }


@router.post("/login", response_model=AuthResponse, summary="Login")
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(
        or_(models.User.email == request.account, models.User.username == request.account)
    ).first()
    if not user or not verify_password(request.password, user.password_hash):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "code": status.HTTP_401_UNAUTHORIZED,
                "message": "error",
                "detail": "\u7528\u6237\u540D\u6216\u8005\u5BC6\u7801\u9519\u8BEF",
            },
        )
    if user.status != "active":
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "code": status.HTTP_403_FORBIDDEN,
                "message": "error",
                "detail": "\u5F53\u524D\u8D26\u53F7\u4E0D\u53EF\u7528",
            },
        )

    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(user)
    _add_audit_log(
        db,
        action="login",
        actor_id=user.id,
        actor_role=user.role,
        detail={"account": request.account},
    )
    db.commit()
    db.refresh(user)

    return {
        "code": 0,
        "message": "success",
        "data": build_auth_tokens(user),
    }


@router.post("/refresh", response_model=RefreshTokenResponse, summary="Refresh access token")
def refresh_access_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_jwt_token(request.refresh_token, expected_type="refresh", db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user_id = payload.get("sub")
    try:
        user_uuid = UUID(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is invalid",
        ) from exc

    user = db.query(models.User).filter(models.User.id == user_uuid).first()
    if not user or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User does not exist or session has expired",
        )

    access_token = create_jwt_token(str(user.id), user.role, "access", ACCESS_TOKEN_EXPIRE_SECONDS)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "accessToken": access_token,
            "accessTokenExpiresIn": ACCESS_TOKEN_EXPIRE_SECONDS,
        },
    }


@router.post("/logout", response_model=SuccessResponse, summary="Logout")
def logout(
    request: Request,
    request_body: RefreshTokenRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        access_token = auth_header[len("Bearer ") :].strip()
        if access_token:
            try:
                revoke_jwt_token(access_token, expected_type="access", db=db)
            except ValueError:
                pass

    if request_body and request_body.refresh_token:
        try:
            revoke_jwt_token(request_body.refresh_token, expected_type="refresh", db=db)
        except ValueError:
            pass

    _add_audit_log(
        db,
        action="logout",
        actor_id=current_user.id,
        actor_role=current_user.role,
        detail={"username": current_user.username},
    )
    db.commit()
    return {"code": 0, "message": "success", "data": {}}


@router.get("/me", response_model=UserResponse, summary="Get current authenticated user")
def get_current_auth_user(current_user: models.User = Depends(get_current_user)):
    return {
        "code": 0,
        "message": "success",
        "data": current_user,
    }
