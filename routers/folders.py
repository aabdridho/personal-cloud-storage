from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import FileRecord, Folder, User
from permissions import get_own_folder
from schemas import FolderCreate, FolderInfo, FolderUpdate

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post("", response_model=FolderInfo, status_code=status.HTTP_201_CREATED)
def create_folder(
    data: FolderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    folder = Folder(owner_id=user.id, name=data.name, is_shared=data.is_shared)
    db.add(folder)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Folder '{data.name}' sudah ada")
    db.refresh(folder)
    return folder


@router.get("", response_model=list[FolderInfo])
def list_folders(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Folder)
        .where(or_(Folder.owner_id == user.id, Folder.is_shared.is_(True)))
        .order_by(Folder.is_shared.desc(), Folder.name)
    ).all()


@router.patch("/{folder_id}", response_model=FolderInfo)
def update_folder(
    folder_id: int,
    data: FolderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    folder = get_own_folder(db, folder_id, user)

    if data.is_shared is False and folder.is_shared:
        others = db.scalar(
            select(func.count(FileRecord.id)).where(
                FileRecord.folder_id == folder.id,
                FileRecord.owner_id != user.id,
            )
        )
        if others:
            raise HTTPException(
                status_code=409,
                detail=f"Folder masih berisi {others} file milik anggota lain",
            )

    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(folder, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Folder '{data.name}' sudah ada")

    db.refresh(folder)
    return folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    folder = get_own_folder(db, folder_id, user)

    count = db.scalar(select(func.count(FileRecord.id)).where(FileRecord.folder_id == folder.id))
    if count:
        raise HTTPException(status_code=409, detail=f"Folder masih berisi {count} file")

    db.delete(folder)
    db.commit()
