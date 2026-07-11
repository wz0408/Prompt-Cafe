from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import desc, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, get_auth_context, get_current_user, get_db
from app.db import models
from app.schemas.community import (
    CommunityPromptListResponse,
    CommunityPromptResponse,
    CommunityTagListResponse,
    FavoritePromptResponse,
    ForkCommunityPromptResponse,
    MyShareListResponse,
    ReportCommunityPromptRequest,
    ReportCommunityPromptResponse,
    ReviewStatus,
    SharePromptRequest,
    SharePromptResponse,
    WithdrawShareResponse,
)


router = APIRouter()


def _author_name(user: models.User | None) -> str:
    if not user:
        return "匿名用户"
    return user.nickname or user.username or "匿名用户"


def _optional_user(db: Session, auth_context: AuthContext) -> models.User | None:
    if not auth_context.token_valid or not auth_context.user_id:
        return None
    try:
        user_id = UUID(auth_context.user_id)
    except ValueError:
        return None
    return db.query(models.User).filter(models.User.id == user_id, models.User.status == "active").first()


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean_tag = str(tag).strip()
        if clean_tag and clean_tag not in seen:
            normalized.append(clean_tag)
            seen.add(clean_tag)
    return normalized


def _content_preview(item: models.CommunityPrompt, limit: int = 120) -> str:
    content = item.user_prompt_snapshot.strip()
    return content if len(content) <= limit else f"{content[:limit]}..."


def _favorite_prompt_ids(db: Session, user: models.User | None, item_ids: list[UUID]) -> set[UUID]:
    if not user or not item_ids:
        return set()
    favorites = (
        db.query(models.UserFavorite.community_prompt_id)
        .filter(
            models.UserFavorite.user_id == user.id,
            models.UserFavorite.community_prompt_id.in_(item_ids),
        )
        .all()
    )
    return {favorite_id for (favorite_id,) in favorites}


def _to_list_item(item: models.CommunityPrompt, author: models.User | None, favorited: bool) -> dict:
    return {
        "id": item.id,
        "promptId": item.prompt_id,
        "title": item.title_snapshot,
        "description": item.description,
        "contentPreview": _content_preview(item),
        "tags": item.tags_snapshot or [],
        "authorId": item.user_id,
        "authorName": _author_name(author),
        "authorAvatarUrl": author.avatar_url if author else None,
        "favoriteCount": item.favorite_count or 0,
        "favorited": favorited,
        "viewCount": item.view_count or 0,
        "publishedAt": item.reviewed_at or item.created_at,
    }


def _community_variables(db: Session, item: models.CommunityPrompt) -> list[dict]:
    if not item.prompt_id:
        return []
    prompt = db.query(models.Prompt).filter(models.Prompt.id == item.prompt_id).first()
    return deepcopy(prompt.variables or []) if prompt else []


def _to_detail_item(
    db: Session,
    item: models.CommunityPrompt,
    author: models.User | None,
    favorited: bool,
) -> dict:
    detail = _to_list_item(item, author, favorited)
    detail.update(
        {
            "systemPrompt": item.system_prompt_snapshot,
            "userPrompt": item.user_prompt_snapshot,
            "variables": _community_variables(db, item),
            "usageGuide": item.usage_guide,
        }
    )
    return detail


def _query_visible_prompts(db: Session):
    return db.query(models.CommunityPrompt).filter(models.CommunityPrompt.status == "approved")


def _tag_condition(tag: str):
    tag_items = func.json_each(models.CommunityPrompt.tags_snapshot).table_valued("value").alias()
    return exists(select(1).select_from(tag_items).where(tag_items.c.value == tag))


def _tag_keyword_condition(keyword: str):
    tag_items = func.json_each(models.CommunityPrompt.tags_snapshot).table_valued("value").alias()
    return exists(select(1).select_from(tag_items).where(tag_items.c.value.ilike(f"%{keyword}%")))


def _filter_tags(query, tags: Optional[str]):
    if not tags:
        return query
    for tag in _normalize_tags(tags.split(",")):
        query = query.filter(_tag_condition(tag))
    return query


def _list_response(
    db: Session,
    query,
    page: int,
    page_size: int,
    current_user: models.User | None = None,
) -> dict:
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    author_ids = {item.user_id for item in items if item.user_id}
    authors = (
        {user.id: user for user in db.query(models.User).filter(models.User.id.in_(author_ids)).all()}
        if author_ids
        else {}
    )
    favorites = _favorite_prompt_ids(db, current_user, [item.id for item in items])

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                _to_list_item(item, authors.get(item.user_id), item.id in favorites)
                for item in items
            ],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
            },
        },
    }


