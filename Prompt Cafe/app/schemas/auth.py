from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserProfile


class AuthTokenData(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    access_token_expires_in: int = Field(alias="accessTokenExpiresIn")
    refresh_token_expires_in: int = Field(alias="refreshTokenExpiresIn")
    user: UserProfile


class AuthResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AuthTokenData


class LoginRequest(BaseModel):
    account: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")


class RefreshTokenData(BaseModel):
    access_token: str = Field(alias="accessToken")
    access_token_expires_in: int = Field(alias="accessTokenExpiresIn")


class RefreshTokenResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: RefreshTokenData


class SuccessResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None
