import re

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal
from typing import List

from app.schemas.prompt import PromptVariableDef


class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[str] = None
    role: Optional[Literal["user", "admin"]] = None
    status: Optional[Literal["active", "disabled"]] = None

    nickname: Optional[str] = Field(None, max_length=50)
    avatarUrl: Optional[str | None] = None
    bio: Optional[str | None] = None

    reason: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, value):
            raise ValueError("Invalid email format")
        return value

class AdminDisableUserRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class AdminReviewRequest(BaseModel):
    auditNote: Optional[str] = Field(None, max_length=500)


class AdminRejectRequest(BaseModel):
    auditNote: str = Field(..., min_length=1, max_length=500)


class AdminReasonRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class HandleReportRequest(BaseModel):
    status: Literal["processed", "rejected"]
    handleResult: str = Field(..., min_length=1, max_length=1000)
    removeCommunityPrompt: bool = False


class AdminSystemAIConfigRequest(BaseModel):
    provider: Literal["openai", "deepseek", "anthropic", "custom"]
    baseUrl: Optional[str | None] = None
    apiKey: Optional[str | None] = None
    defaultModel: str = Field(..., min_length=1, max_length=100)
    dailyGuestLimit: int = Field(default=10, ge=0, le=100000)
    isEnabled: bool = True

    @model_validator(mode="after")
    def validate_payload(self):
        if self.provider == "custom" and not (self.baseUrl or "").strip():
            raise ValueError("baseUrl is required when provider is custom")
        if not self.defaultModel.strip():
            raise ValueError("defaultModel cannot be empty")
        return self


class AdminUpdatePromptRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str | None] = None
    systemPrompt: Optional[str | None] = None
    userPrompt: Optional[str] = None
    variables: Optional[List[PromptVariableDef]] = None
    tags: Optional[list[str]] = None
    visibility: Optional[Literal["private", "public"]] = None
    reason: Optional[str | None] = None

    @model_validator(mode="after")
    def validate_payload(self):
        if not any(
            getattr(self, field_name) is not None
            for field_name in [
                "title",
                "description",
                "systemPrompt",
                "userPrompt",
                "variables",
                "tags",
                "visibility",
            ]
        ):
            raise ValueError("At least one field must be provided")

        if self.title is not None and self.title.strip() == "":
            raise ValueError("title cannot be empty")

        if self.userPrompt is not None and self.userPrompt.strip() == "":
            raise ValueError("userPrompt cannot be empty")

        return self
