import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import S3_BUCKET
from database import Base, engine, get_db
from models import FileRecord
from storage import create_download_url, s3

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Personal Cloud Storage", version="0.3.0")


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
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class ShareLink(BaseModel):
    id: int
    filename: str
    url: str
    expires_in: int
    expires_at: datetime


def clean_filename(raw: str | None) -> str:
    name = Path(raw or "").name
    if name in ("", ".", "..") or len(name) > 255:
        raise HTTPException(status_code=400, detail="Nama file tidak valid")
    return name


def get_file_or_404(db: Session, file_id: int) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"File dengan id {file_id} tidak ditemukan",
        )
    return record


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = clean_filename(file.filename)

    if db.scalar(select(FileRecord).where(FileRecord.filename == filename)):
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
def list_files(db: Session = Depends(get_db)):
    return db.scalars(
        select(FileRecord).order_by(FileRecord.uploaded_at.desc())
    ).all()


@app.get("/files/{file_id}/link", response_model=ShareLink)
def create_share_link(
    file_id: int,
    expires: int = Query(default=3600, ge=60, le=604800),
    db: Session = Depends(get_db),
):
    record = get_file_or_404(db, file_id)
    return ShareLink(
        id=record.id,
        filename=record.filename,
        url=create_download_url(record.object_key, record.filename, expires),
        expires_in=expires,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires),
    )


@app.get("/files/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db)):
    record = get_file_or_404(db, file_id)
    return RedirectResponse(
        create_download_url(record.object_key, record.filename, expires=300),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@app.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, db: Session = Depends(get_db)):
    record = get_file_or_404(db, file_id)
    object_key = record.object_key

    db.delete(record)
    db.commit()

    s3.delete_object(Bucket=S3_BUCKET, Key=object_key)
