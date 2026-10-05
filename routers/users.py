from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_admin
from database import get_db
from models import User
from schemas import UserCreate, UserInfo, UserUpdate
from security import hash_password

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("", response_model=list[UserInfo])
def list_users(db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.post("", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(status_code=409, detail=f"Username '{data.username}' sudah dipakai")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        is_admin=data.is_admin,
    )
    if data.quota_bytes is not None:
        user.quota_bytes = data.quota_bytes

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserInfo)
def update_user(
    user_id: int,
    data: UserUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User dengan id {user_id} tidak ditemukan")

    if user.id == admin.id and data.is_active is False:
        raise HTTPException(status_code=400, detail="Admin tidak bisa menonaktifkan akunnya sendiri")

    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user
