from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


ReviewStatus = Literal["pending", "approved", "rejected", "removed"]
ReportStatus = Literal["pending", "processed", "rejected"]
ReportReason = Literal["unsafe_content", "copyright", "spam", "privacy", "other"]


class CommunityPromptVariable(BaseModel):
    name: str
    type: Literal["text", "textarea", "select", "number"] = "text"
    label: Optional[str] = None
    required: bool = False
    options: Optional[list[str]] = None
    description: Optional[str] = None
    value: Optional[Any] = None


class CommunityPromptListItem(BaseModel):
    id: UUID
    promptId: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    contentPreview: Optional[str] = None
    tags: list[str]
    authorId: Optional[UUID] = None
    authorName: str
    authorAvatarUrl: Optional[str] = None
    favoriteCount: int
    favorited: bool
    viewCount: int
    publishedAt: datetime


class CommunityPromptDetail(CommunityPromptListItem):
    systemPrompt: Optional[str] = None
    userPrompt: str
    variables: list[CommunityPromptVariable] = Field(default_factory=list)
    usageGuide: Optional[str] = None


class PaginationMeta(BaseModel):
    page: int
    pageSize: int
    total: int


class CommunityPromptListData(BaseModel):
    items: list[CommunityPromptListItem]
    pagination: PaginationMeta


class CommunityPromptListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: CommunityPromptListData


class CommunityPromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: CommunityPromptDetail


class SharePromptRequest(BaseModel):
    promptId: UUID
    title: str = Field(..., max_length=200)
    description: str
    tags: list[str] = Field(default_factory=list)
    usageGuide: str


class SharePromptData(BaseModel):
    shareId: UUID
    promptId: UUID
    title: str
    reviewStatus: ReviewStatus
    submittedAt: datetime


class SharePromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: SharePromptData


class MyShareItem(BaseModel):
    shareId: UUID
    promptId: Optional[UUID] = None
    title: str
    reviewStatus: ReviewStatus
    auditNote: Optional[str] = None
    submittedAt: datetime
    reviewedAt: Optional[datetime] = None


class MyShareListData(BaseModel):
    items: list[MyShareItem]
    pagination: PaginationMeta


class MyShareListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: MyShareListData


class WithdrawShareData(BaseModel):
    shareId: UUID
    withdrawn: bool
    withdrawnAt: datetime


class WithdrawShareResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: WithdrawShareData


class FavoritePromptData(BaseModel):
    communityPromptId: UUID
    favorited: bool
    favoriteCount: int


class FavoritePromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: FavoritePromptData


class CommunityTagItem(BaseModel):
    name: str
    promptCount: int


class CommunityTagListData(BaseModel):
    items: list[CommunityTagItem]


class CommunityTagListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: CommunityTagListData


class ReportCommunityPromptRequest(BaseModel):
    reason: ReportReason
    description: Optional[str] = Field(default=None, max_length=1000)


class ReportCommunityPromptData(BaseModel):
    reportId: UUID
    communityPromptId: UUID
    status: ReportStatus
    submittedAt: datetime


class ReportCommunityPromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ReportCommunityPromptData


class ForkCommunityPromptData(BaseModel):
    promptId: UUID
    sourceCommunityPromptId: UUID
    title: str
    createdAt: datetime


class ForkCommunityPromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ForkCommunityPromptData


class SuccessResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)
