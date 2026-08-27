from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Patch anchor not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, count: int) -> None:
    file = Path(path)
    text = file.read_text()
    if text.count(new) >= count:
        return
    if text.count(old) < count:
        raise RuntimeError(f"Expected {count} anchors in {path}, found {text.count(old)}")
    file.write_text(text.replace(old, new, count))


# Monitoring jobs reference the canonical persisted monitor while retaining config as a compatibility shadow.
replace_count(
    "commercelens/jobs/models.py",
    "    config: MonitorConfig\n    schedule_kind: ScheduleKind = ScheduleKind.interval\n",
    "    config: MonitorConfig\n    monitor_id: str | None = None\n    schedule_kind: ScheduleKind = ScheduleKind.interval\n",
    2,
)
replace_once(
    "commercelens/jobs/models.py",
    "    config: MonitorConfig | None = None\n    schedule_kind: ScheduleKind | None = None\n",
    "    config: MonitorConfig | None = None\n    monitor_id: str | None = None\n    schedule_kind: ScheduleKind | None = None\n",
)

# A caller that explicitly supplies a monitor_id already owns the monitor binding.
replace_once(
    "commercelens/domain/service.py",
    "    if not request.account_id or not request.project_id:\n        return None\n",
    "    if request.monitor_id or not request.account_id or not request.project_id:\n        return None\n",
)
replace_once(
    "commercelens/domain/service.py",
    "        monitor = MonitorRecord(\n            account_id=job.account_id,\n",
    "        monitor = MonitorRecord(\n            id=job.monitor_id or _stable_id(\"mon\", job.account_id, job.project_id, job.id),\n            account_id=job.account_id,\n",
)
replace_once(
    "commercelens/domain/service.py",
    "from commercelens.schemas.product import Price, Product, ProductExtractionResult\n",
    "from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult\n",
)
replace_once(
    "commercelens/domain/service.py",
    "                availability=snapshot.availability or \"unknown\",\n",
    "                availability=(\n                    Availability(snapshot.availability)\n                    if snapshot.availability\n                    else Availability.UNKNOWN\n                ),\n",
)

# Keep the repository module lint-clean.
replace_once("commercelens/domain/repository.py", "import json\n", "")
replace_once(
    "commercelens/domain/repository.py",
    "from typing import Any, Protocol, TypeVar, cast\n",
    "from typing import Any, Protocol, TypeVar\n",
)

# Use the public monitor resource name and complete product-match CRUD.
replace_once(
    "commercelens/api/domain.py",
    '"/v1/domain-monitors"',
    '"/v1/monitors"',
)
replace_once(
    "commercelens/api/domain.py",
    '"/v1/domain-monitors/{monitor_id}"',
    '"/v1/monitors/{monitor_id}"',
)
replace_once(
    "commercelens/api/domain.py",
    '''@router.get("/v1/product-matches", response_model=list[ProductMatchRecord])
def list_product_matches_endpoint(
''',
    '''@router.get("/v1/product-matches", response_model=list[ProductMatchRecord])
def list_product_matches_endpoint(
''',
)
# Insert the missing GET-by-id endpoint immediately before PATCH if it is not present.
match_get = '''\n\n@router.get("/v1/product-matches/{match_id}", response_model=ProductMatchRecord)\ndef get_product_match_endpoint(\n    match_id: str,\n    repo: Any = Depends(_repo),\n    key: ApiKeyRecord | None = Depends(require_api_key),\n) -> ProductMatchRecord:\n    require_scope(key, "jobs:read")\n    account_id, project_id = _tenant(key)\n    record = repo.get_product_match(match_id, account_id=account_id, project_id=project_id)\n    if not record:\n        raise HTTPException(status_code=404, detail="Product match not found.")\n    return record\n'''
api_domain = Path("commercelens/api/domain.py")
api_text = api_domain.read_text()
patch_anchor = '\n\n@router.patch("/v1/product-matches/{match_id}", response_model=ProductMatchRecord)\n'
if match_get not in api_text:
    if patch_anchor not in api_text:
        raise RuntimeError("Product match PATCH anchor not found")
    api_domain.write_text(api_text.replace(patch_anchor, match_get + patch_anchor, 1))

