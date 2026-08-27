from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.api.portal_auth import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME
from commercelens.domain.insights import build_product_comparison
from commercelens.domain.models import (
    ProductMatchRecord,
    ProductMatchStatus,
    ProductRecord,
)
from commercelens.domain.repository import domain_repository_for_store
from commercelens.jobs.models import AccountCreate, AccountStatus, ApiKeyCreate, ProjectCreate
from commercelens.jobs.store import JobStore
from commercelens.matching.corrections import correct_product_match, replace_product_match


def _workspace(store: JobStore):
    account = store.create_account(
        AccountCreate(name="Acme", owner="owner@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name="Retail"))
    return account, project


def _portal_key(store: JobStore, account_id: str, project_id: str):
    return store.create_api_key(
        ApiKeyCreate(
            name="portal",
            owner="owner@example.com",
            account_id=account_id,
            project_id=project_id,
            scopes=["*"],
        )
    )


def _login(client: TestClient, token: str) -> str:
    login_page = client.get("/portal/login")
    login_csrf = login_page.cookies[LOGIN_CSRF_COOKIE_NAME]
    response = client.post(
        "/portal/login",
        data={"api_key": token, "csrf_token": login_csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client.cookies[CSRF_COOKIE_NAME]


def _products(repo, account_id: str, project_id: str):
    rows = [
        ProductRecord(
            id="prod_anchor",
            account_id=account_id,
            project_id=project_id,
            name="Anchor Product",
            brand="Acme",
        ),
        ProductRecord(
            id="prod_old",
            account_id=account_id,
            project_id=project_id,
            name="Old Equivalent",
            brand="Acme",
        ),
        ProductRecord(
            id="prod_new",
            account_id=account_id,
            project_id=project_id,
            name="New Equivalent",
            brand="Acme",
        ),
    ]
    for product in rows:
        repo.save_product(product)
    return rows


def _match(repo, account_id: str, project_id: str) -> ProductMatchRecord:
    return repo.save_product_match(
        ProductMatchRecord(
            id="match_anchor_old",
            account_id=account_id,
            project_id=project_id,
            left_product_id="prod_anchor",
            right_product_id="prod_old",
            confidence=0.82,
            status=ProductMatchStatus.proposed,
            method="similarity",
        )
    )


def test_match_correction_persists_provenance_and_changes_comparison(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account, project = _workspace(store)
    repo = domain_repository_for_store(store)
    _products(repo, account.id, project.id)
    match = _match(repo, account.id, project.id)

    before = build_product_comparison(
        repo,
        account_id=account.id,
        project_id=project.id,
        product_id="prod_anchor",
    )
    assert before is not None
    assert [item.product.id for item in before.equivalent_products] == ["prod_old"]

    confirmed = correct_product_match(
        repo,
        account_id=account.id,
        project_id=project.id,
        match_id=match.id,
        action="confirm",
        actor="owner@example.com",
        note="Verified against retailer page",
    )
    assert confirmed.status == ProductMatchStatus.confirmed
    assert confirmed.method == "customer_correction"
    assert confirmed.metadata["last_correction"]["action"] == "confirm"
    assert confirmed.metadata["last_correction"]["previous_status"] == "proposed"

    rejected = correct_product_match(
        repo,
        account_id=account.id,
        project_id=project.id,
        match_id=match.id,
        action="reject",
        actor="owner@example.com",
    )
    assert rejected.status == ProductMatchStatus.rejected
    after = build_product_comparison(
        repo,
        account_id=account.id,
        project_id=project.id,
        product_id="prod_anchor",
    )
    assert after is not None
    assert after.equivalent_products == []


def test_replace_match_rejects_old_and_confirms_new(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account, project = _workspace(store)
    repo = domain_repository_for_store(store)
    _products(repo, account.id, project.id)
    match = _match(repo, account.id, project.id)

    result = replace_product_match(
        repo,
        account_id=account.id,
        project_id=project.id,
        match_id=match.id,
        replacement_product_id="prod_new",
        actor="owner@example.com",
        note="Old match was a different bundle",
    )

    assert result.updated.status == ProductMatchStatus.rejected
    assert result.replacement is not None
    assert result.replacement.status == ProductMatchStatus.confirmed
    assert result.replacement.confidence == 1.0
    assert result.replacement.metadata["last_correction"]["replacement_for"] == match.id
    comparison = build_product_comparison(
        repo,
        account_id=account.id,
        project_id=project.id,
        product_id="prod_anchor",
    )
    assert comparison is not None
    assert [item.product.id for item in comparison.equivalent_products] == ["prod_new"]


def test_portal_can_confirm_reject_and_replace_match(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    account, project = _workspace(store)
    repo = domain_repository_for_store(store)
    _products(repo, account.id, project.id)
    match = _match(repo, account.id, project.id)
    key = _portal_key(store, account.id, project.id)
    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, key.token)

    page = client.get(f"/portal/matches?project_id={project.id}")
    assert page.status_code == 200
    assert "Anchor Product" in page.text
    assert "Old Equivalent" in page.text

    confirmed = client.post(
        f"/portal/matches/{match.id}/confirm",
        data={"csrf_token": csrf, "project_id": project.id},
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    saved = domain_repository_for_store(JobStore(db_path)).get_product_match(
        match.id, account_id=account.id, project_id=project.id
    )
    assert saved is not None
    assert saved.status == ProductMatchStatus.confirmed

    replaced = client.post(
        f"/portal/matches/{match.id}/replace",
        data={
            "csrf_token": csrf,
            "project_id": project.id,
            "replacement_product_id": "prod_new",
            "note": "Correct competitor equivalent",
        },
        follow_redirects=False,
    )
    assert replaced.status_code == 303
    repo_after = domain_repository_for_store(JobStore(db_path))
    old = repo_after.get_product_match(match.id, account_id=account.id, project_id=project.id)
    assert old is not None
    assert old.status == ProductMatchStatus.rejected
    replacements = [
        row
        for row in repo_after.list_product_matches(
            account_id=account.id, project_id=project.id, limit=100
        )
        if {row.left_product_id, row.right_product_id} == {"prod_anchor", "prod_new"}
    ]
    assert len(replacements) == 1
    assert replacements[0].status == ProductMatchStatus.confirmed


def test_portal_match_correction_is_tenant_scoped(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    first_account, first_project = _workspace(store)
    first_repo = domain_repository_for_store(store)
    _products(first_repo, first_account.id, first_project.id)
    match = _match(first_repo, first_account.id, first_project.id)

    second_account = store.create_account(
        AccountCreate(name="Other", owner="other@example.com", status=AccountStatus.active)
    )
    second_project = store.create_project(second_account.id, ProjectCreate(name="Other"))
    second_key = _portal_key(store, second_account.id, second_project.id)
    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, second_key.token)

    response = client.post(
        f"/portal/matches/{match.id}/reject",
        data={"csrf_token": csrf, "project_id": first_project.id},
        follow_redirects=False,
    )

    assert response.status_code == 404
    unchanged = domain_repository_for_store(JobStore(db_path)).get_product_match(
        match.id, account_id=first_account.id, project_id=first_project.id
    )
    assert unchanged is not None
    assert unchanged.status == ProductMatchStatus.proposed
