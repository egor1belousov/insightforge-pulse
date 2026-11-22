import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LLM_ENABLED"] = "false"
os.environ["APP_ENV"] = "dev"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import CSRF_COOKIE, login_limiter  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db.session import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter.reset()
    yield


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get(CSRF_COOKIE) or ""}


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
