import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
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

app = FastAPI(title="Personal Cloud Storage", version="0.2.0")


class FileInfo(BaseModel):
    filename: str
    size: int
    uploaded_at: datetime


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


@app.get("/files/{filename}")
def download_file(filename: str):
    key = validate_key(filename)
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as error:
        if is_not_found(error):
            raise HTTPException(
                status_code=404,
                detail=f"File '{key}' tidak ditemukan",
            )
        raise

    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=1024 * 1024),
        media_type=obj.get("ContentType", "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(key)}",
            "Content-Length": str(obj["ContentLength"]),
        },
    )


@app.delete("/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(filename: str):
    key = validate_key(filename)
    if not object_exists(key):
        raise HTTPException(status_code=404, detail=f"File '{key}' tidak ditemukan")
    s3.delete_object(Bucket=S3_BUCKET, Key=key)
