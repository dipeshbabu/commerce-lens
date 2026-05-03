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

        account = client.post(
            _url(config.base_url, "/v1/accounts"),
            headers=admin_headers,
            json={"name": "Smoke Account", "owner": config.owner},
        )
        _raise_for_status(account, "create account")
        account_payload = account.json()
        account_id = account_payload["id"]
        print(f"account: {account_id}")

        project = client.post(
            _url(config.base_url, f"/v1/accounts/{account_id}/projects"),
            headers=admin_headers,
            json={"name": "Smoke Project", "slug": "smoke"},
        )
        _raise_for_status(project, "create project")
        project_payload = project.json()
        project_id = project_payload["id"]
        print(f"project: {project_id}")

        api_key = client.post(
            _url(config.base_url, "/v1/api-keys"),
            headers=admin_headers,
            json={
                "name": "Smoke API Key",
                "account_id": account_id,
                "project_id": project_id,
                "owner": config.owner,
                "scopes": ["*"],
            },
        )
        _raise_for_status(api_key, "create api key")
        token = api_key.json()["token"]
        print(f"api_key: {token[:10]}...")

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

        usage = client.get(_url(config.base_url, "/v1/usage/summary"), headers={"X-API-Key": token})
        _raise_for_status(usage, "usage summary")
        print(f"usage_total: {usage.json()['total_quantity']}")

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
    args = parser.parse_args(argv)
    return SmokeConfig(
        base_url=args.base_url,
        admin_token=args.admin_token,
        owner=args.owner,
        timeout_seconds=args.timeout_seconds,
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