# SQLite hosted store: additive monitor_id migration, binding, and monitor synchronization.
replace_once(
    "commercelens/jobs/store.py",
    '            self._ensure_column(conn, "monitoring_jobs", "owner", "TEXT")\n',
    '            self._ensure_column(conn, "monitoring_jobs", "owner", "TEXT")\n'
    '            self._ensure_column(conn, "monitoring_jobs", "monitor_id", "TEXT")\n'
    '            conn.execute(\n'
    '                "CREATE INDEX IF NOT EXISTS idx_jobs_monitor_id ON monitoring_jobs(monitor_id)"\n'
    '            )\n',
)
create_job_old = '''    def create_job(self, request: MonitoringJobCreate) -> MonitoringJob:\n        job = MonitoringJob(**request.model_dump())\n        job.next_run_at = self.compute_next_run(job)\n        self.save_job(job)\n        self.record_usage(\n'''
create_job_new = '''    def create_job(self, request: MonitoringJobCreate) -> MonitoringJob:\n        job = MonitoringJob(**request.model_dump())\n        job.next_run_at = self.compute_next_run(job)\n        domain_repo = None\n        monitor = None\n        if job.account_id and job.project_id:\n            from commercelens.domain.repository import domain_repository_for_store\n            from commercelens.domain.service import bind_monitor_to_job, monitor_from_job_create\n\n            domain_repo = domain_repository_for_store(self)\n            monitor = monitor_from_job_create(request)\n            if monitor is not None:\n                monitor = domain_repo.save_monitor(monitor)\n                job.monitor_id = monitor.id\n        self.save_job(job)\n        if domain_repo is not None and monitor is not None:\n            bind_monitor_to_job(domain_repo, monitor, job)\n        self.record_usage(\n'''
replace_once("commercelens/jobs/store.py", create_job_old, create_job_new)
replace_once("commercelens/jobs/postgres_store.py", create_job_old, create_job_new)

replace_once(
    "commercelens/jobs/store.py",
    '''                INSERT INTO monitoring_jobs (id, payload, status, next_run_at, updated_at, account_id, project_id, owner)\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status, next_run_at=excluded.next_run_at, updated_at=excluded.updated_at, account_id=excluded.account_id, project_id=excluded.project_id, owner=excluded.owner\n''',
    '''                INSERT INTO monitoring_jobs (id, payload, status, next_run_at, updated_at, account_id, project_id, owner, monitor_id)\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status, next_run_at=excluded.next_run_at, updated_at=excluded.updated_at, account_id=excluded.account_id, project_id=excluded.project_id, owner=excluded.owner, monitor_id=excluded.monitor_id\n''',
)
replace_once(
    "commercelens/jobs/store.py",
    '''                    job.owner,\n                ),\n            )\n        return job\n\n    def get_job(\n''',
    '''                    job.owner,\n                    job.monitor_id,\n                ),\n            )\n        return job\n\n    def get_job(\n''',
)
replace_once(
    "commercelens/jobs/postgres_store.py",
    '''            conn.execute(\n                """INSERT INTO monitoring_jobs (id, payload, status, next_run_at, updated_at, account_id, project_id, owner) VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status, next_run_at=excluded.next_run_at, updated_at=excluded.updated_at, account_id=excluded.account_id, project_id=excluded.project_id, owner=excluded.owner""",\n''',
    '''            conn.execute(\n                """INSERT INTO monitoring_jobs (id, payload, status, next_run_at, updated_at, account_id, project_id, owner, monitor_id) VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status, next_run_at=excluded.next_run_at, updated_at=excluded.updated_at, account_id=excluded.account_id, project_id=excluded.project_id, owner=excluded.owner, monitor_id=excluded.monitor_id""",\n''',
)
replace_once(
    "commercelens/jobs/postgres_store.py",
    '''                    job.owner,\n                ),\n            )\n        return job\n\n    def get_job(\n''',
    '''                    job.owner,\n                    job.monitor_id,\n                ),\n            )\n        return job\n\n    def get_job(\n''',
)

