from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import FileRecord, Folder, User


def not_found(kind: str, item_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} dengan id {item_id} tidak ditemukan")


def forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def get_accessible_folder_or_404(db: Session, folder_id: int, user: User) -> Folder:
    folder = db.get(Folder, folder_id)
    if folder is None or (folder.owner_id != user.id and not folder.is_shared):
        raise not_found("Folder", folder_id)
    return folder


def get_own_folder(db: Session, folder_id: int, user: User) -> Folder:
    folder = get_accessible_folder_or_404(db, folder_id, user)
    if folder.owner_id != user.id:
        raise forbidden("Hanya pembuat folder yang boleh mengubah atau menghapusnya")
    return folder


def get_readable_file_or_404(db: Session, file_id: int, user: User) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if record is None:
        raise not_found("File", file_id)
    if record.owner_id == user.id:
        return record
    if record.folder_id is not None:
        folder = db.get(Folder, record.folder_id)
        if folder is not None and folder.is_shared:
            return record
    raise not_found("File", file_id)


def get_own_file(db: Session, file_id: int, user: User) -> FileRecord:
    record = get_readable_file_or_404(db, file_id, user)
    if record.owner_id != user.id:
        raise forbidden("Hanya pengunggah file yang boleh mengubah atau menghapusnya")
    return record
