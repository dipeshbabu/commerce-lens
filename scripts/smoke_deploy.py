from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


PRODUCT_HTML = """
<html>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "CommerceLens Smoke Product",
    "brand": {"@type": "Brand", "name": "CommerceLens"},
    "offers": {
      "@type": "Offer",
      "price": "19.99",
      "priceCurrency": "USD",
      "availability": "https://schema.org/InStock"
    }
  }
  </script>
</html>
"""


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    admin_token: str
    owner: str
    timeout_seconds: float
    stripe_price_id: str | None = None


def _url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _raise_for_status(response: httpx.Response, label: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:500]
        raise RuntimeError(f"{label} failed: HTTP {response.status_code}: {body}") from exc


def run_smoke(config: SmokeConfig) -> None:
    admin_headers = {"X-Admin-Token": config.admin_token}
    with httpx.Client(timeout=config.timeout_seconds, follow_redirects=True) as client:
        health = client.get(_url(config.base_url, "/health"))
        _raise_for_status(health, "health")
        print(f"health: {health.json()['status']}")

        ready = client.get(_url(config.base_url, "/ready"))
        _raise_for_status(ready, "ready")
        ready_payload = ready.json()
        print(
            "ready: "
            f"store={ready_payload['store_backend']} "
            f"api_key_required={ready_payload['api_key_required']}"
        )

        onboarding = client.post(
            _url(config.base_url, "/v1/onboarding"),
            headers=admin_headers,
            json={
                "account_name": "Smoke Account",
                "owner_email": config.owner,
                "project_name": "Smoke Project",
                "billing_plan": "team",
                "monthly_domain_quotas": {"example.com": 1, "*": 100},
            },
        )
        _raise_for_status(onboarding, "onboarding")
        onboarding_payload = onboarding.json()
        account_id = onboarding_payload["account"]["id"]
        project_payload = onboarding_payload["project"]
        project_id = project_payload["id"]
        token = onboarding_payload["token"]
        portal_path = onboarding_payload["portal_path"]
        print(f"account: {account_id}")
        print(f"project: {project_id}")
        print(f"api_key: {token[:10]}...")

        portal = client.get(_url(config.base_url, portal_path))
        _raise_for_status(portal, "customer portal")
        if "customer portal" not in portal.text:
            raise RuntimeError("customer portal response did not contain marker")
        print("portal: ok")

        extraction = client.post(
            _url(config.base_url, "/v1/extract/product"),
            headers={"X-API-Key": token},
            json={
                "url": "https://example.com/products/smoke",
                "html": PRODUCT_HTML,
            },
        )
        _raise_for_status(extraction, "product extraction")
        extraction_payload = extraction.json()
        print(f"extract_product: {extraction_payload['product']['name']}")

        quota_block = client.post(
            _url(config.base_url, "/v1/extract/product"),
            headers={"X-API-Key": token},
            json={
                "url": "https://example.com/products/smoke-quota",
                "html": PRODUCT_HTML,
            },
        )
        if quota_block.status_code != 429:
            raise RuntimeError(f"quota check failed: expected HTTP 429, got {quota_block.status_code}")
        print("quota: blocked")

        failed_extraction = client.post(
            _url(config.base_url, "/v1/extract/product"),
            headers={"X-API-Key": token},
            json={"html": PRODUCT_HTML, "render": True},
        )
        if failed_extraction.status_code != 400:
            raise RuntimeError(f"failure triage setup failed: HTTP {failed_extraction.status_code}")

        job = client.post(
            _url(config.base_url, "/v1/jobs"),
            headers={"X-API-Key": token},
            json={
                "name": "Smoke Monitor",
                "interval_minutes": 1440,
                "account_id": account_id,
                "project_id": project_id,
                "config": {
                    "targets": [{"url": "https://example.org/products/smoke", "tags": ["smoke"]}],
                    "rules": [{"name": "any-change", "condition": "any_change"}],
                    "channels": [],
                },
            },
        )
        _raise_for_status(job, "create job")
        print(f"job: {job.json()['id']}")

        worker = client.post(
            _url(config.base_url, "/v1/worker/tick"),
            headers={"X-API-Key": token},
            params={"dry_run": "true", "domain_concurrency": 1},
        )
        _raise_for_status(worker, "worker tick")
        print(f"worker_tick: due={worker.json()['due_jobs']}")

        usage = client.get(_url(config.base_url, "/v1/usage/summary"), headers={"X-API-Key": token})
        _raise_for_status(usage, "usage summary")
        print(f"usage_total: {usage.json()['total_quantity']}")

        issues = client.get(_url(config.base_url, "/v1/issues"), headers={"X-API-Key": token})
        _raise_for_status(issues, "issues")
        if issues.json()["count"] < 1:
            raise RuntimeError("issues response did not include expected failed extraction")
        print(f"issues: {issues.json()['count']}")

        if config.stripe_price_id:
            checkout = client.post(
                _url(config.base_url, "/v1/billing/stripe/checkout-session"),
                headers=admin_headers,
                json={
                    "account_id": account_id,
                    "price_id": config.stripe_price_id,
                    "success_url": "https://example.com/success",
                    "cancel_url": "https://example.com/cancel",
                    "billing_plan": "team",
                },
            )
            _raise_for_status(checkout, "stripe checkout")
            if not checkout.json()["url"].startswith("https://"):
                raise RuntimeError("stripe checkout response did not include a hosted URL")
            print("stripe_checkout: ok")

        dashboard = client.get(
            _url(config.base_url, "/dashboard"),
            params={"admin_token": config.admin_token},
        )
        _raise_for_status(dashboard, "dashboard")
        if "CommerceLens" not in dashboard.text:
            raise RuntimeError("dashboard response did not contain CommerceLens marker")
        print("dashboard: ok")


def parse_args(argv: list[str]) -> SmokeConfig:
    parser = argparse.ArgumentParser(description="Smoke test a deployed CommerceLens API.")
    parser.add_argument("--base-url", required=True, help="Base API URL, e.g. https://app.onrender.com")
    parser.add_argument("--admin-token", required=True, help="COMMERCELENS_ADMIN_TOKEN value")
    parser.add_argument("--owner", default="ops@example.com", help="Owner email for smoke records")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--stripe-price-id", default=None, help="Optional Stripe price ID to verify checkout creation")
    args = parser.parse_args(argv)
    return SmokeConfig(
        base_url=args.base_url,
        admin_token=args.admin_token,
        owner=args.owner,
        timeout_seconds=args.timeout_seconds,
        stripe_price_id=args.stripe_price_id,
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv or sys.argv[1:])
    try:
        run_smoke(config)
    except Exception as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    print("smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
