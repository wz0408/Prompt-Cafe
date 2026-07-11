from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user, get_db
from app.db import models
from app.schemas.prompt import (
    ApiResponse,
    PromptCopyRequest,
    PromptCreateRequest,
    PromptDetail,
    PromptListResponse,
    PromptRenderRequest,
    PromptRenderResponse,
    PromptTagsRequest,
    UpdatePromptRequest,
)

router = APIRouter()


def _serialize_prompt_detail(
    prompt: models.Prompt,
    version: models.PromptVersion | None = None,
) -> PromptDetail:
    """
    将数据库中的 Prompt ORM 对象转换为接口返回的 PromptDetail。
    如果传入 version，则 systemPrompt / userPrompt / variables 使用版本快照。
    """
    return PromptDetail(
        id=prompt.id,
        title=prompt.title,
        description=prompt.description,
        tags=prompt.tags or [],
        currentVersion=prompt.current_version,
        visibility=prompt.visibility,
        createdAt=prompt.created_at,
        updatedAt=prompt.updated_at,
        systemPrompt=version.system_prompt if version else prompt.system_prompt,
        userPrompt=version.user_prompt if version else prompt.user_prompt,
        variables=(version.variables if version else prompt.variables) or [],
    )


def render_template(template: str, variables: dict) -> str:
    """
    渲染模板变量。
    支持 {{name}} 和 {{ name }} 两种格式。
    如果变量没有传入，则保留原占位符。
    """
    def replace(match: re.Match) -> str:
        name = match.group(1).strip()
        if name not in variables:
            return match.group(0)
        value = variables[name]
        return "" if value is None else str(value)

    return re.sub(r"\{\{\s*([^{}\s]+)\s*\}\}", replace, template)


def normalize_tags(tags: list[str]) -> list[str]:
    """
    清洗标签：去除首尾空格、去除空字符串、去重，并保持原顺序。
    """
    normalized: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        clean_tag = str(tag).strip()
        if not clean_tag or clean_tag in seen:
            continue
        normalized.append(clean_tag)
        seen.add(clean_tag)

    return normalized


def _get_current_version(db: Session, prompt_id: UUID, version_number: int):
    return (
        db.query(models.PromptVersion)
        .filter(
            models.PromptVersion.prompt_id == prompt_id,
            models.PromptVersion.version_number == version_number,
        )
        .first()
    )


def _get_latest_version(db: Session, prompt_id: UUID):
    return (
        db.query(models.PromptVersion)
        .filter(models.PromptVersion.prompt_id == prompt_id)
        .order_by(desc(models.PromptVersion.version_number))
        .first()
    )


def _next_version_number(db: Session, prompt: models.Prompt) -> int:
    latest_version_number = (
        db.query(func.max(models.PromptVersion.version_number))
        .filter(models.PromptVersion.prompt_id == prompt.id)
        .scalar()
    ) or 0
    return max(prompt.current_version or 0, latest_version_number) + 1


def _replace_prompt_body_from_version(prompt: models.Prompt, version: models.PromptVersion) -> None:
    prompt.title = version.title
    prompt.description = version.description
    prompt.system_prompt = version.system_prompt
    prompt.user_prompt = version.user_prompt
    prompt.variables = version.variables or []
    prompt.tags = version.tags_snapshot or []


