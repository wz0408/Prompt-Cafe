from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, String, func
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from app.api.dependencies import get_db, require_admin
from app.db.models import User, AuditLog, CommunityPrompt, CommunityReport, Prompt, PromptVersion, SystemAIConfig

from app.schemas.admin import (
    AdminUpdateUserRequest,
    AdminDisableUserRequest,
    AdminReviewRequest,
    AdminRejectRequest,
    AdminReasonRequest,
    HandleReportRequest,
    AdminUpdatePromptRequest,
    AdminSystemAIConfigRequest,
)
from app.api.routes.ai import AIProviderError, encrypt_api_key, mask_api_key, normalized_base_url, verify_api_key

router = APIRouter()


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _serialize_system_ai_config(config: SystemAIConfig | None) -> dict:
    if not config:
        return {
            "configured": False,
            "provider": None,
            "baseUrl": None,
            "maskedKey": None,
            "defaultModel": None,
            "dailyGuestLimit": 10,
            "isEnabled": False,
            "updatedAt": None,
        }
    return {
        "configured": bool(config.encrypted_api_key),
        "provider": config.provider,
        "baseUrl": config.base_url,
        "maskedKey": config.key_mask,
        "defaultModel": config.default_model,
        "dailyGuestLimit": config.daily_guest_limit or 10,
        "isEnabled": bool(config.is_enabled),
        "updatedAt": config.updated_at,
    }


def _get_default_system_ai_config(db: Session) -> SystemAIConfig | None:
    return (
        db.query(SystemAIConfig)
        .order_by(SystemAIConfig.is_default.desc(), SystemAIConfig.updated_at.desc())
        .first()
    )

def _community_prompt_to_admin_item(item: CommunityPrompt, author: User | None) -> dict:
    author_data = None
    if author:
        author_data = {
            "id": str(author.id),
            "username": author.username,
            "nickname": author.nickname,
        }

    return {
        "id": str(item.id),
        "promptId": str(item.prompt_id) if item.prompt_id else None,
        "userId": str(item.user_id) if item.user_id else None,
        "titleSnapshot": item.title_snapshot,
        "systemPromptSnapshot": item.system_prompt_snapshot,
        "userPromptSnapshot": item.user_prompt_snapshot,
        "tagsSnapshot": item.tags_snapshot or [],
        "description": item.description,
        "status": item.status,
        "reviewedBy": str(item.reviewed_by) if item.reviewed_by else None,
        "reviewedAt": item.reviewed_at,
        "viewCount": item.view_count or 0,
        "favoriteCount": item.favorite_count or 0,
        "auditNote": item.audit_note,
        "createdAt": item.created_at,
        "author": author_data,
    }


def _serialize_author(author: User | None) -> dict | None:
    if not author:
        return None

    return {
        "id": str(author.id),
        "username": author.username,
        "nickname": author.nickname,
    }


def _serialize_prompt_admin_item(prompt: Prompt, author: User | None) -> dict:
    return {
        "id": str(prompt.id),
        "userId": str(prompt.user_id),
        "title": prompt.title,
        "description": prompt.description,
        "systemPrompt": prompt.system_prompt,
        "userPrompt": prompt.user_prompt,
        "variables": prompt.variables or [],
        "tags": prompt.tags or [],
        "visibility": prompt.visibility,
        "currentVersion": prompt.current_version,
        "createdAt": prompt.created_at,
        "updatedAt": prompt.updated_at,
        "author": _serialize_author(author),
    }


def _next_prompt_version_number(db: Session, prompt: Prompt) -> int:
    latest_version_number = (
        db.query(func.max(PromptVersion.version_number))
        .filter(PromptVersion.prompt_id == prompt.id)
        .scalar()
    ) or 0
    return max(prompt.current_version or 0, latest_version_number) + 1


def _serialize_report_item(report: CommunityReport) -> dict:
    return {
        "id": str(report.id),
        "reporterId": str(report.reporter_id) if report.reporter_id else None,
        "communityPromptId": str(report.community_prompt_id),
        "reason": report.reason,
        "description": report.description,
        "status": report.status,
        "handledBy": str(report.handled_by) if report.handled_by else None,
        "handledAt": report.handled_at,
        "handleResult": report.handle_result,
        "createdAt": report.created_at,
    }


def _add_audit_log(
    db: Session,
    request: Request | None,
    admin: User,
    action: str,
    target_type: str,
    target_id: UUID,
    detail: dict | None = None,
):
    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_role=admin.role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    )


