import argparse
import getpass

from sqlalchemy import select

from database import SessionLocal
from models import User
from security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Buat akun Personal Cloud Storage")
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true", help="Jadikan akun admin")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        raise SystemExit("Password minimal 8 karakter")
    if password != getpass.getpass("Ulangi password: "):
        raise SystemExit("Password tidak sama")

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == args.username)):
            raise SystemExit(f"Username '{args.username}' sudah dipakai")

        user = User(
            username=args.username,
            password_hash=hash_password(password),
            is_admin=args.admin,
        )
        db.add(user)
        db.commit()
        print(f"Akun '{user.username}' dibuat (id={user.id}, admin={user.is_admin})")


if __name__ == "__main__":
    main()
