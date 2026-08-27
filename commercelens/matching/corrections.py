from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel

from commercelens.domain.models import (
    ProductMatchRecord,
    ProductMatchStatus,
    utc_now_iso,
)


CorrectionAction = Literal["confirm", "reject", "replace"]


class MatchCorrectionResult(BaseModel):
    updated: ProductMatchRecord
    replacement: ProductMatchRecord | None = None


def correct_product_match(
    repo: Any,
    *,
    account_id: str,
    project_id: str,
    match_id: str,
    action: Literal["confirm", "reject"],
    actor: str | None,
    note: str | None = None,
) -> ProductMatchRecord:
    record = repo.get_product_match(match_id, account_id=account_id, project_id=project_id)
    if record is None:
        raise ValueError("Product match not found.")
    status = ProductMatchStatus.confirmed if action == "confirm" else ProductMatchStatus.rejected
    _append_correction(record, action=action, actor=actor, previous_status=record.status, note=note)
    record.status = status
    record.method = "customer_correction"
    return repo.save_product_match(record)


def replace_product_match(
    repo: Any,
    *,
    account_id: str,
    project_id: str,
    match_id: str,
    replacement_product_id: str,
    actor: str | None,
    note: str | None = None,
) -> MatchCorrectionResult:
    current = repo.get_product_match(match_id, account_id=account_id, project_id=project_id)
    if current is None:
        raise ValueError("Product match not found.")
    anchor_product_id = current.left_product_id
    if replacement_product_id in {anchor_product_id, current.right_product_id}:
        raise ValueError("Choose a different replacement product.")
    if repo.get_product(
        replacement_product_id, account_id=account_id, project_id=project_id
    ) is None:
        raise ValueError("Replacement product not found.")

    previous_status = current.status
    _append_correction(
        current,
        action="replace",
        actor=actor,
        previous_status=previous_status,
        note=note,
        replacement_product_id=replacement_product_id,
    )
    current.status = ProductMatchStatus.rejected
    current.method = "customer_correction"
    current = repo.save_product_match(current)

    replacement = _find_pair(
        repo,
        account_id=account_id,
        project_id=project_id,
        left_product_id=anchor_product_id,
        right_product_id=replacement_product_id,
    )
    if replacement is None:
        left_product_id, right_product_id = _canonical_pair(
            anchor_product_id, replacement_product_id
        )
        replacement = ProductMatchRecord(
            id=_match_id(account_id, project_id, left_product_id, right_product_id),
            account_id=account_id,
            project_id=project_id,
            left_product_id=left_product_id,
            right_product_id=right_product_id,
            confidence=1.0,
            status=ProductMatchStatus.confirmed,
            method="customer_correction",
            metadata={},
        )
    else:
        replacement.status = ProductMatchStatus.confirmed
        replacement.confidence = 1.0
        replacement.method = "customer_correction"
    _append_correction(
        replacement,
        action="confirm",
        actor=actor,
        previous_status=replacement.status,
        note=note,
        replacement_for=match_id,
    )
    replacement = repo.save_product_match(replacement)
    return MatchCorrectionResult(updated=current, replacement=replacement)


def _append_correction(
    record: ProductMatchRecord,
    *,
    action: CorrectionAction,
    actor: str | None,
    previous_status: ProductMatchStatus,
    note: str | None,
    replacement_product_id: str | None = None,
    replacement_for: str | None = None,
) -> None:
    history = list(record.metadata.get("corrections") or [])
    event = {
        "action": action,
        "actor": actor,
        "corrected_at": utc_now_iso(),
        "previous_status": previous_status.value,
    }
    if note:
        event["note"] = note
    if replacement_product_id:
        event["replacement_product_id"] = replacement_product_id
    if replacement_for:
        event["replacement_for"] = replacement_for
    history.append(event)
    record.metadata["corrections"] = history[-100:]
    record.metadata["last_correction"] = event


def _canonical_pair(left_product_id: str, right_product_id: str) -> tuple[str, str]:
    return tuple(sorted((left_product_id, right_product_id)))  # type: ignore[return-value]


def _match_id(account_id: str, project_id: str, left: str, right: str) -> str:
    raw = "|".join((account_id, project_id, left, right)).encode("utf-8")
    return f"match_{hashlib.sha256(raw).hexdigest()[:20]}"


def _find_pair(
    repo: Any,
    *,
    account_id: str,
    project_id: str,
    left_product_id: str,
    right_product_id: str,
) -> ProductMatchRecord | None:
    target = {left_product_id, right_product_id}
    for record in repo.list_product_matches(
        account_id=account_id, project_id=project_id, limit=5000
    ):
        if {record.left_product_id, record.right_product_id} == target:
            return record
    return None
