from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import User
from schemas import StorageUsage, Token, UserInfo
from security import DUMMY_HASH, create_access_token, verify_password
from services import get_storage_usage

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
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


@router.get("/me", response_model=UserInfo)
def read_me(user: User = Depends(get_current_user)):
    return user


@router.get("/me/storage", response_model=StorageUsage)
def read_my_storage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    used, count = get_storage_usage(db, user.id)
    percent = round(used / user.quota_bytes * 100, 2) if user.quota_bytes else 100.0
    return StorageUsage(
        used_bytes=used,
        quota_bytes=user.quota_bytes,
        file_count=count,
        used_percent=percent,
    )