update_return_old = '''        if job.status != JobStatus.active:\n            job.next_run_at = None\n        return self.save_job(job)\n'''
update_return_new = '''        if job.status != JobStatus.active:\n            job.next_run_at = None\n        saved = self.save_job(job)\n        if saved.account_id and saved.project_id:\n            from commercelens.domain.repository import domain_repository_for_store\n            from commercelens.domain.service import sync_monitor_from_job\n\n            domain_repo = domain_repository_for_store(self)\n            monitor = sync_monitor_from_job(domain_repo, saved)\n            if monitor is not None and saved.monitor_id != monitor.id:\n                saved.monitor_id = monitor.id\n                self.save_job(saved)\n        return saved\n'''
replace_once("commercelens/jobs/store.py", update_return_old, update_return_new)
replace_once("commercelens/jobs/postgres_store.py", update_return_old, update_return_new)

# Postgres migration for the new domain and the job -> monitor reference.
migration = '''    PostgresMigration(\n        id="0003_commerce_domain",\n        description="Add first-class commerce domain records and monitoring job bindings.",\n        statements=(\n            "ALTER TABLE monitoring_jobs ADD COLUMN IF NOT EXISTS monitor_id TEXT",\n            "CREATE INDEX IF NOT EXISTS idx_jobs_monitor_id ON monitoring_jobs(monitor_id)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_sources (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, domain TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_sources_tenant_domain ON commerce_sources(account_id, project_id, domain)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_products (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, identity_key TEXT, updated_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_products_identity ON commerce_products(account_id, project_id, identity_key) WHERE identity_key IS NOT NULL",\n            "CREATE INDEX IF NOT EXISTS idx_commerce_products_tenant ON commerce_products(account_id, project_id, updated_at)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_offers (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, product_id TEXT NOT NULL, source_id TEXT NOT NULL,\n                url TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_offers_source_url ON commerce_offers(account_id, project_id, source_id, url)",\n            "CREATE INDEX IF NOT EXISTS idx_commerce_offers_product ON commerce_offers(account_id, project_id, product_id)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_monitors (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, job_id TEXT, status TEXT NOT NULL,\n                updated_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE INDEX IF NOT EXISTS idx_commerce_monitors_tenant ON commerce_monitors(account_id, project_id, updated_at)",\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_monitors_job ON commerce_monitors(account_id, project_id, job_id) WHERE job_id IS NOT NULL",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_observations (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, source_id TEXT NOT NULL, product_id TEXT NOT NULL,\n                offer_id TEXT NOT NULL, monitor_id TEXT, job_id TEXT, run_id TEXT,\n                captured_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE INDEX IF NOT EXISTS idx_commerce_observations_offer_time ON commerce_observations(account_id, project_id, offer_id, captured_at DESC)",\n            "CREATE INDEX IF NOT EXISTS idx_commerce_observations_product_time ON commerce_observations(account_id, project_id, product_id, captured_at DESC)",\n            "CREATE INDEX IF NOT EXISTS idx_commerce_observations_monitor_time ON commerce_observations(account_id, project_id, monitor_id, captured_at DESC)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_change_events (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, product_id TEXT NOT NULL, offer_id TEXT NOT NULL,\n                monitor_id TEXT, event_type TEXT NOT NULL, changed_at TIMESTAMPTZ NOT NULL,\n                dedupe_key TEXT NOT NULL\n            )\n            """,\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_change_dedupe ON commerce_change_events(account_id, project_id, dedupe_key)",\n            "CREATE INDEX IF NOT EXISTS idx_commerce_change_feed ON commerce_change_events(account_id, project_id, changed_at DESC)",\n            """\n            CREATE TABLE IF NOT EXISTS commerce_product_matches (\n                id TEXT PRIMARY KEY, payload JSONB NOT NULL, account_id TEXT NOT NULL,\n                project_id TEXT NOT NULL, left_product_id TEXT NOT NULL,\n                right_product_id TEXT NOT NULL, status TEXT NOT NULL,\n                updated_at TIMESTAMPTZ NOT NULL\n            )\n            """,\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_product_match_pair ON commerce_product_matches(account_id, project_id, left_product_id, right_product_id)",\n        ),\n    ),\n'''
migrations_path = Path("commercelens/jobs/migrations.py")
migrations_text = migrations_path.read_text()
if 'id="0003_commerce_domain"' not in migrations_text:
    marker = "\n)\n\n\ndef ensure_migration_table"
    if marker not in migrations_text:
        raise RuntimeError("Postgres migration tuple terminator not found")
    migrations_path.write_text(migrations_text.replace(marker, "\n" + migration + marker, 1))

