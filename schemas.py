from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_PATTERN = r"^[^/\\]+$"


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    folder_id: int | None
    filename: str
    size: int
    content_type: str
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return to_utc(value)


class FileUpdate(BaseModel):
    filename: str | None = Field(default=None, min_length=1, max_length=255, pattern=NAME_PATTERN)
    folder_id: int | None = None


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    is_shared: bool = False


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=NAME_PATTERN)
    is_shared: bool | None = None


class FolderInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    is_shared: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return to_utc(value)


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
