from pathlib import Path

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.jobs.models import AccountCreate, MemberCreate, MemberRole, ProjectCreate
from commercelens.jobs.store import JobStore


def test_account_project_member_roundtrip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")

    account = store.create_account(AccountCreate(name="Acme Retail", owner="ops@acme.test"))
    project = store.create_project(account.id, ProjectCreate(name="Competitors", slug="competitors"))
    member = store.create_member(
        account.id,
        MemberCreate(email="analyst@acme.test", name="Analyst", role=MemberRole.admin),
    )

    assert store.get_account(account.id) == account
    assert store.get_project(project.id, account_id=account.id) == project
    assert store.list_accounts()[0].name == "Acme Retail"
    assert store.list_projects(account_id=account.id)[0].slug == "competitors"
    assert store.list_members(account.id)[0].email == member.email


def test_account_api_requires_admin_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    client = TestClient(app)

    denied = client.get("/v1/accounts")
    allowed = client.get("/v1/accounts", headers={"X-Admin-Token": "secret"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_account_api_and_dashboard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    client = TestClient(app)

    account_response = client.post(
        "/v1/accounts",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Acme Retail", "owner": "ops@acme.test"},
    )
    assert account_response.status_code == 200
    account = account_response.json()

    project_response = client.post(
        f"/v1/accounts/{account['id']}/projects",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Competitors", "slug": "competitors"},
    )
    assert project_response.status_code == 200

    member_response = client.post(
        f"/v1/accounts/{account['id']}/members",
        headers={"X-Admin-Token": "secret"},
        json={"email": "analyst@acme.test", "role": "admin"},
    )
    assert member_response.status_code == 200

    dashboard_response = client.get("/dashboard?admin_token=secret")
    detail_response = client.get(f"/dashboard/accounts/{account['id']}?admin_token=secret")

    assert dashboard_response.status_code == 200
    assert "Acme Retail" in dashboard_response.text
    assert detail_response.status_code == 200
    assert "Competitors" in detail_response.text
    assert "analyst@acme.test" in detail_response.text
