from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


AIProvider = Literal["openai", "deepseek", "anthropic", "custom"]


class TokenUsage(BaseModel):
    promptTokens: int = 0
    completionTokens: int = 0
    totalTokens: int = 0


class Pagination(BaseModel):
    page: int
    pageSize: int
    total: int


class AIGuestQuotaData(BaseModel):
    dailyLimit: int
    usedCount: int
    remainingCount: int
    resetAt: datetime
    allowed: bool


class AIGuestQuotaResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIGuestQuotaData


class AIGuestConfigData(BaseModel):
    configured: bool
    provider: AIProvider | None = None
    defaultModel: str | None = None
    dailyLimit: int
    remainingCount: int
    allowed: bool


class AIGuestConfigResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIGuestConfigData


class AISaveApiKeyRequest(BaseModel):
    apiKey: str = Field(..., min_length=1, max_length=500)
    provider: AIProvider
    baseUrl: HttpUrl | None = None
    defaultModel: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("apiKey")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("apiKey cannot be empty")
        return value

    @field_validator("defaultModel")
    @classmethod
    def validate_default_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("defaultModel cannot be empty")
        return value

    @model_validator(mode="after")
    def require_custom_config(self):
        if self.provider == "custom" and self.baseUrl is None:
            raise ValueError("baseUrl is required when provider is custom")
        if self.provider == "custom" and self.defaultModel is None:
            raise ValueError("defaultModel is required when provider is custom")
        return self


class AIApiKeyStatusData(BaseModel):
    configured: bool
    saved: bool | None = None
    maskedKey: str | None = None
    provider: AIProvider | None
    baseUrl: str | None = None
    defaultModel: str | None = None
    verified: bool
    updatedAt: datetime | None = None


class AIApiKeyStatusResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIApiKeyStatusData


class AIDeleteApiKeyData(BaseModel):
    deleted: bool
    deletedAt: datetime


class AIDeleteApiKeyResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIDeleteApiKeyData


class AIModelProviderItem(BaseModel):
    provider: str
    models: list[str]


class AIModelListData(BaseModel):
    items: list[AIModelProviderItem]


class AIModelListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIModelListData


class AIPolishPromptRequest(BaseModel):
    promptId: UUID | None = None
    content: str | None = Field(default=None, max_length=20000)
    provider: AIProvider | None = None
    model: str | None = Field(default=None, min_length=1, max_length=100)
    tone: Literal["formal", "casual", "concise", "academic", "creative"] | None = None
    language: Literal["zh-CN", "en-US"] | None = None
    lengthPreference: Literal["short", "medium", "long"] | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("model cannot be empty")
        return value

    @model_validator(mode="after")
    def require_prompt_or_content(self):
        if self.promptId is None and not (self.content and self.content.strip()):
            raise ValueError("promptId and content cannot both be empty")
        return self


class AIPolishPromptData(BaseModel):
    original: str
    optimized: str
    suggestions: list[str]
    provider: str
    model: str
    latencyMs: int


class AIPolishPromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AIPolishPromptData


class AITestPromptRequest(BaseModel):
    promptId: UUID | None = None
    content: str = Field(..., min_length=1, max_length=20000)
    variables: dict[str, str] = Field(default_factory=dict)
    provider: AIProvider | None = None
    model: str = Field(..., min_length=1, max_length=100)
    temperature: float = Field(default=0.7, ge=0, le=2)
    maxTokens: int = Field(default=4096, ge=1, le=16384)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content cannot be empty")
        return value


class AITestPromptData(BaseModel):
    recordId: UUID
    promptId: UUID | None = None
    provider: str
    model: str
    renderedPrompt: str
    output: str
    latencyMs: int
    tokenUsage: TokenUsage
    createdAt: datetime


class AITestPromptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AITestPromptData


class AITestRecordListItem(BaseModel):
    id: UUID
    promptId: UUID | None = None
    provider: str
    model: str
    inputSummary: str
    outputSummary: str
    latencyMs: int
    createdAt: datetime


class AITestRecordListData(BaseModel):
    items: list[AITestRecordListItem]
    pagination: Pagination


class AITestRecordListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AITestRecordListData


class AITestRecordDetailData(BaseModel):
    id: UUID
    promptId: UUID | None = None
    provider: str
    model: str
    inputVariables: dict[str, str] | None = None
    renderedPrompt: str
    output: str
    latencyMs: int
    tokenUsage: TokenUsage
    createdAt: datetime


class AITestRecordDetailResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AITestRecordDetailData
