from __future__ import annotations

from pathlib import Path


# Finish route renaming and lint cleanup after the primary integration patch.
path = Path("commercelens/api/domain.py")
text = path.read_text().replace("/v1/domain-monitors", "/v1/monitors")
path.write_text(text)

path = Path("commercelens/domain/repository.py")
text = path.read_text().replace("import json\n", "")
path.write_text(text)

# Existing persisted monitors are canonical when a new execution job binds to monitor_id.
old_create = '''        domain_repo = None\n        monitor = None\n        if job.account_id and job.project_id:\n            from commercelens.domain.repository import domain_repository_for_store\n            from commercelens.domain.service import bind_monitor_to_job, monitor_from_job_create\n\n            domain_repo = domain_repository_for_store(self)\n            monitor = monitor_from_job_create(request)\n            if monitor is not None:\n                monitor = domain_repo.save_monitor(monitor)\n                job.monitor_id = monitor.id\n        self.save_job(job)\n'''
new_create = '''        domain_repo = None\n        monitor = None\n        if job.account_id and job.project_id:\n            from commercelens.domain.repository import domain_repository_for_store\n            from commercelens.domain.service import bind_monitor_to_job, monitor_from_job_create\n\n            domain_repo = domain_repository_for_store(self)\n            if job.monitor_id:\n                monitor = domain_repo.get_monitor(\n                    job.monitor_id, account_id=job.account_id, project_id=job.project_id\n                )\n                if monitor is None:\n                    raise ValueError(f"Monitor not found: {job.monitor_id}")\n                job.name = monitor.name\n                job.config = monitor.config\n                job.schedule_kind = ScheduleKind(monitor.schedule_kind)\n                job.interval_minutes = monitor.interval_minutes\n                job.tags = list(monitor.tags)\n            else:\n                monitor = monitor_from_job_create(request)\n                if monitor is not None:\n                    monitor = domain_repo.save_monitor(monitor)\n                    job.monitor_id = monitor.id\n        self.save_job(job)\n'''
for filename in ("commercelens/jobs/store.py", "commercelens/jobs/postgres_store.py"):
    file = Path(filename)
    current = file.read_text()
    if new_create not in current:
        if old_create not in current:
            raise RuntimeError(f"Canonical monitor binding anchor not found in {filename}")
        file.write_text(current.replace(old_create, new_create, 1))

# Help mypy understand the tenant values narrowed by the preceding condition.
path = Path("commercelens/api/main.py")
text = path.read_text()
old = '''                account_id=context["account_id"],\n                project_id=context["project_id"],\n                extraction_id=record.id,\n'''
new = '''                account_id=str(context["account_id"]),\n                project_id=str(context["project_id"]),\n                extraction_id=record.id,\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Domain ingest tenant type-narrowing anchor not found")
path.write_text(text)

# Exercise the Postgres migration, job binding, and first-class observation storage in the existing CI job.
path = Path("tests/test_postgres_integration.py")
text = path.read_text()
import_anchor = "from commercelens.api.portal_auth import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME\n"
imports = (
    import_anchor
    + "from commercelens.domain.repository import domain_repository_for_store\n"
    + "from commercelens.domain.service import ingest_product_extraction\n"
)
if "from commercelens.domain.repository import domain_repository_for_store\n" not in text:
    if import_anchor not in text:
        raise RuntimeError("Postgres test import anchor not found")
    text = text.replace(import_anchor, imports, 1)
product_import_anchor = "from commercelens.jobs.postgres_store import PostgresJobStore\n"
product_imports = (
    product_import_anchor
    + "from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult\n"
)
if "from commercelens.schemas.product import Availability" not in text:
    text = text.replace(product_import_anchor, product_imports, 1)

job_anchor = '''        job = store.create_job(\n            MonitoringJobCreate(\n                name="Integration monitor",\n                config=config,\n                interval_minutes=5,\n                account_id=account.id,\n                project_id=project.id,\n            )\n        )\n        job.next_run_at = "2000-01-01T00:00:00+00:00"\n'''
job_new = '''        job = store.create_job(\n            MonitoringJobCreate(\n                name="Integration monitor",\n                config=config,\n                interval_minutes=5,\n                account_id=account.id,\n                project_id=project.id,\n            )\n        )\n        assert job.monitor_id is not None\n        domain_repo = domain_repository_for_store(store)\n        persisted_monitor = domain_repo.get_monitor(\n            job.monitor_id, account_id=account.id, project_id=project.id\n        )\n        assert persisted_monitor is not None\n        assert persisted_monitor.job_id == job.id\n        ingested = ingest_product_extraction(\n            domain_repo,\n            ProductExtractionResult(\n                url="https://example.com/product",\n                product=Product(\n                    name="Integration product",\n                    brand="Example",\n                    price=Price(amount=42.0, currency="USD"),\n                    availability=Availability.IN_STOCK,\n                    source_url="https://example.com/product",\n                    metadata={"gtin": "00012345678905"},\n                ),\n                confidence=0.99,\n            ),\n            account_id=account.id,\n            project_id=project.id,\n            monitor_id=job.monitor_id,\n            job_id=job.id,\n            captured_at="2026-08-26T12:00:00+00:00",\n            provenance={"fixture": "postgres"},\n        )\n        assert domain_repo.get_observation(\n            ingested.observation.id, account_id=account.id, project_id=project.id\n        ) is not None\n        assert domain_repo.get_observation(\n            ingested.observation.id, account_id="acct_other", project_id=project.id\n        ) is None\n        job.next_run_at = "2000-01-01T00:00:00+00:00"\n'''
if job_new not in text:
    if job_anchor not in text:
        raise RuntimeError("Postgres domain assertion anchor not found")
    text = text.replace(job_anchor, job_new, 1)
path.write_text(text)

print("Issue 19 follow-up integration patches applied")
