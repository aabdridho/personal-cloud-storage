from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size: int
    content_type: str
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return to_utc(value)


class FileRename(BaseModel):
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+$")


class ShareLink(BaseModel):
    id: int
    filename: str
    url: str
    expires_in: int
    expires_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool
    is_active: bool
    quota_bytes: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return to_utc(value)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False
    quota_bytes: int | None = Field(default=None, ge=0)


class UserUpdate(BaseModel):
    is_active: bool | None = None
    quota_bytes: int | None = Field(default=None, ge=0)


class StorageUsage(BaseModel):
    used_bytes: int
    quota_bytes: int
    file_count: int
    used_percent: float
