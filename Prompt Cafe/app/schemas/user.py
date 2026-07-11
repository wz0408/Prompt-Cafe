import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="username", examples=["admin"])
    email: str = Field(..., description="valid email address", examples=["zhangsan@example.com"])
    password: str = Field(..., min_length=6, max_length=64, description="password", examples=["12345678"])

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, value):
            raise ValueError("Invalid email format")
        return value


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    username: str
    email: str
    role: str
    status: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, alias="avatarUrl")
    bio: Optional[str] = None
    last_login_at: Optional[datetime] = Field(default=None, alias="lastLoginAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UserResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: UserProfile


class UpdateMyProfileRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=50)
    avatar_url: Optional[str] = Field(default=None, alias="avatarUrl")
    bio: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(populate_by_name=True)
