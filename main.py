import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Personal Cloud Storage", version="0.1.0")


class FileInfo(BaseModel):
    filename: str
    size: int
    uploaded_at: datetime


def to_file_info(path: Path) -> FileInfo:
    stat = path.stat()
    return FileInfo(
        filename=path.name,
        size=stat.st_size,
        uploaded_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    )


def get_file_path(filename: str) -> Path:
    path = (STORAGE_DIR / filename).resolve()
    if path.parent != STORAGE_DIR:
        raise HTTPException(status_code=400, detail="Nama file tidak valid")
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"File '{filename}' tidak ditemukan",
        )
    return path


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile = File(...)):
    safe_name = Path(file.filename or "").name
    if safe_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Nama file tidak valid")

    destination = STORAGE_DIR / safe_name
    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail=f"File '{safe_name}' sudah ada",
        )

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return to_file_info(destination)


@app.get("/files", response_model=list[FileInfo])
def list_files():
    return [
        to_file_info(path)
        for path in sorted(STORAGE_DIR.iterdir())
        if path.is_file()
    ]


@app.get("/files/{filename}")
def download_file(filename: str):
    path = get_file_path(filename)
    return FileResponse(path, filename=path.name)


@app.delete("/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(filename: str):
    path = get_file_path(filename)
    path.unlink()
