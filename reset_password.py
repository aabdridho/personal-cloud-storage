import argparse
import getpass

from sqlalchemy import select

from database import SessionLocal
from models import User
from security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset password akun Personal Cloud Storage")
    parser.add_argument("username")
    args = parser.parse_args()

    password = getpass.getpass("Password baru: ")
    if len(password) < 8:
        raise SystemExit("Password minimal 8 karakter")
    if password != getpass.getpass("Ulangi password baru: "):
        raise SystemExit("Password tidak sama")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            raise SystemExit(f"Username '{args.username}' tidak ditemukan")

        user.password_hash = hash_password(password)
        db.commit()
        print(f"Password '{user.username}' diperbarui")


if __name__ == "__main__":
    main()
