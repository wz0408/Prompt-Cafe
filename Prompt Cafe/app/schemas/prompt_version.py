from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID

# 1. 基础版本信息结构 (根据数据库 prompt_versions 表补全)
class PromptVersionInfo(BaseModel):
    id: UUID
    prompt_id: UUID
    version_number: int
    title: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: str
    variables: Optional[Any] = None
    tags_snapshot: Optional[Any] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# 2. GET 历史版本列表 响应结构
class VersionListResponse(BaseModel):
    data: List[PromptVersionInfo]

# 3. POST 手动创建版本快照 请求结构
class VersionCreateRequest(BaseModel):
    note: Optional[str] = Field(None, description="提交前手动保存一个版本的备注", examples=["提交前手动保存一个版本"])

# 4. POST 手动创建版本快照 响应结构
class VersionCreateResponse(BaseModel):
    data: PromptVersionInfo

# 5. GET 比较历史版本差异 响应结构
class VersionDiffData(BaseModel):
    from_version: Optional[PromptVersionInfo] = None
    to_version: Optional[PromptVersionInfo] = None

class VersionDiffResponse(BaseModel):
    data: VersionDiffData

# 6. POST 回溯历史版本 响应结构
class RollbackData(BaseModel):
    message: str
    new_version_id: UUID
    current_version_number: int

class RollbackResponse(BaseModel):
    data: RollbackData