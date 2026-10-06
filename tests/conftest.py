import os
import tempfile
from pathlib import Path

_tmp_dir = Path(tempfile.mkdtemp())

os.environ.update(
    {
        "S3_ENDPOINT": "http://s3.test",
        "S3_PUBLIC_ENDPOINT": "http://s3.test",
        "S3_ACCESS_KEY": "test",
        "S3_SECRET_KEY": "test",
        "S3_BUCKET": "test-bucket",
        # Default SQLite sementara; set TEST_DATABASE_URL untuk menguji di PostgreSQL.
        "DATABASE_URL": os.getenv(
            "TEST_DATABASE_URL", f"sqlite:///{(_tmp_dir / 'test.db').as_posix()}"
        ),
        "JWT_SECRET": "secret-khusus-pytest-yang-cukup-panjang",
        "MOTO_S3_CUSTOM_ENDPOINTS": "http://s3.test",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from moto import mock_aws  # noqa: E402

_aws_mock = mock_aws()
_aws_mock.start()

from database import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402
from models import User  # noqa: E402
from security import hash_password  # noqa: E402
from storage import s3  # noqa: E402

s3.create_bucket(Bucket=os.environ["S3_BUCKET"])

PASSWORD = "password-untuk-test"


def create_user(username: str, is_admin: bool = False) -> None:
    with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password(PASSWORD), is_admin=is_admin))
        db.commit()


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    def _login(username: str, password: str = PASSWORD) -> dict:
        response = client.post("/auth/login", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


@pytest.fixture
def admin(login):
    create_user("admin", is_admin=True)
    return login("admin")


@pytest.fixture
def member(login):
    create_user("member")
    return login("member")
