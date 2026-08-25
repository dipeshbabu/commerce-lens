from __future__ import annotations

from urllib.parse import urlparse

from commercelens.jobs.models import ExtractionRecord, FailureClass, JobRun


RECOMMENDATIONS: dict[FailureClass, str] = {
    FailureClass.blocked: "Review robots, headers, and customer permission. Consider a rendered fetch or site-specific adapter.",
    FailureClass.invalid_url: "Fix the URL and retry the request.",
    FailureClass.network_error: "Retry later and verify DNS, TLS, and upstream connectivity.",
    FailureClass.parser_low_confidence: "Inspect the extraction payload and add a fixture or adapter for this page shape.",
    FailureClass.queue_deferred: "The worker deferred this run because the domain concurrency limit was reached.",
    FailureClass.quota_exceeded: "Increase the API key quota or wait for the next billing period.",
    FailureClass.rate_limited: "Reduce polling frequency or add per-domain concurrency limits before retrying.",
    FailureClass.render_required: "Retry with render=true or enable rendering on the monitoring target.",
    FailureClass.timeout: "Increase timeout, reduce concurrency, or retry with rendering disabled if possible.",
    FailureClass.unknown: "Inspect the raw error and retry after confirming the target is reachable.",
}


def classify_failure(
    error: str | None, *, confidence: float | None = None, metadata: dict | None = None
) -> FailureClass | None:
    if confidence is not None and confidence < 0.55:
        return FailureClass.parser_low_confidence
    if not error:
        return None
    text = error.lower()
    metadata = metadata or {}
    if metadata.get("failure_class"):
        try:
            return FailureClass(str(metadata["failure_class"]))
        except ValueError:
            return FailureClass.unknown
    if "quota" in text or "monthly domain budget" in text:
        return FailureClass.quota_exceeded
    if "429" in text or "rate limit" in text or "too many requests" in text:
        return FailureClass.rate_limited
    if (
        "403" in text
        or "401" in text
        or "blocked" in text
        or "forbidden" in text
        or "captcha" in text
    ):
        return FailureClass.blocked
    if (
        "render=true requires a url" in text
        or "javascript" in text
        or "render" in text
        and "required" in text
    ):
        return FailureClass.render_required
    if "timeout" in text or "timed out" in text:
        return FailureClass.timeout
    if "invalid url" in text or "missing scheme" in text or "url" in text and "invalid" in text:
        return FailureClass.invalid_url
    if (
        "dns" in text
        or "connection" in text
        or "network" in text
        or "tls" in text
        or "ssl" in text
        or "host" in text
    ):
        return FailureClass.network_error
    return FailureClass.unknown


def recommendation_for_failure(failure_class: FailureClass | None) -> str | None:
    return RECOMMENDATIONS.get(failure_class) if failure_class else None


def failure_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc.lower() or None


def failed_run_issue(run: JobRun) -> dict | None:
    if not run.error and run.status.value != "failed":
        return None
    failure_class = run.failure_class or classify_failure(run.error)
    return {
        "source": "run",
        "id": run.id,
        "job_id": run.job_id,
        "account_id": run.account_id,
        "project_id": run.project_id,
        "status": run.status.value,
        "failure_class": failure_class.value if failure_class else None,
        "error": run.error,
        "recommendation": run.recommendation or recommendation_for_failure(failure_class),
        "created_at": run.created_at,
    }


def failed_extraction_issue(record: ExtractionRecord) -> dict | None:
    if not record.error and record.status.value != "failed":
        return None
    failure_class = record.failure_class or classify_failure(
        record.error, confidence=record.confidence, metadata=record.metadata
    )
    return {
        "source": "extraction",
        "id": record.id,
        "account_id": record.account_id,
        "project_id": record.project_id,
        "status": record.status.value,
        "kind": record.kind.value,
        "url": record.url,
        "domain": failure_domain(record.url),
        "failure_class": failure_class.value if failure_class else None,
        "error": record.error,
        "recommendation": record.recommendation or recommendation_for_failure(failure_class),
        "created_at": record.created_at,
    }
