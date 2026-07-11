from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from uuid import UUID
from typing import List, Optional, Any, Dict, Literal


class PromptSummary(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    tags: List[str]
    currentVersion: int
    visibility: str
    createdAt: datetime
    updatedAt: datetime


class PromptListData(BaseModel):
    items: list[PromptSummary]
    total: int
    page: int
    pageSize: int


class PromptListResponse(BaseModel):
    data: PromptListData
    error: Any

class PromptVariableDef(BaseModel):
    name: str
    type: Literal["text", "textarea", "number"] = "text"
    description: Optional[str] = None
    required: Optional[bool] = False
    value: Optional[str] = None

class PromptCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)

    description: Optional[str] = None

    systemPrompt: Optional[str] = None
    userPrompt: str

    variables: Optional[List[PromptVariableDef]] = None

    tags: Optional[List[str]] = None

    visibility: Optional[Literal["private", "public"]] = "private"

class PromptDetail(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    tags: Optional[List[str]]

    currentVersion: int
    visibility: str

    createdAt: datetime
    updatedAt: datetime

    systemPrompt: Optional[str]
    userPrompt: str

    variables: Optional[List[PromptVariableDef]]

class ApiResponse(BaseModel):
    data: PromptDetail
    error: Optional[dict] = None

class PromptCopyRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_payload(self):
        if self.title is not None and self.title.strip() == "":
            raise ValueError("title cannot be empty")
        return self

class PromptRenderRequest(BaseModel):
    systemPrompt: Optional[str] = None
    userPrompt: str
    variables: Dict[str, Any] = Field(default_factory=dict)

class PromptRenderData(BaseModel):
    renderedSystemPrompt: Optional[str] = None
    renderedUserPrompt: str

class PromptRenderResponse(BaseModel):
    data: PromptRenderData
    error: Optional[dict] = None

class PromptTagsRequest(BaseModel):
    tags: List[str]

class UpdatePromptRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str | None] = None
    systemPrompt: Optional[str | None] = None
    userPrompt: Optional[str] = None
    variables: Optional[List[PromptVariableDef]] = None
    tags: Optional[List[str]] = None
    visibility: Optional[Literal["private", "public"]] = Field(default=None)
    changeNote: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_payload(self):
        if self.changeNote is not None:
            self.changeNote = self.changeNote.strip() or None

        if not any(
            getattr(self, f) is not None
            for f in [
                "title",
                "description",
                "systemPrompt",
                "userPrompt",
                "variables",
                "tags",
                "visibility",
                "changeNote",
            ]
        ):
            raise ValueError("At least one field must be provided")

        if self.title is not None and self.title.strip() == "":
            raise ValueError("title cannot be empty")

        if self.userPrompt is not None and self.userPrompt.strip() == "":
            raise ValueError("userPrompt cannot be empty")

        return self