@router.get("/ai/system-config")
def get_system_ai_config(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return {"code": 0, "message": "success", "data": _serialize_system_ai_config(_get_default_system_ai_config(db))}


@router.put("/ai/system-config")
def save_system_ai_config(
    payload: AdminSystemAIConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    config = _get_default_system_ai_config(db)
    api_key = (payload.apiKey or "").strip()
    base_url = normalized_base_url(payload.provider, payload.baseUrl.strip() if payload.baseUrl else None)

    provider_changed = bool(config and config.provider != payload.provider)
    base_url_changed = bool(config and config.base_url != base_url)
    if (config is None or provider_changed or base_url_changed) and not api_key:
        raise HTTPException(400, "apiKey is required when creating config or changing provider/baseUrl")

    if api_key:
        try:
            verify_api_key(payload.provider, base_url, api_key)
        except AIProviderError as exc:
            raise HTTPException(422, f"System API Key verification failed: {exc.message}") from exc

    now = datetime.utcnow()
    if config is None:
        config = SystemAIConfig(
            provider=payload.provider,
            base_url=base_url,
            key_mask="",
            encrypted_api_key="",
            default_model=payload.defaultModel.strip(),
            is_default=True,
            is_enabled=payload.isEnabled,
            daily_guest_limit=payload.dailyGuestLimit,
            created_by=admin.id,
            updated_by=admin.id,
            created_at=now,
            updated_at=now,
        )
        db.add(config)
        db.flush()

    db.query(SystemAIConfig).filter(SystemAIConfig.id != config.id).update({"is_default": False})
    config.provider = payload.provider
    config.base_url = base_url
    config.default_model = payload.defaultModel.strip()
    config.daily_guest_limit = payload.dailyGuestLimit
    config.is_enabled = payload.isEnabled
    config.is_default = True
    config.updated_by = admin.id
    config.updated_at = now
    if api_key:
        config.encrypted_api_key = encrypt_api_key(api_key)
        config.key_mask = mask_api_key(api_key)

    _add_audit_log(
        db,
        request,
        admin,
        "admin.ai.system_config.save",
        "system_ai_config",
        config.id,
        {
            "provider": payload.provider,
            "baseUrl": base_url,
            "defaultModel": config.default_model,
            "dailyGuestLimit": config.daily_guest_limit,
            "isEnabled": config.is_enabled,
            "apiKeyUpdated": bool(api_key),
        },
    )
    db.commit()
    db.refresh(config)
    return {"code": 0, "message": "success", "data": _serialize_system_ai_config(config)}


@router.get("/shared-prompts/pending")
def get_pending_community_prompts(
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(CommunityPrompt).filter(CommunityPrompt.status == "pending")

    if keyword:
        kw = keyword.strip()
        if kw:
            like_expr = f"%{kw}%"
            query = query.filter(
                or_(
                    CommunityPrompt.title_snapshot.ilike(like_expr),
                    CommunityPrompt.description.ilike(like_expr),
                    cast(CommunityPrompt.tags_snapshot, String).ilike(like_expr),
                )
            )

    total = query.count()
    items = (
        query.order_by(CommunityPrompt.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    author_ids = {item.user_id for item in items if item.user_id}
    authors = {}
    if author_ids:
        authors = {u.id: u for u in db.query(User).filter(User.id.in_(author_ids)).all()}

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [_community_prompt_to_admin_item(item, authors.get(item.user_id)) for item in items],
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "total": total,
            },
        },
    }


@router.get("/shared-prompts/{communityPromptId}")
def get_admin_community_prompt_detail(
    communityPromptId: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    item = db.query(CommunityPrompt).filter(CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(404, "Community prompt not found")

    author = db.query(User).filter(User.id == item.user_id).first() if item.user_id else None
    return {
        "code": 0,
        "message": "success",
        "data": _community_prompt_to_admin_item(item, author),
    }


@router.post("/shared-prompts/{communityPromptId}/approve")
def approve_community_prompt(
    communityPromptId: UUID,
    request: Request,
    payload: AdminReviewRequest | None = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    item = db.query(CommunityPrompt).filter(CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(404, "Community prompt not found")
    if item.status != "pending":
        raise HTTPException(400, "Only pending prompts can be approved")

    before_status = item.status
    note = payload.auditNote.strip() if payload and payload.auditNote else None

    item.status = "approved"
    item.reviewed_by = admin.id
    item.reviewed_at = datetime.utcnow()
    item.audit_note = note

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="admin.community_prompt.approve",
        target_type="community_prompt",
        target_id=item.id,
        detail={"beforeStatus": before_status, "afterStatus": item.status, "auditNote": note},
    )

    db.commit()
    db.refresh(item)

    author = db.query(User).filter(User.id == item.user_id).first() if item.user_id else None
    return {
        "code": 0,
        "message": "success",
        "data": _community_prompt_to_admin_item(item, author),
    }


@router.post("/shared-prompts/{communityPromptId}/reject")
def reject_community_prompt(
    communityPromptId: UUID,
    payload: AdminRejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    item = db.query(CommunityPrompt).filter(CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(404, "Community prompt not found")
    if item.status != "pending":
        raise HTTPException(400, "Only pending prompts can be rejected")

    note = payload.auditNote.strip()
    if not note:
        raise HTTPException(400, "auditNote is required")

    before_status = item.status
    item.status = "rejected"
    item.reviewed_by = admin.id
    item.reviewed_at = datetime.utcnow()
    item.audit_note = note

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="admin.community_prompt.reject",
        target_type="community_prompt",
        target_id=item.id,
        detail={"beforeStatus": before_status, "afterStatus": item.status, "auditNote": note},
    )

    db.commit()
    db.refresh(item)

    author = db.query(User).filter(User.id == item.user_id).first() if item.user_id else None
    return {
        "code": 0,
        "message": "success",
        "data": _community_prompt_to_admin_item(item, author),
    }


@router.post("/shared-prompts/{communityPromptId}/remove")
def remove_community_prompt(
    communityPromptId: UUID,
    payload: AdminReasonRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    item = db.query(CommunityPrompt).filter(CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(404, "Community prompt not found")

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(400, "reason is required")

    before_status = item.status
    item.status = "removed"
    item.reviewed_by = admin.id
    item.reviewed_at = datetime.utcnow()
    item.audit_note = reason

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="admin.community_prompt.remove",
        target_type="community_prompt",
        target_id=item.id,
        detail={"beforeStatus": before_status, "afterStatus": item.status, "reason": reason},
    )

    db.commit()
    db.refresh(item)

    author = db.query(User).filter(User.id == item.user_id).first() if item.user_id else None
    return {
        "code": 0,
        "message": "success",
        "data": _community_prompt_to_admin_item(item, author),
    }


@router.post("/reports/{reportId}/handle")
def handle_community_report(
    reportId: UUID,
    payload: HandleReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    report = db.query(CommunityReport).filter(CommunityReport.id == reportId).first()
    if not report:
        raise HTTPException(404, "Community report not found")
    if report.status != "pending":
        raise HTTPException(400, "This report has already been handled")

    result = payload.handleResult.strip()
    if not result:
        raise HTTPException(400, "handleResult is required")

    now = datetime.utcnow()
    report.status = payload.status
    report.handled_by = admin.id
    report.handled_at = now
    report.handle_result = result

    removed_prompt_id = None
    if payload.removeCommunityPrompt and payload.status == "processed":
        prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == report.community_prompt_id).first()
        if prompt and prompt.status != "removed":
            prompt.status = "removed"
            prompt.reviewed_by = admin.id
            prompt.reviewed_at = now
            prompt.audit_note = f"Removed while handling report {report.id}: {result}"
            removed_prompt_id = prompt.id

            _add_audit_log(
                db=db,
                request=request,
                admin=admin,
                action="admin.community_prompt.remove_by_report",
                target_type="community_prompt",
                target_id=prompt.id,
                detail={
                    "reportId": str(report.id),
                    "reason": "report_handle_remove",
                    "handleResult": result,
                },
            )

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="admin.community_report.handle",
        target_type="community_report",
        target_id=report.id,
        detail={
            "status": payload.status,
            "handleResult": result,
            "removeCommunityPrompt": payload.removeCommunityPrompt,
            "removedCommunityPromptId": str(removed_prompt_id) if removed_prompt_id else None,
        },
    )

    db.commit()
    db.refresh(report)

    return {
        "code": 0,
        "message": "success",
        "data": _serialize_report_item(report),
    }


@router.get("/reports")
def list_community_reports(
    status: str | None = Query(None),
    communityPromptId: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(CommunityReport)

    if status:
        query = query.filter(CommunityReport.status == status)

    if communityPromptId:
        query = query.filter(CommunityReport.community_prompt_id == communityPromptId)

    total = query.count()
    reports = (
        query.order_by(CommunityReport.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [_serialize_report_item(report) for report in reports],
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "total": total,
            },
        },
    }


@router.get("/users")
def list_users(
    keyword: str | None = Query(None),
    role: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(User)

    if keyword:
        like_expr = f"%{keyword}%"
        query = query.filter(
            or_(
                User.username.ilike(like_expr),
                User.email.ilike(like_expr),
                User.nickname.ilike(like_expr),
            )
        )

    if role:
        query = query.filter(User.role == role)

    if status:
        query = query.filter(User.status == status)

    total = query.count()

    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    items = [
        {
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "status": u.status,
            "nickname": u.nickname,
            "avatarUrl": u.avatar_url,
            "bio": u.bio,
            "lastLoginAt": u.last_login_at,
            "createdAt": u.created_at,
            "updatedAt": u.updated_at,
        }
        for u in users
    ]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "total": total,
            },
        },
    }

@router.get("/users/{userId}")
def get_user_detail(
    userId: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = (
        db.query(User)
        .filter(User.id == userId)
        .first()
    )

    if not user:
        raise HTTPException(404, "User not found")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "nickname": user.nickname,
            "avatarUrl": user.avatar_url,
            "bio": user.bio,
            "lastLoginAt": user.last_login_at,
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        },
    }

@router.patch("/users/{userId}")
def admin_update_user(
    userId: UUID,
    payload: AdminUpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == userId).first()

    if not user:
        raise HTTPException(404, "User not found")
    
    is_self = user.id == admin.id

    if is_self:
        if payload.role == "user":
            raise HTTPException(
                400,
                "You cannot downgrade your own admin role",
            )

        if payload.status == "disabled":
            raise HTTPException(
                400,
                "You cannot disable yourself",
            )
    
    before = {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
    }

    if payload.username is not None:
        if payload.username != user.username:
            username_conflict = (
                db.query(User)
                .filter(User.id != user.id, User.username == payload.username)
                .first()
            )
            if username_conflict:
                raise HTTPException(409, "Username already exists")
        user.username = payload.username

    if payload.email is not None:
        if payload.email != user.email:
            email_conflict = (
                db.query(User)
                .filter(User.id != user.id, User.email == payload.email)
                .first()
            )
            if email_conflict:
                raise HTTPException(409, "Email already exists")
        user.email = payload.email

    if payload.role is not None:
        user.role = payload.role

    if payload.status is not None:
        user.status = payload.status

    if payload.nickname is not None:
        user.nickname = payload.nickname

    if payload.avatarUrl is not None:
        user.avatar_url = payload.avatarUrl

    if payload.bio is not None:
        user.bio = payload.bio
    
    after = {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
    }

    audit = AuditLog(
        actor_id=admin.id,
        actor_role=admin.role,
        action="admin.update_user",
        target_type="user",
        target_id=user.id,
        detail={
            "before": before,
            "after": after,
            "reason": payload.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.add(audit)

    user.updated_at = datetime.utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username or email already exists") from exc
    db.refresh(user)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "nickname": user.nickname,
            "avatarUrl": user.avatar_url,
            "bio": user.bio,
            "lastLoginAt": user.last_login_at,
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        },
    }

@router.patch("/users/{userId}/disable")
def disable_user(
    userId: UUID,
    payload: AdminDisableUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == userId).first()

    if not user:
        raise HTTPException(404, "User not found")

    # ======================================
    # 1. 禁止操作自己
    # ======================================
    if user.id == admin.id:
        raise HTTPException(400, "You cannot disable yourself")

    # ======================================
    # 2. 禁止禁用超级管理员（如果你有这个角色）
    # ======================================
    if user.role == "super_admin":
        raise HTTPException(403, "Cannot disable super admin")

    # ======================================
    # 3. 幂等处理（已经 disabled 直接返回）
    # ======================================
    if user.status == "disabled":
        return {
            "code": 0,
            "message": "success",
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "nickname": user.nickname,
                "avatarUrl": user.avatar_url,
                "bio": user.bio,
                "lastLoginAt": user.last_login_at,
                "createdAt": user.created_at,
                "updatedAt": user.updated_at,
            },
        }

    # ======================================
    # 4. 记录变更前状态
    # ======================================
    before = {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
    }

    # ======================================
    # 5. 执行 disable
    # ======================================
    user.status = "disabled"
    user.updated_at = datetime.utcnow()

    # ======================================
    # 6. 记录 audit log（关键）
    # ======================================
    audit = AuditLog(
        actor_id=admin.id,
        actor_role=admin.role,
        action="user_disable",
        target_type="user",
        target_id=user.id,
        detail={
            "before": before,
            "after": {
                **before,
                "status": "disabled",
            },
            "reason": payload.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.add(audit)

    # ======================================
    # 7. commit + refresh
    # ======================================
    db.commit()
    db.refresh(user)

    # ======================================
    # 8. 返回统一 DTO
    # ======================================
    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "nickname": user.nickname,
            "avatarUrl": user.avatar_url,
            "bio": user.bio,
            "lastLoginAt": user.last_login_at,
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        },
    }

@router.patch("/users/{userId}/restore")
def restore_user(
    userId: UUID,
    payload: AdminDisableUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == userId).first()

    if not user:
        raise HTTPException(404, "User not found")

    # ======================================
    # 1. 禁止恢复自己（保持一致的安全策略）
    # ======================================
    if user.id == admin.id:
        raise HTTPException(400, "You cannot restore yourself")

    # ======================================
    # 2. 幂等处理（已经 active）
    # ======================================
    if user.status == "active":
        return {
            "code": 0,
            "message": "success",
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "nickname": user.nickname,
                "avatarUrl": user.avatar_url,
                "bio": user.bio,
                "lastLoginAt": user.last_login_at,
                "createdAt": user.created_at,
                "updatedAt": user.updated_at,
            },
        }

    # ======================================
    # 3. 记录变更前状态
    # ======================================
    before = {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
    }

    # ======================================
    # 4. 执行 restore
    # ======================================
    user.status = "active"
    user.updated_at = datetime.utcnow()

    # ======================================
    # 5. audit log
    # ======================================
    audit = AuditLog(
        actor_id=admin.id,
        actor_role=admin.role,
        action="user_restore",
        target_type="user",
        target_id=user.id,
        detail={
            "before": before,
            "after": {
                **before,
                "status": "active",
            },
            "reason": payload.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.add(audit)

    # ======================================
    # 6. commit
    # ======================================
    db.commit()
    db.refresh(user)

    # ======================================
    # 7. response DTO
    # ======================================
    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "nickname": user.nickname,
            "avatarUrl": user.avatar_url,
            "bio": user.bio,
            "lastLoginAt": user.last_login_at,
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        },
    }


@router.get("/prompts")
def list_admin_prompts(
    keyword: str | None = Query(None),
    authorId: UUID | None = Query(None),
    visibility: str | None = Query(None),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(Prompt)

    if keyword:
        like_expr = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Prompt.title.ilike(like_expr),
                Prompt.description.ilike(like_expr),
                Prompt.user_prompt.ilike(like_expr),
            )
        )

    if authorId:
        query = query.filter(Prompt.user_id == authorId)

    if visibility:
        query = query.filter(Prompt.visibility == visibility)

    if tag:
        query = query.filter(Prompt.tags.contains([tag]))

    total = query.count()
    prompts = (
        query.order_by(Prompt.updated_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    author_ids = {prompt.user_id for prompt in prompts}
    authors = {}
    if author_ids:
        authors = {user.id: user for user in db.query(User).filter(User.id.in_(author_ids)).all()}

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [_serialize_prompt_admin_item(prompt, authors.get(prompt.user_id)) for prompt in prompts],
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "total": total,
            },
        },
    }