@router.get("/prompts", response_model=CommunityPromptListResponse)
def get_community_prompts(
    keyword: Optional[str] = Query(default=None, max_length=200),
    tags: Optional[str] = Query(default=None),
    sort: str = Query("latest"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    query = _query_visible_prompts(db)

    if keyword:
        kw = keyword.strip()[:200]
        if kw:
            query = query.filter(
                or_(
                    models.CommunityPrompt.title_snapshot.ilike(f"%{kw}%"),
                    models.CommunityPrompt.description.ilike(f"%{kw}%"),
                    models.CommunityPrompt.user_prompt_snapshot.ilike(f"%{kw}%"),
                    _tag_keyword_condition(kw),
                )
            )

    query = _filter_tags(query, tags)

    if sort == "favoriteCount":
        query = query.order_by(desc(models.CommunityPrompt.favorite_count), desc(models.CommunityPrompt.created_at))
    elif sort == "hot":
        query = query.order_by(
            desc((models.CommunityPrompt.favorite_count * 2) + models.CommunityPrompt.view_count),
            desc(models.CommunityPrompt.created_at),
        )
    elif sort == "latest":
        query = query.order_by(desc(models.CommunityPrompt.reviewed_at), desc(models.CommunityPrompt.created_at))
    else:
        raise HTTPException(status_code=400, detail="Invalid sort")

    return _list_response(db, query, page, pageSize, _optional_user(db, auth_context))


@router.get("/favorites", response_model=CommunityPromptListResponse)
def get_favorite_community_prompts(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = (
        _query_visible_prompts(db)
        .join(
            models.UserFavorite,
            models.UserFavorite.community_prompt_id == models.CommunityPrompt.id,
        )
        .filter(models.UserFavorite.user_id == current_user.id)
        .order_by(desc(models.UserFavorite.created_at))
    )
    return _list_response(db, query, page, pageSize, current_user)


@router.get("/prompts/{communityPromptId}", response_model=CommunityPromptResponse)
def get_community_prompt_detail(
    communityPromptId: UUID = Path(...),
    db: Session = Depends(get_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    item = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    item.view_count = (item.view_count or 0) + 1
    db.commit()
    db.refresh(item)

    current_user = _optional_user(db, auth_context)
    favorites = _favorite_prompt_ids(db, current_user, [item.id])
    author = db.query(models.User).filter(models.User.id == item.user_id).first() if item.user_id else None
    return {
        "code": 0,
        "message": "success",
        "data": _to_detail_item(db, item, author, item.id in favorites),
    }


@router.post("/shares", response_model=SharePromptResponse, status_code=status.HTTP_201_CREATED)
def share_prompt(
    payload: SharePromptRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prompt = db.query(models.Prompt).filter(models.Prompt.id == payload.promptId).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if prompt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    title = payload.title.strip()
    description = payload.description.strip()
    usage_guide = payload.usageGuide.strip()
    tags = _normalize_tags(payload.tags)
    if not title or not description or not usage_guide:
        raise HTTPException(status_code=400, detail="title, description and usageGuide are required")

    existing = (
        db.query(models.CommunityPrompt)
        .filter(
            models.CommunityPrompt.prompt_id == prompt.id,
            models.CommunityPrompt.status.in_(("pending", "approved")),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="This prompt already has an active community share")

    share = models.CommunityPrompt(
        prompt_id=prompt.id,
        user_id=current_user.id,
        title_snapshot=title,
        system_prompt_snapshot=prompt.system_prompt,
        user_prompt_snapshot=prompt.user_prompt,
        tags_snapshot=tags,
        description=description,
        usage_guide=usage_guide,
        status="pending",
        favorite_count=0,
        view_count=0,
        created_at=datetime.utcnow(),
    )
    db.add(share)
    db.commit()
    db.refresh(share)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "shareId": share.id,
            "promptId": share.prompt_id,
            "title": share.title_snapshot,
            "reviewStatus": share.status,
            "submittedAt": share.created_at,
        },
    }


@router.get("/shares/my", response_model=MyShareListResponse)
def get_my_community_shares(
    reviewStatus: Optional[ReviewStatus] = Query(default=None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(models.CommunityPrompt).filter(models.CommunityPrompt.user_id == current_user.id)
    if reviewStatus:
        query = query.filter(models.CommunityPrompt.status == reviewStatus)

    total = query.count()
    items = (
        query.order_by(desc(models.CommunityPrompt.created_at))
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "shareId": item.id,
                    "promptId": item.prompt_id,
                    "title": item.title_snapshot,
                    "reviewStatus": item.status,
                    "auditNote": item.audit_note,
                    "submittedAt": item.created_at,
                    "reviewedAt": item.reviewed_at,
                }
                for item in items
            ],
            "pagination": {"page": page, "pageSize": pageSize, "total": total},
        },
    }


@router.delete("/shares/{shareId}", response_model=WithdrawShareResponse)
def withdraw_community_share(
    shareId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    share = db.query(models.CommunityPrompt).filter(models.CommunityPrompt.id == shareId).first()
    if not share:
        raise HTTPException(status_code=404, detail="Community share not found")
    if share.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")
    if share.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending shares can be withdrawn")

    withdrawn_at = datetime.utcnow()
    db.delete(share)
    db.commit()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "shareId": shareId,
            "withdrawn": True,
            "withdrawnAt": withdrawn_at,
        },
    }


@router.post("/prompts/{communityPromptId}/favorite", response_model=FavoritePromptResponse)
def favorite_prompt(
    communityPromptId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    try:
        db.add(models.UserFavorite(user_id=current_user.id, community_prompt_id=communityPromptId))
        db.flush()
        (
            db.query(models.CommunityPrompt)
            .filter(models.CommunityPrompt.id == communityPromptId)
            .update(
                {
                    models.CommunityPrompt.favorite_count:
                        func.coalesce(models.CommunityPrompt.favorite_count, 0) + 1
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except IntegrityError:
        # The unique index makes repeated or concurrent favorite requests idempotent.
        db.rollback()

    item = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "communityPromptId": item.id,
            "favorited": True,
            "favoriteCount": item.favorite_count or 0,
        },
    }


@router.delete("/prompts/{communityPromptId}/favorite", response_model=FavoritePromptResponse)
def unfavorite_prompt(
    communityPromptId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    deleted_count = (
        db.query(models.UserFavorite)
        .filter(
            models.UserFavorite.user_id == current_user.id,
            models.UserFavorite.community_prompt_id == communityPromptId,
        )
        .delete(synchronize_session=False)
    )
    if deleted_count:
        (
            db.query(models.CommunityPrompt)
            .filter(models.CommunityPrompt.id == communityPromptId)
            .update(
                {
                    models.CommunityPrompt.favorite_count:
                        func.max(0, func.coalesce(models.CommunityPrompt.favorite_count, 0) - 1)
                },
                synchronize_session=False,
            )
        )
        db.commit()

    db.refresh(item)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "communityPromptId": item.id,
            "favorited": False,
            "favoriteCount": item.favorite_count or 0,
        },
    }


@router.get("/tags", response_model=CommunityTagListResponse)
def get_community_tags(
    keyword: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    tag_keyword = keyword.strip().lower() if keyword else ""
    counts: Counter[str] = Counter()
    rows = _query_visible_prompts(db).all()
    for item in rows:
        for tag in _normalize_tags(item.tags_snapshot or []):
            if not tag_keyword or tag_keyword in tag.lower():
                counts[tag] += 1

    items = [
        {"name": tag, "promptCount": count}
        for tag, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]
    return {"code": 0, "message": "success", "data": {"items": items}}


@router.get("/tags/{tag}/prompts", response_model=CommunityPromptListResponse)
def search_community_by_tag(
    tag: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    clean_tag = tag.strip()
    if not clean_tag:
        raise HTTPException(status_code=400, detail="tag is required")
    query = (
        _query_visible_prompts(db)
        .filter(_tag_condition(clean_tag))
        .order_by(desc(models.CommunityPrompt.created_at))
    )
    return _list_response(db, query, page, pageSize, _optional_user(db, auth_context))


@router.post(
    "/prompts/{communityPromptId}/reports",
    response_model=ReportCommunityPromptResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_community_prompt(
    payload: ReportCommunityPromptRequest,
    request: Request,
    communityPromptId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not item:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    duplicate = (
        db.query(models.CommunityReport)
        .filter(
            models.CommunityReport.reporter_id == current_user.id,
            models.CommunityReport.community_prompt_id == communityPromptId,
            models.CommunityReport.status == "pending",
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="You have already reported this prompt")

    now = datetime.utcnow()
    report = models.CommunityReport(
        reporter_id=current_user.id,
        community_prompt_id=communityPromptId,
        reason=payload.reason,
        description=payload.description,
        status="pending",
        created_at=now,
    )
    db.add(report)
    db.add(
        models.AuditLog(
            actor_id=current_user.id,
            actor_role=current_user.role,
            action="community.report",
            target_type="community_prompt",
            target_id=communityPromptId,
            detail={"reason": payload.reason, "description": payload.description},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()
    db.refresh(report)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "reportId": report.id,
            "communityPromptId": report.community_prompt_id,
            "status": report.status,
            "submittedAt": report.created_at,
        },
    }


@router.post(
    "/prompts/{communityPromptId}/fork",
    response_model=ForkCommunityPromptResponse,
    status_code=status.HTTP_201_CREATED,
)
def fork_community_prompt(
    communityPromptId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    source = _query_visible_prompts(db).filter(models.CommunityPrompt.id == communityPromptId).first()
    if not source:
        raise HTTPException(status_code=404, detail="Community prompt not found")

    now = datetime.utcnow()
    title = f"{source.title_snapshot} - 副本"
    variables = _community_variables(db, source)
    prompt = models.Prompt(
        user_id=current_user.id,
        title=title,
        description=source.description,
        system_prompt=source.system_prompt_snapshot,
        user_prompt=source.user_prompt_snapshot,
        variables=deepcopy(variables),
        tags=deepcopy(source.tags_snapshot or []),
        visibility="private",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(prompt)
    db.flush()
    db.add(
        models.PromptVersion(
            prompt_id=prompt.id,
            version_number=1,
            title=prompt.title,
            description=prompt.description,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            variables=deepcopy(prompt.variables or []),
            tags_snapshot=deepcopy(prompt.tags or []),
            created_at=now,
        )
    )
    db.commit()
    db.refresh(prompt)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "promptId": prompt.id,
            "sourceCommunityPromptId": source.id,
            "title": prompt.title,
            "createdAt": prompt.created_at,
        },
    }
