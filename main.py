import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_admin, get_current_user
from config import S3_BUCKET
from database import get_db
from models import FileRecord, User
from security import DUMMY_HASH, create_access_token, hash_password, verify_password
from storage import create_download_url, s3

app = FastAPI(title="Personal Cloud Storage", version="0.4.0")


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
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return to_utc(value)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


def clean_filename(raw: str | None) -> str:
    name = Path(raw or "").name
    if name in ("", ".", "..") or len(name) > 255:
        raise HTTPException(status_code=400, detail="Nama file tidak valid")
    return name


def get_own_file_or_404(db: Session, file_id: int, user: User) -> FileRecord:
    record = db.scalar(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.owner_id == user.id,
        )
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"File dengan id {file_id} tidak ditemukan",
        )
    return record


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/auth/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == form.username))
    if user is None:
        verify_password(form.password, DUMMY_HASH)
        valid = False
    else:
        valid = verify_password(form.password, user.password_hash)

    if not valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


@app.get("/auth/me", response_model=UserInfo)
def read_me(user: User = Depends(get_current_user)):
    return user


@app.post("/users", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(status_code=409, detail=f"Username '{data.username}' sudah dipakai")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        is_admin=data.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = clean_filename(file.filename)

    duplicate = db.scalar(
        select(FileRecord).where(
            FileRecord.owner_id == user.id,
            FileRecord.filename == filename,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail=f"File '{filename}' sudah ada")

    object_key = uuid.uuid4().hex
    content_type = file.content_type or "application/octet-stream"

    s3.upload_fileobj(
        file.file,
        S3_BUCKET,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    head = s3.head_object(Bucket=S3_BUCKET, Key=object_key)

    record = FileRecord(
        owner_id=user.id,
        filename=filename,
        object_key=object_key,
        size=head["ContentLength"],
        content_type=content_type,
        etag=head["ETag"].strip('"'),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        s3.delete_object(Bucket=S3_BUCKET, Key=object_key)
        raise HTTPException(status_code=409, detail=f"File '{filename}' sudah ada")

    db.refresh(record)
    return record


@app.get("/files", response_model=list[FileInfo])
def list_files(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(FileRecord)
        .where(FileRecord.owner_id == user.id)
        .order_by(FileRecord.uploaded_at.desc())
    ).all()


@app.get("/files/{file_id}/link", response_model=ShareLink)
def create_share_link(
    file_id: int,
    expires: int = Query(default=3600, ge=60, le=604800),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_own_file_or_404(db, file_id, user)
    return ShareLink(
        id=record.id,
        filename=record.filename,
        url=create_download_url(record.object_key, record.filename, expires),
        expires_in=expires,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires),
    )


@app.get("/files/{file_id}")
def download_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_own_file_or_404(db, file_id, user)
    return RedirectResponse(
        create_download_url(record.object_key, record.filename, expires=300),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@app.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_own_file_or_404(db, file_id, user)
    object_key = record.object_key

    db.delete(record)
    db.commit()

    s3.delete_object(Bucket=S3_BUCKET, Key=object_key)
