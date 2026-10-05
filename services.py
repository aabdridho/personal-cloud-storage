from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import FileRecord


def get_storage_usage(db: Session, user_id: int) -> tuple[int, int]:
    used, count = db.execute(
        select(
            func.coalesce(func.sum(FileRecord.size), 0),
            func.count(FileRecord.id),
        ).where(FileRecord.owner_id == user_id)
    ).one()
    return int(used), int(count)
