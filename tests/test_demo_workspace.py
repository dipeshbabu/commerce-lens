from __future__ import annotations

from commercelens.demo import DEMO_ACCOUNT_ID, DEMO_PROJECT_ID, seed_demo_workspace
from commercelens.jobs.store import JobStore


def test_seed_demo_workspace_populates_portal_data(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")

    result = seed_demo_workspace(store)

    assert result["account"]["id"] == DEMO_ACCOUNT_ID
    assert result["project"]["id"] == DEMO_PROJECT_ID
    assert result["token"].startswith("cl_")
    assert result["portal_path"] == "/portal/login"
    assert len(store.list_jobs(account_id=DEMO_ACCOUNT_ID, project_id=DEMO_PROJECT_ID)) == 1
    assert len(store.list_runs(account_id=DEMO_ACCOUNT_ID, project_id=DEMO_PROJECT_ID)) == 2
    assert len(store.list_extractions(account_id=DEMO_ACCOUNT_ID, project_id=DEMO_PROJECT_ID)) == 4
    assert (
        store.usage_summary(account_id=DEMO_ACCOUNT_ID, project_id=DEMO_PROJECT_ID).total_quantity
        == 167
    )
