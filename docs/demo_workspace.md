# Demo Workspace

CommerceLens includes a seed command that creates a realistic customer workspace
for local demos, screenshots, onboarding walkthroughs, and portal testing.

## Seed the Demo

```bash
commercelens seed-demo --jobs-db commercelens_demo.db --out demo_workspace.json
```

The command creates:

- a trialing Team-plan account
- a project named `Competitor Price Watch`
- an owner member
- a tenant-scoped API key
- a daily monitoring job with three product targets
- successful and failed job-run history
- usage, quota, alert, and extraction records

The returned JSON includes the one-time API token and a `portal_path` value.
Run the API against the same database and open that path:

```bash
set COMMERCELENS_JOBS_DB=commercelens_demo.db
set COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

```text
http://127.0.0.1:8000/portal?api_key=cl_REPLACE_WITH_TOKEN
```

Use this workspace when preparing product screenshots, customer demos, and
regression checks for the customer portal.