# Results can be mirrored to the first-class domain without changing legacy monitor behavior.
replace_once(
    "commercelens/alerts/runner.py",
    "from __future__ import annotations\n\nfrom pydantic import BaseModel, Field\n",
    "from __future__ import annotations\n\nfrom collections.abc import Callable\n\nfrom pydantic import BaseModel, Field\n",
)
replace_once(
    "commercelens/alerts/runner.py",
    "from commercelens.core.monitor import monitor_product\n",
    "from commercelens.core.monitor import MonitorResult, monitor_product\n",
)
replace_once(
    "commercelens/alerts/runner.py",
    '''def run_monitor_config(\n    config: MonitorConfig,\n    dry_run: bool = False,\n    deliver: bool = True,\n) -> MonitorRunResult:\n''',
    '''def run_monitor_config(\n    config: MonitorConfig,\n    dry_run: bool = False,\n    deliver: bool = True,\n    on_result: Callable[[MonitorResult], None] | None = None,\n) -> MonitorRunResult:\n''',
)
replace_once(
    "commercelens/alerts/runner.py",
    "            result.succeeded += 1\n",
    "            result.succeeded += 1\n            if on_result is not None:\n                on_result(monitor_result)\n",
)

# Hosted workers resolve the canonical domain monitor and persist observations/change events.
replace_once(
    "commercelens/jobs/worker.py",
    "from commercelens.alerts.runner import run_monitor_config\nfrom commercelens.jobs.models import JobRun, WorkerTickResult\n",
    "from commercelens.alerts.runner import run_monitor_config\n"
    "from commercelens.domain.repository import domain_repository_for_store\n"
    "from commercelens.domain.service import effective_job_config, make_job_result_sink\n"
    "from commercelens.jobs.models import JobRun, WorkerTickResult\n",
)
replace_once(
    "commercelens/jobs/worker.py",
    "        self.store = store or JobStore(store_path)\n",
    "        self.store = store or JobStore(store_path)\n        self.domain_repo = domain_repository_for_store(self.store)\n",
)
replace_once(
    "commercelens/jobs/worker.py",
    "                    executor=executor,\n                    worker_concurrency=worker_concurrency,\n",
    "                    executor=executor,\n                    domain_repo=self.domain_repo,\n                    worker_concurrency=worker_concurrency,\n",
)
replace_once(
    "commercelens/jobs/worker.py",
    '''def run_job_now(store: Any, job_id: str, dry_run: bool = False, deliver: bool = True) -> JobRun:\n    job = store.get_job(job_id)\n    if not job:\n        raise ValueError(f"Job not found: {job_id}")\n    run = store.mark_job_run_started(job)\n    try:\n        monitor_result = run_monitor_config(job.config, dry_run=dry_run, deliver=deliver)\n''',
    '''def run_job_now(store: Any, job_id: str, dry_run: bool = False, deliver: bool = True) -> JobRun:\n    job = store.get_job(job_id)\n    if not job:\n        raise ValueError(f"Job not found: {job_id}")\n    run = store.mark_job_run_started(job)\n    domain_repo = domain_repository_for_store(store)\n    config = effective_job_config(domain_repo, job)\n    result_sink = make_job_result_sink(domain_repo, job, run)\n    try:\n        monitor_result = run_monitor_config(\n            config, dry_run=dry_run, deliver=deliver, on_result=result_sink\n        )\n''',
)
replace_once(
    "commercelens/jobs/worker.py",
    "    executor: ThreadPoolExecutor,\n    worker_concurrency: int,\n",
    "    executor: ThreadPoolExecutor,\n    domain_repo: Any,\n    worker_concurrency: int,\n",
)
replace_once(
    "commercelens/jobs/worker.py",
    '''        future = executor.submit(\n            run_monitor_config,\n            job.config,\n            dry_run=dry_run,\n            deliver=deliver,\n        )\n''',
    '''        config = effective_job_config(domain_repo, job)\n        result_sink = make_job_result_sink(domain_repo, job, run)\n        future = executor.submit(\n            run_monitor_config,\n            config,\n            dry_run=dry_run,\n            deliver=deliver,\n            on_result=result_sink,\n        )\n''',
)

