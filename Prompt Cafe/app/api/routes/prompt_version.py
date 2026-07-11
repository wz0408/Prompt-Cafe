from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from uuid import UUID
import uuid

from app.db import models
from app.schemas.prompt_version import (
    VersionListResponse, 
    VersionCreateRequest, 
    VersionCreateResponse,
    VersionDiffResponse,
    RollbackResponse
)
from app.api.dependencies import get_current_user, get_db

router = APIRouter()


def _get_owned_prompt(db: Session, prompt_id: UUID, current_user) -> models.Prompt:
    prompt = db.query(models.Prompt).filter(models.Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if prompt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")
    return prompt


def _next_version_number(db: Session, prompt: models.Prompt) -> int:
    latest_version_number = (
        db.query(func.max(models.PromptVersion.version_number))
        .filter(models.PromptVersion.prompt_id == prompt.id)
        .scalar()
    ) or 0
    return max(prompt.current_version or 0, latest_version_number) + 1


@router.get("/{id}/versions", response_model=VersionListResponse, summary="查看 Prompt 的历史版本列表")
def get_prompt_versions(
    id: UUID = Path(..., description="Prompt ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查看某个 Prompt 的所有历史版本记录，按版本号倒序排列"""
    _get_owned_prompt(db, id, current_user)

    versions = db.query(models.PromptVersion).filter(
        models.PromptVersion.prompt_id == id
    ).order_by(desc(models.PromptVersion.version_number)).all()
    
    return {"data": versions}


@router.post("/{id}/versions", response_model=VersionCreateResponse, summary="手动创建一个版本快照")
def create_prompt_version(
    request: VersionCreateRequest,
    id: UUID = Path(..., description="Prompt ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    根据当前的 Prompt 内容，手动生成一个历史版本快照，
    并将 Prompt 的当前版本号 (current_version) + 1。
    """
    prompt = _get_owned_prompt(db, id, current_user)
    new_version_number = _next_version_number(db, prompt)

    # 创建版本快照
    new_version = models.PromptVersion(
        prompt_id=prompt.id,
        version_number=new_version_number,
        title=prompt.title,
        description=prompt.description,
        system_prompt=prompt.system_prompt,
        user_prompt=prompt.user_prompt,
        variables=prompt.variables or [],
        tags_snapshot=prompt.tags or [],
        note=request.note,
        created_at=datetime.utcnow(),
    )
    db.add(new_version)
    
    # 主表当前版本号始终指向最新快照
    prompt.current_version = new_version_number
    prompt.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(new_version)
    return {"data": new_version}


@router.get("/{id}/versions/diff", response_model=VersionDiffResponse, summary="比较历史版本差异")
def get_version_diff(
    id: UUID = Path(..., description="Prompt ID"),
    from_ver: int = Query(..., alias="from", description="起始版本号"),
    to_ver: int = Query(..., alias="to", description="目标版本号"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取两个指定版本的数据，供前端进行 Diff 对比展示"""
    _get_owned_prompt(db, id, current_user)

    from_version = db.query(models.PromptVersion).filter(
        models.PromptVersion.prompt_id == id,
        models.PromptVersion.version_number == from_ver
    ).first()

    to_version = db.query(models.PromptVersion).filter(
        models.PromptVersion.prompt_id == id,
        models.PromptVersion.version_number == to_ver
    ).first()

    if not from_version or not to_version:
        raise HTTPException(status_code=404, detail="One or both versions not found")

    return {
        "data": {
            "from_version": from_version,
            "to_version": to_version
        }
    }


@router.post("/{id}/versions/{versionId}/rollback", response_model=RollbackResponse, summary="回溯到指定历史版本")
def rollback_prompt_version(
    id: UUID = Path(..., description="Prompt ID"),
    versionId: str = Path(..., description="版本号 或 版本快照的UUID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    回溯逻辑：
    1. 根据 UUID 或版本号查找到旧版本数据
    2. 使用旧版本数据覆盖当前 Prompt 的内容
    3. 生成一条新的版本快照，记录本次回溯动作
    4. 当前 Prompt 版本号 + 1
    """
    prompt = _get_owned_prompt(db, id, current_user)

    # 兼容处理 versionId：尝试解析为 UUID，若失败则视为整数版本号
    target_version = None
    try:
        val_uuid = uuid.UUID(versionId)
        target_version = db.query(models.PromptVersion).filter(
            models.PromptVersion.prompt_id == id,
            models.PromptVersion.id == val_uuid
        ).first()
    except ValueError:
        if versionId.isdigit():
            target_version = db.query(models.PromptVersion).filter(
                models.PromptVersion.prompt_id == id,
                models.PromptVersion.version_number == int(versionId)
            ).first()

    if not target_version:
        raise HTTPException(status_code=404, detail="Target version not found")

    new_version_number = _next_version_number(db, prompt)

    # 覆盖当前 Prompt 内容
    prompt.title = target_version.title
    prompt.description = target_version.description
    prompt.system_prompt = target_version.system_prompt
    prompt.user_prompt = target_version.user_prompt
    prompt.variables = target_version.variables or []
    prompt.tags = target_version.tags_snapshot or []
    
    # 保存覆盖后的状态为一个新版本快照
    rollback_note = f"Rollback to version {target_version.version_number}"
    new_version = models.PromptVersion(
        prompt_id=prompt.id,
        version_number=new_version_number,
        title=prompt.title,
        description=prompt.description,
        system_prompt=prompt.system_prompt,
        user_prompt=prompt.user_prompt,
        variables=prompt.variables or [],
        tags_snapshot=prompt.tags or [],
        note=rollback_note,
        created_at=datetime.utcnow(),
    )
    db.add(new_version)

    # 主表当前版本号始终指向最新快照
    prompt.current_version = new_version_number
    prompt.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(new_version)

    return {
        "data": {
            "message": "Rollback successful",
            "new_version_id": new_version.id,
            "current_version_number": new_version_number
        }
    }
