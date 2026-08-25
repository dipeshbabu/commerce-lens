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

The returned JSON includes the one-time API token and `/portal/login` as the
`portal_path`. Run the API against the same database and open that path:

```bash
set COMMERCELENS_JOBS_DB=commercelens_demo.db
set COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

```text
http://localhost:8000/portal/login
```

Enter the returned API token in the sign in form. CommerceLens exchanges it for
an expiring browser session, so the token does not appear in portal URLs.

Use this workspace when preparing product screenshots, customer demos, and
regression checks for the customer portal.
