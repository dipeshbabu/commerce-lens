from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.api import portal_management_actions, portal_management_core
from commercelens.api.portal_auth import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME
from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.jobs.models import (
    AccountCreate,
    AccountStatus,
    ApiKeyCreate,
    JobStatus,
    MonitoringJobCreate,
    ProjectCreate,
)
from commercelens.jobs.store import JobStore
from commercelens.schemas.listing import ListingExtractionResult, ListingProduct
from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult


def _workspace(
    store: JobStore,
    *,
    account_name: str = "Acme",
    project_name: str = "Competitive",
):
    account = store.create_account(
        AccountCreate(name=account_name, owner="owner@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name=project_name))
    return account, project


def _portal_key(store: JobStore, account_id: str, project_id: str | None):
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


def test_portal_customer_can_create_project_with_account_level_key(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    account = store.create_account(
        AccountCreate(name="Acme", owner="owner@example.com", status=AccountStatus.active)
    )
    key = _portal_key(store, account.id, None)
    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, key.token)

    manage = client.get("/portal/manage")
    assert manage.status_code == 200
    assert "No project is available" in manage.text
    assert "Create a project" in manage.text

    created = client.post(
        "/portal/manage/projects",
        data={"csrf_token": csrf, "name": "Retail", "slug": "retail"},
        follow_redirects=False,
    )

    assert created.status_code == 303
    projects = JobStore(db_path).list_projects(account_id=account.id)
    assert len(projects) == 1
    assert projects[0].name == "Retail"
    assert f"project_id={projects[0].id}" in created.headers["location"]


def test_portal_onboarding_preview_activate_and_manage_monitor(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    account, project = _workspace(store)
    key = _portal_key(store, account.id, project.id)

    category_url = "https://shop.example/category/shoes"
    csv_product_url = "https://shop.example/products/csv-item"
    category_product_url = "https://shop.example/products/category-item"

    def listing_preview(url: str, render: bool):
        assert url == category_url
        assert render is False
        return ListingExtractionResult(
            url=url,
            products=[
                ListingProduct(
                    name="Category item",
                    url=category_product_url,
                    price=Price(amount=79.0, currency="USD"),
                    confidence=0.95,
                )
            ],
            product_count=1,
            confidence=0.95,
        )

    def product_preview(url: str, render: bool):
        assert url in {csv_product_url, category_product_url}
        assert render is False
        return ProductExtractionResult(
            url=url,
            product=Product(
                name="Preview shoe",
                brand="Example",
                price=Price(amount=99.0, currency="USD"),
                availability=Availability.IN_STOCK,
                source_url=url,
            ),
            confidence=0.97,
        )

    monkeypatch.setattr(portal_management_core, "_extract_listing_preview", listing_preview)
    monkeypatch.setattr(portal_management_core, "_extract_product_preview", product_preview)

    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, key.token)

    preview = client.post(
        "/portal/manage/preview",
        data={
            "csrf_token": csrf,
            "project_id": project.id,
            "name": "Footwear competitors",
            "category_urls": category_url,
            "schedule_kind": "interval",
            "interval_minutes": "60",
            "render": "false",
            "alert_name": "Large drop",
            "alert_condition": "percent_drop_at_least",
            "alert_threshold": "10",
            "destination_type": "webhook",
            "destination_value": "https://alerts.example/hooks/commerce",
        },
        files={"csv_file": ("targets.csv", f"url\n{csv_product_url}\n", "text/csv")},
    )

    assert preview.status_code == 200
    assert "Validation passed" in preview.text
    assert "First extraction preview" in preview.text
    assert "Preview shoe" in preview.text
    assert csv_product_url in preview.text
    assert category_product_url in preview.text
    assert "Activate monitor" in preview.text

    activated = client.post(
        "/portal/manage/monitors",
        data={
            "csrf_token": csrf,
            "project_id": project.id,
            "name": "Footwear competitors",
            "schedule_kind": "interval",
            "interval_minutes": "60",
            "render": "false",
            "resolved_urls": f"{csv_product_url}\n{category_product_url}",
            "alert_name": "Large drop",
            "alert_condition": "percent_drop_at_least",
            "alert_threshold": "10",
            "destination_type": "webhook",
            "destination_value": "https://alerts.example/hooks/commerce",
        },
        follow_redirects=False,
    )

    assert activated.status_code == 303
    jobs = JobStore(db_path).list_jobs(account_id=account.id, project_id=project.id)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.name == "Footwear competitors"
    assert job.interval_minutes == 60
    assert {str(target.url) for target in job.config.targets} == {
        csv_product_url,
        category_product_url,
    }
    assert job.config.rules[0].condition.value == "percent_drop_at_least"
    assert str(job.config.rules[0].destinations[0].url) == "https://alerts.example/hooks/commerce"

    paused = client.post(
        f"/portal/manage/jobs/{job.id}/pause",
        data={"csrf_token": csrf, "project_id": project.id},
        follow_redirects=False,
    )
    assert paused.status_code == 303
    assert JobStore(db_path).get_job(job.id).status == JobStatus.paused

    resumed = client.post(
        f"/portal/manage/jobs/{job.id}/resume",
        data={"csrf_token": csrf, "project_id": project.id},
        follow_redirects=False,
    )
    assert resumed.status_code == 303
    assert JobStore(db_path).get_job(job.id).status == JobStatus.active

    edited = client.post(
        f"/portal/manage/jobs/{job.id}/edit",
        data={
            "csrf_token": csrf,
            "project_id": project.id,
            "name": "Footwear daily",
            "schedule_kind": "manual",
            "interval_minutes": "1440",
            "render": "true",
            "urls": f"{csv_product_url}\n{category_product_url}",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    updated = JobStore(db_path).get_job(job.id)
    assert updated.name == "Footwear daily"
    assert updated.schedule_kind.value == "manual"
    assert updated.config.render is True

    run_calls: list[str] = []
    monkeypatch.setattr(
        portal_management_actions,
        "run_job_now",
        lambda store, job_id, dry_run=False, deliver=True: run_calls.append(job_id),
    )
    run = client.post(
        f"/portal/manage/jobs/{job.id}/run",
        data={"csrf_token": csrf, "project_id": project.id},
        follow_redirects=False,
    )
    assert run.status_code == 303
    assert run_calls == [job.id]

    deleted = client.post(
        f"/portal/manage/jobs/{job.id}/delete",
        data={"csrf_token": csrf, "project_id": project.id},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert JobStore(db_path).get_job(job.id) is None

    audited_project = JobStore(db_path).get_project(project.id, account_id=account.id)
    assert audited_project is not None
    audit_operations = {
        event.get("operation")
        for event in audited_project.metadata.get("portal_audit_events", [])
    }
    assert {
        "portal_monitor_activated",
        "portal_monitor_pause",
        "portal_monitor_resume",
        "portal_monitor_edited",
        "portal_monitor_run",
        "portal_monitor_delete",
    }.issubset(audit_operations)


def test_portal_preview_explains_invalid_and_duplicate_urls_before_save(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    account, project = _workspace(store)
    existing_url = "https://shop.example/products/already"
    store.create_job(
        MonitoringJobCreate(
            name="Existing",
            config=MonitorConfig(targets=[MonitorTarget(url=existing_url)]),
            account_id=account.id,
            project_id=project.id,
        )
    )
    key = _portal_key(store, account.id, project.id)
    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, key.token)

    preview = client.post(
        "/portal/manage/preview",
        data={
            "csrf_token": csrf,
            "project_id": project.id,
            "name": "Bad import",
            "schedule_kind": "interval",
            "interval_minutes": "60",
            "render": "false",
            "alert_condition": "",
        },
        files={
            "csv_file": (
                "targets.csv",
                f"url\n{existing_url}\nnot-a-url\n{existing_url}\n",
                "text/csv",
            )
        },
    )

    assert preview.status_code == 422
    assert "Fix these items before activation" in preview.text
    assert "already monitored in this project" in preview.text
    assert "Use a complete http:// or https:// URL" in preview.text
    assert "Activate monitor" not in preview.text


def test_portal_monitor_actions_are_tenant_scoped(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    first_account, first_project = _workspace(store, account_name="First", project_name="One")
    second_account, second_project = _workspace(store, account_name="Second", project_name="Two")
    job = store.create_job(
        MonitoringJobCreate(
            name="Private monitor",
            config=MonitorConfig(targets=[MonitorTarget(url="https://first.example/product")]),
            account_id=first_account.id,
            project_id=first_project.id,
        )
    )
    second_key = _portal_key(store, second_account.id, second_project.id)
    client = TestClient(app, base_url="https://testserver")
    csrf = _login(client, second_key.token)

    response = client.post(
        f"/portal/manage/jobs/{job.id}/pause",
        data={"csrf_token": csrf, "project_id": first_project.id},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert JobStore(db_path).get_job(job.id).status == JobStatus.active