@router.get("", response_model=PromptListResponse, summary="Get current user's prompts")
def list_my_prompts(
    keyword: Optional[str] = Query(default=None, max_length=200, description="标题模糊搜索"),
    tags: Optional[str] = Query(default=None),
    sortBy: str = Query("updatedAt"),
    sortOrder: str = Query("desc"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    sort_map = {
        "createdAt": models.Prompt.created_at,
        "updatedAt": models.Prompt.updated_at,
        "title": models.Prompt.title,
    }

    if sortBy not in sort_map:
        raise HTTPException(status_code=400, detail="Invalid sortBy")
    if sortOrder not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sortOrder")

    query = db.query(models.Prompt).filter(models.Prompt.user_id == current_user.id)

    if keyword:
        kw = keyword.strip()[:200]
        if kw:
            query = query.filter(
                or_(
                    models.Prompt.title.ilike(f"%{kw}%"),
                    models.Prompt.description.ilike(f"%{kw}%"),
                    models.Prompt.user_prompt.ilike(f"%{kw}%"),
                )
            )

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            query = query.filter(models.Prompt.tags.like(f'%"{tag}"%'))

    total = query.count()
    order_column = sort_map[sortBy]
    query = query.order_by(asc(order_column) if sortOrder == "asc" else desc(order_column))

    prompts = query.offset((page - 1) * pageSize).limit(pageSize).all()
    items = [
        {
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "tags": p.tags or [],
            "currentVersion": p.current_version,
            "visibility": p.visibility,
            "createdAt": p.created_at,
            "updatedAt": p.updated_at,
        }
        for p in prompts
    ]

    return {
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": pageSize,
        },
        "error": None,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    now = datetime.utcnow()
    variables_json = [v.model_dump() for v in payload.variables] if payload.variables else []

    prompt = models.Prompt(
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        system_prompt=payload.systemPrompt,
        user_prompt=payload.userPrompt,
        variables=variables_json,
        tags=payload.tags or [],
        visibility=payload.visibility or "private",
        current_version=1,
        created_at=now,
        updated_at=now,
    )

    db.add(prompt)
    db.flush()

    version = models.PromptVersion(
        prompt_id=prompt.id,
        version_number=1,
        title=prompt.title,
        description=prompt.description,
        system_prompt=prompt.system_prompt,
        user_prompt=prompt.user_prompt,
        variables=variables_json,
        tags_snapshot=prompt.tags or [],
        created_at=now,
    )

    db.add(version)
    db.commit()
    db.refresh(prompt)

    return {
        "data": _serialize_prompt_detail(prompt),
        "error": None,
    }


@router.post("/render", response_model=PromptRenderResponse)
def render_prompt(
    payload: PromptRenderRequest,
    _current_user=Depends(get_current_user),
):
    """
    变量渲染预览。
    不查库、不调用大模型，只根据请求体中的 systemPrompt / userPrompt / variables 做替换。
    """
    rendered_system_prompt = (
        None
        if payload.systemPrompt is None
        else render_template(payload.systemPrompt, payload.variables)
    )

    return {
        "data": {
            "renderedSystemPrompt": rendered_system_prompt,
            "renderedUserPrompt": render_template(payload.userPrompt, payload.variables),
        },
        "error": None,
    }


@router.get("/{id}", response_model=ApiResponse)
def get_prompt_detail(
    id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prompt = db.query(models.Prompt).filter(models.Prompt.id == id).first()

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if prompt.visibility != "public" and prompt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    return {
        "data": _serialize_prompt_detail(prompt),
        "error": None,
    }


@router.put("/{id}", response_model=ApiResponse)
def update_prompt(
    payload: UpdatePromptRequest,
    id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prompt = db.query(models.Prompt).filter(models.Prompt.id == id).first()

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if prompt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    original = {
        "title": prompt.title,
        "description": prompt.description,
        "system_prompt": prompt.system_prompt,
        "user_prompt": prompt.user_prompt,
        "variables": prompt.variables or [],
        "tags": prompt.tags or [],
        "visibility": prompt.visibility,
    }
    variables_json = [var.model_dump() for var in payload.variables] if payload.variables is not None else None
    tags_json = normalize_tags(payload.tags) if payload.tags is not None else None

    if payload.title is not None:
        prompt.title = payload.title
    if payload.description is not None:
        prompt.description = payload.description
    if payload.systemPrompt is not None:
        prompt.system_prompt = payload.systemPrompt
    if payload.userPrompt is not None:
        prompt.user_prompt = payload.userPrompt
    if variables_json is not None:
        prompt.variables = variables_json
    if tags_json is not None:
        prompt.tags = tags_json
        flag_modified(prompt, "tags")
    if payload.visibility is not None:
        prompt.visibility = payload.visibility

    current_changed = any(
        [
            payload.title is not None and payload.title != original["title"],
            payload.description is not None and payload.description != original["description"],
            payload.systemPrompt is not None and payload.systemPrompt != original["system_prompt"],
            payload.userPrompt is not None and payload.userPrompt != original["user_prompt"],
            variables_json is not None and variables_json != original["variables"],
            tags_json is not None and tags_json != original["tags"],
            payload.visibility is not None and payload.visibility != original["visibility"],
            payload.changeNote is not None,
        ]
    )

    if current_changed:
        new_version_number = _next_version_number(db, prompt)
        new_version = models.PromptVersion(
            prompt_id=prompt.id,
            version_number=new_version_number,
            title=prompt.title,
            description=prompt.description,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            variables=prompt.variables or [],
            tags_snapshot=prompt.tags or [],
            note=payload.changeNote,
            created_at=datetime.utcnow(),
        )
        db.add(new_version)
        prompt.current_version = new_version_number
        prompt.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(prompt)

    return {
        "data": _serialize_prompt_detail(prompt),
        "error": None,
    }


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    物理删除当前用户自己的 Prompt。
    删除前先保留社区快照，将 community_prompts.prompt_id 置空；
    再删除对应版本记录，最后删除 Prompt 本体。
    """
    try:
        prompt = (
            db.query(models.Prompt)
            .filter(
                models.Prompt.id == id,
                models.Prompt.user_id == current_user.id,
            )
            .first()
        )

        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        if hasattr(models, "CommunityPrompt") and hasattr(models.CommunityPrompt, "prompt_id"):
            (
                db.query(models.CommunityPrompt)
                .filter(models.CommunityPrompt.prompt_id == prompt.id)
                .update(
                    {models.CommunityPrompt.prompt_id: None},
                    synchronize_session=False,
                )
            )

        db.query(models.PromptVersion).filter(
            models.PromptVersion.prompt_id == prompt.id
        ).delete(synchronize_session=False)

        db.delete(prompt)
        db.commit()

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except Exception:
        db.rollback()
        raise


@router.post("/{id}/copy", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def copy_prompt(
    id: UUID = Path(...),
    payload: PromptCopyRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    复制当前用户自己的 Prompt。
    新 Prompt 为 private，current_version 从 1 开始，同时创建初始版本快照。
    """
    try:
        source_prompt = (
            db.query(models.Prompt)
            .filter(
                models.Prompt.id == id,
                models.Prompt.user_id == current_user.id,
            )
            .first()
        )

        if not source_prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        now = datetime.utcnow()

        raw_title = payload.title.strip() if payload and payload.title else ""
        new_title = raw_title or f"{source_prompt.title} 副本"

        variables = deepcopy(source_prompt.variables or [])
        tags = deepcopy(source_prompt.tags or [])

        new_prompt = models.Prompt(
            user_id=current_user.id,
            title=new_title,
            description=source_prompt.description,
            system_prompt=source_prompt.system_prompt,
            user_prompt=source_prompt.user_prompt,
            variables=variables,
            tags=tags,
            visibility="private",
            current_version=1,
            created_at=now,
            updated_at=now,
        )

        db.add(new_prompt)
        db.flush()

        new_version = models.PromptVersion(
            prompt_id=new_prompt.id,
            version_number=1,
            title=new_prompt.title,
            description=new_prompt.description,
            system_prompt=new_prompt.system_prompt,
            user_prompt=new_prompt.user_prompt,
            variables=deepcopy(new_prompt.variables or []),
            tags_snapshot=deepcopy(new_prompt.tags or []),
            created_at=now,
        )

        db.add(new_version)
        db.commit()
        db.refresh(new_prompt)
        db.refresh(new_version)

        return {
            "data": _serialize_prompt_detail(new_prompt, new_version),
            "error": None,
        }

    except Exception:
        db.rollback()
        raise


@router.put("/{id}/tags", response_model=ApiResponse)
def replace_prompt_tags(
    payload: PromptTagsRequest,
    id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    全量替换当前用户自己的 Prompt 标签。
    """
    try:
        prompt = (
            db.query(models.Prompt)
            .filter(
                models.Prompt.id == id,
                models.Prompt.user_id == current_user.id,
            )
            .first()
        )

        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        prompt.tags = normalize_tags(payload.tags)
        flag_modified(prompt, "tags")
        prompt.updated_at = datetime.utcnow()

        latest_version = _get_latest_version(db, prompt.id)
        if latest_version:
            latest_version.tags_snapshot = prompt.tags
            flag_modified(latest_version, "tags_snapshot")
            prompt.current_version = latest_version.version_number

        db.commit()
        db.refresh(prompt)

        return {
            "data": _serialize_prompt_detail(prompt),
            "error": None,
        }

    except Exception:
        db.rollback()
        raise