@router.get("/prompts/{promptId}")
def get_admin_prompt_detail(
    promptId: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    prompt = db.query(Prompt).filter(Prompt.id == promptId).first()
    if not prompt:
        raise HTTPException(404, "Prompt not found")

    author = db.query(User).filter(User.id == prompt.user_id).first()
    return {
        "code": 0,
        "message": "success",
        "data": _serialize_prompt_admin_item(prompt, author),
    }


@router.patch("/prompts/{promptId}")
def admin_update_prompt(
    promptId: UUID,
    payload: AdminUpdatePromptRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    prompt = db.query(Prompt).filter(Prompt.id == promptId).first()
    if not prompt:
        raise HTTPException(404, "Prompt not found")

    before = {
        "title": prompt.title,
        "description": prompt.description,
        "systemPrompt": prompt.system_prompt,
        "userPrompt": prompt.user_prompt,
        "variables": prompt.variables or [],
        "tags": prompt.tags or [],
        "visibility": prompt.visibility,
    }

    changed = False

    if payload.title is not None and payload.title != prompt.title:
        prompt.title = payload.title
        changed = True
    if payload.description is not None and payload.description != prompt.description:
        prompt.description = payload.description
        changed = True
    if payload.systemPrompt is not None and payload.systemPrompt != prompt.system_prompt:
        prompt.system_prompt = payload.systemPrompt
        changed = True
    if payload.userPrompt is not None and payload.userPrompt != prompt.user_prompt:
        prompt.user_prompt = payload.userPrompt
        changed = True
    if payload.variables is not None:
        variables_data = [item.model_dump() for item in payload.variables]
        if variables_data != (prompt.variables or []):
            prompt.variables = variables_data
            changed = True
    if payload.tags is not None:
        normalized_tags = [str(tag).strip() for tag in payload.tags if str(tag).strip()]
        if normalized_tags != (prompt.tags or []):
            prompt.tags = normalized_tags
            changed = True
    if payload.visibility is not None and payload.visibility != prompt.visibility:
        prompt.visibility = payload.visibility
        changed = True

    if not changed:
        raise HTTPException(400, "No changes detected")

    new_version_number = _next_prompt_version_number(db, prompt)
    prompt.current_version = new_version_number
    prompt.updated_at = datetime.utcnow()

    db.add(
        PromptVersion(
            prompt_id=prompt.id,
            version_number=new_version_number,
            title=prompt.title,
            description=prompt.description,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            variables=prompt.variables or [],
            tags_snapshot=prompt.tags or [],
            note=payload.reason,
        )
    )

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="admin.update_prompt",
        target_type="prompt",
        target_id=prompt.id,
        detail={
            "before": before,
            "after": {
                "title": prompt.title,
                "description": prompt.description,
                "systemPrompt": prompt.system_prompt,
                "userPrompt": prompt.user_prompt,
                "variables": prompt.variables or [],
                "tags": prompt.tags or [],
                "visibility": prompt.visibility,
            },
            "reason": payload.reason,
        },
    )

    db.commit()
    db.refresh(prompt)

    author = db.query(User).filter(User.id == prompt.user_id).first()
    return {
        "code": 0,
        "message": "success",
        "data": _serialize_prompt_admin_item(prompt, author),
    }


@router.delete("/prompts/{promptId}")
def admin_delete_prompt(
    promptId: UUID,
    payload: AdminReasonRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    prompt = db.query(Prompt).filter(Prompt.id == promptId).first()
    if not prompt:
        raise HTTPException(404, "Prompt not found")

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(400, "reason is required")

    related_community_prompts = db.query(CommunityPrompt).filter(CommunityPrompt.prompt_id == prompt.id).all()
    for community_prompt in related_community_prompts:
        community_prompt.prompt_id = None
        community_prompt.status = "removed"
        community_prompt.reviewed_by = admin.id
        community_prompt.reviewed_at = datetime.utcnow()
        community_prompt.audit_note = reason

    db.query(PromptVersion).filter(PromptVersion.prompt_id == prompt.id).delete()

    _add_audit_log(
        db=db,
        request=request,
        admin=admin,
        action="prompt_delete",
        target_type="prompt",
        target_id=prompt.id,
        detail={
            "reason": reason,
            "communityPromptIds": [str(item.id) for item in related_community_prompts],
        },
    )

    db.delete(prompt)
    db.commit()

    return {
        "code": 0,
        "message": "success",
        "data": {},
    }

@router.get("/audit-logs")
def list_audit_logs(
    actorId: UUID | None = Query(None),
    action: str | None = Query(None),
    targetType: str | None = Query(None),
    targetId: UUID | None = Query(None),
    startTime: datetime | None = Query(None),
    endTime: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(AuditLog)

    # ======================================
    # 1. filters
    # ======================================
    if actorId:
        query = query.filter(AuditLog.actor_id == actorId)

    if action:
        query = query.filter(AuditLog.action == action)

    if targetType:
        query = query.filter(AuditLog.target_type == targetType)

    if targetId:
        query = query.filter(AuditLog.target_id == targetId)

    if startTime:
        query = query.filter(AuditLog.created_at >= _naive_utc(startTime))

    if endTime:
        query = query.filter(AuditLog.created_at <= _naive_utc(endTime))

    # ======================================
    # 2. total
    # ======================================
    total = query.count()

    # ======================================
    # 3. pagination
    # ======================================
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    # ======================================
    # 4. response mapping
    # ======================================
    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "actorId": str(log.actor_id) if log.actor_id else None,
            "actorRole": log.actor_role,
            "action": log.action,
            "targetType": log.target_type,
            "targetId": str(log.target_id),
            "detail": log.detail,
            "ipAddress": log.ip_address,
            "userAgent": log.user_agent,
            "createdAt": log.created_at,
        })

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "total": total,
            },
        },
    }
