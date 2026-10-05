import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

S3_BUCKET = os.environ["S3_BUCKET"]

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="us-east-1",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    ),
)

app = FastAPI(title="Personal Cloud Storage", version="0.2.1")


class FileInfo(BaseModel):
    filename: str
    size: int
    uploaded_at: datetime


class ShareLink(BaseModel):
    filename: str
    url: str
    expires_in: int
    expires_at: datetime


def validate_key(filename: str) -> str:
    if filename in ("", ".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nama file tidak valid")
    return filename


def is_not_found(error: ClientError) -> bool:
    return error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound")


def object_exists(key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as error:
        if is_not_found(error):
            return False
        raise


def ensure_object_exists(key: str) -> None:
    if not object_exists(key):
        raise HTTPException(status_code=404, detail=f"File '{key}' tidak ditemukan")


def get_object_info(key: str) -> FileInfo:
    try:
        head = s3.head_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as error:
        if is_not_found(error):
            raise HTTPException(
                status_code=404,
                detail=f"File '{key}' tidak ditemukan",
            )
        raise
    return FileInfo(
        filename=key,
        size=head["ContentLength"],
        uploaded_at=head["LastModified"],
    )


def create_download_url(key: str, expires: int) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(key)}",
        },
        ExpiresIn=expires,
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile = File(...)):
    key = validate_key(Path(file.filename or "").name)

    if object_exists(key):
        raise HTTPException(status_code=409, detail=f"File '{key}' sudah ada")

    s3.upload_fileobj(
        file.file,
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": file.content_type or "application/octet-stream"},
    )
    return get_object_info(key)


@app.get("/files", response_model=list[FileInfo])
def list_files():
    files = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET):
        for obj in page.get("Contents", []):
            files.append(
                FileInfo(
                    filename=obj["Key"],
                    size=obj["Size"],
                    uploaded_at=obj["LastModified"],
                )
            )
    return files


@app.get("/files/{filename}/link", response_model=ShareLink)
def create_share_link(
    filename: str,
    expires: int = Query(default=3600, ge=60, le=604800),
):
    key = validate_key(filename)
    ensure_object_exists(key)
    return ShareLink(
        filename=key,
        url=create_download_url(key, expires),
        expires_in=expires,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires),
    )


@app.get("/files/{filename}")
def download_file(filename: str):
    key = validate_key(filename)
    ensure_object_exists(key)
    return RedirectResponse(
        create_download_url(key, expires=300),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@app.delete("/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(filename: str):
    key = validate_key(filename)
    ensure_object_exists(key)
    s3.delete_object(Bucket=S3_BUCKET, Key=key)
