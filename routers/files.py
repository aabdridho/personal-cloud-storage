import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user
from config import MAX_UPLOAD_MB, S3_BUCKET
from database import get_db
from models import FileRecord, User
from schemas import FileInfo, FileRename, ShareLink
from services import get_storage_usage
from storage import create_download_url, s3

router = APIRouter(prefix="/files", tags=["files"])

MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def clean_filename(raw: str | None) -> str:
    name = Path(raw or "").name
    if name in ("", ".", "..") or len(name) > 255:
        raise HTTPException(status_code=400, detail="Nama file tidak valid")
    return name


def get_upload_size(file: UploadFile) -> int:
    if file.size is not None:
        return file.size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    return size


def get_own_file_or_404(db: Session, file_id: int, user: User) -> FileRecord:
    record = db.scalar(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.owner_id == user.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"File dengan id {file_id} tidak ditemukan")
    return record


@router.post("", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = clean_filename(file.filename)

    size = get_upload_size(file)
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Ukuran file melebihi batas {MAX_UPLOAD_MB} MB",
        )

    used, _ = get_storage_usage(db, user.id)
    if used + size > user.quota_bytes:
        raise HTTPException(
            status_code=507,
            detail=f"Kuota tidak cukup: terpakai {used} dari {user.quota_bytes} byte, file ini {size} byte",
        )

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


@router.get("", response_model=list[FileInfo])
def list_files(
    q: str | None = Query(default=None, max_length=100),
    content_type: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(FileRecord).where(FileRecord.owner_id == user.id)
    if q:
        query = query.where(FileRecord.filename.icontains(q, autoescape=True))
    if content_type:
        query = query.where(FileRecord.content_type.startswith(content_type, autoescape=True))

    query = (
        query.order_by(FileRecord.uploaded_at.desc(), FileRecord.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return db.scalars(query).all()


@router.patch("/{file_id}", response_model=FileInfo)
def rename_file(
    file_id: int,
    data: FileRename,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_own_file_or_404(db, file_id, user)
    new_name = clean_filename(data.filename)
    if new_name == record.filename:
        return record

    record.filename = new_name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"File '{new_name}' sudah ada")

    db.refresh(record)
    return record


@router.get("/{file_id}/link", response_model=ShareLink)
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


@router.get("/{file_id}")
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


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
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
