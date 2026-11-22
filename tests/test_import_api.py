from pathlib import Path

from fastapi.testclient import TestClient

from app.db.models import Pair, Participant, Response
from app.db.session import SessionLocal
from tests.conftest import csrf_headers
from tests.test_auth import make_all_roles

ROOT = Path(__file__).parent / "fixtures" / "ingest"


def upload(c: TestClient, variant: str):
    files = [
        ("files", (p.name, p.read_bytes()))
        for p in sorted((ROOT / variant).iterdir())
        if p.name != "expected.json"
    ]
    return c.post("/api/import/upload", files=files, headers=csrf_headers(c))


def test_upload_edit_confirm_and_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.core.settings import get_settings

    get_settings.cache_clear()
    clients = make_all_roles()
    hr = clients["hr"]
    assert upload(clients["intern"], "v1").status_code == 403

    r = upload(hr, "v6")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["schema"]["asks"] == []
    schema = job["schema"]
    schema["issues"] = [dict(i, apply=(i["type"] != "duplicate")) for i in schema["issues"]]
    r = hr.put(f"/api/import/{job['id']}/schema", json=schema, headers=csrf_headers(hr))
    assert r.status_code == 200, r.text
    assert any(i["type"] == "duplicate" and not i["apply"] for i in r.json()["schema"]["issues"])

    r = hr.post(f"/api/import/{job['id']}/confirm", headers=csrf_headers(hr))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Pair).count() == 5
        assert db.query(Response).count() == 60
        assert db.query(Participant).filter(Participant.external_id == "С-104").one().user_id is not None

    again = upload(hr, "v6").json()
    assert again["schema"]["profile_applied"]
    get_settings.cache_clear()


def test_bad_file_rejected() -> None:
    hr = make_all_roles()["hr"]
    r = hr.post("/api/import/upload", files=[("files", ("x.pdf", b"%PDF"))], headers=csrf_headers(hr))
    assert r.status_code == 400
    assert "не поддерживается" in r.json()["detail"]