# Register the new domain API alongside the existing customer portal router.
replace_once(
    "commercelens/api/__init__.py",
    "from commercelens.api.main import app\nfrom commercelens.api.portal_management import router as portal_management_router\n",
    "from commercelens.api.domain import router as domain_router\n"
    "from commercelens.api.main import app\n"
    "from commercelens.api.portal_management import router as portal_management_router\n",
)
replace_once(
    "commercelens/api/__init__.py",
    '''if not getattr(app.state, "portal_management_installed", False):\n    app.include_router(portal_management_router)\n    app.state.portal_management_installed = True\n\n__all__ = ["app"]\n''',
    '''if not getattr(app.state, "portal_management_installed", False):\n    app.include_router(portal_management_router)\n    app.state.portal_management_installed = True\n\nif not getattr(app.state, "commerce_domain_installed", False):\n    app.include_router(domain_router)\n    app.state.commerce_domain_installed = True\n\n__all__ = ["app"]\n''',
)

# Direct product extraction remains API-compatible but now mirrors successful tenant output into the domain.
main = Path("commercelens/api/main.py")
main_text = main.read_text()
old_record = '''    return store.record_extraction(\n        ExtractionCreate(\n            kind=kind,\n            status=status,\n            url=url,\n            account_id=context["account_id"],\n            project_id=context["project_id"],\n            owner=context["owner"],\n            api_key_id=context["api_key_id"],\n            confidence=confidence,\n            product_count=product_count,\n            payload=payload,\n            error=error,\n            failure_class=failure_class,\n            recommendation=recommendation_for_failure(failure_class),\n            metadata=metadata,\n        )\n    )\n'''
new_record = '''    record = store.record_extraction(\n        ExtractionCreate(\n            kind=kind,\n            status=status,\n            url=url,\n            account_id=context["account_id"],\n            project_id=context["project_id"],\n            owner=context["owner"],\n            api_key_id=context["api_key_id"],\n            confidence=confidence,\n            product_count=product_count,\n            payload=payload,\n            error=error,\n            failure_class=failure_class,\n            recommendation=recommendation_for_failure(failure_class),\n            metadata=metadata,\n        )\n    )\n    if (\n        kind == ExtractionKind.product\n        and status == ExtractionStatus.succeeded\n        and payload\n        and context["account_id"]\n        and context["project_id"]\n    ):\n        try:\n            from commercelens.domain.repository import domain_repository_for_store\n            from commercelens.domain.service import ingest_product_extraction\n\n            ingest_product_extraction(\n                domain_repository_for_store(store),\n                ProductExtractionResult.model_validate(payload),\n                account_id=context["account_id"],\n                project_id=context["project_id"],\n                extraction_id=record.id,\n                provenance={"capture_path": "api_product_extraction", **metadata},\n            )\n        except Exception:\n            LOGGER.exception("commerce_domain_ingest_failed", extra={"extraction_id": record.id})\n    return record\n'''
if new_record not in main_text:
    if old_record not in main_text:
        raise RuntimeError("_record_extraction return block not found")
    main.write_text(main_text.replace(old_record, new_record, 1))

print("Issue 19 integration patches applied")
