from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from commercelens.api.auth import get_job_store
from commercelens.api.portal_auth import require_portal_csrf, require_portal_session
from commercelens.api.portal_management_core import (
    _available_projects,
    _form,
    _page,
    _select_project,
)
from commercelens.api.presentation import escape_html as esc, table
from commercelens.api.quota import require_scope
from commercelens.domain.repository import domain_repository_for_store
from commercelens.matching.corrections import correct_product_match, replace_product_match

router = APIRouter()


def _product_label(product: Any | None, product_id: str) -> str:
    if product is None:
        return product_id
    name = product.name or product.identity_key or product.id
    brand = f"{product.brand} · " if product.brand else ""
    return f"{brand}{name} ({product.id})"


def _correction_text(match: Any) -> str:
    event = match.metadata.get("last_correction") or {}
    if not event:
        return "—"
    actor = event.get("actor") or "unknown"
    return f"{event.get('action', 'updated')} by {actor} at {event.get('corrected_at', 'unknown')}"


def _can_write(context: Any) -> bool:
    scopes = set(context.key.scopes)
    return "*" in scopes or "match:write" in scopes


@router.get("/portal/matches", response_class=HTMLResponse)
def portal_product_matches(
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if selected is None:
        return _page(
            "Product matches",
            '<h1>Product matches</h1><section class="notice warning" role="status">Create or select a project before reviewing product matches.</section>',
            context,
        )

    repo = domain_repository_for_store(store)
    products = repo.list_products(
        account_id=context.key.account_id or "", project_id=selected.id, limit=5000
    )
    product_by_id = {product.id: product for product in products}
    matches = repo.list_product_matches(
        account_id=context.key.account_id or "", project_id=selected.id, limit=5000
    )
    csrf = esc(context.csrf_token)
    can_write = _can_write(context)
    replacement_options = "".join(
        f'<option value="{esc(product.id)}">{esc(_product_label(product, product.id))}</option>'
        for product in products
    )

    rows: list[list[object]] = []
    for match in matches:
        hidden = (
            f'<input type="hidden" name="csrf_token" value="{csrf}">'
            f'<input type="hidden" name="project_id" value="{esc(selected.id)}">'
        )
        actions = ""
        if can_write:
            actions = (
                '<div class="table-actions">'
                f'<form class="action-form" method="post" action="/portal/matches/{esc(match.id)}/confirm">{hidden}<button type="submit">Confirm</button></form>'
                f'<form class="action-form" method="post" action="/portal/matches/{esc(match.id)}/reject">{hidden}<button class="danger-button" type="submit">Reject</button></form>'
                "</div>"
                '<form class="inline-form" method="post" '
                f'action="/portal/matches/{esc(match.id)}/replace">{hidden}'
                f'<label>Replace with<select name="replacement_product_id" required><option value="">Choose product</option>{replacement_options}</select></label>'
                '<label>Correction note<input name="note" maxlength="240" placeholder="optional"></label>'
                '<button type="submit">Replace</button></form>'
            )
        rows.append(
            [
                f"<code>{esc(match.id)}</code>",
                esc(_product_label(product_by_id.get(match.left_product_id), match.left_product_id)),
                esc(_product_label(product_by_id.get(match.right_product_id), match.right_product_id)),
                esc(f"{match.confidence:.3f}"),
                esc(match.status.value),
                esc(match.method or "—"),
                esc(_correction_text(match)),
                actions or "read only",
            ]
        )

    projects = _available_projects(store, context)
    selector = ""
    if len(projects) > 1:
        options = "".join(
            f'<option value="{esc(project.id)}" {"selected" if project.id == selected.id else ""}>{esc(project.name)}</option>'
            for project in projects
        )
        selector = (
            '<form class="inline-form" method="get" action="/portal/matches">'
            f'<label>Project<select name="project_id">{options}</select></label>'
            '<button type="submit">Switch project</button></form>'
        )

    warning = ""
    if not can_write:
        warning = '<section class="notice warning" role="status">This key can review product matches but needs <code>match:write</code> to correct them.</section>'
    empty = (
        '<section class="notice warning" role="status">No product matches have been proposed for this project yet.</section>'
        if not matches
        else ""
    )
    content = f"""
    <div class="page-heading">
      <div><h1>Product matches</h1><p class="muted">Confirm, reject, or replace cross-store product identities. Corrections update comparisons immediately.</p></div>
      <a class="button-link" href="/portal/products?project_id={esc(selected.id)}">Products</a>
    </div>
    {selector}
    {warning}
    {empty}
    <section class="panel">
      {table(["Match", "Product", "Equivalent", "Confidence", "Status", "Method", "Last correction", "Actions"], rows)}
    </section>
    """
    return _page("Product matches", content, context)


async def _correct(
    request: Request,
    match_id: str,
    action: str,
    store: Any,
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "match:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    selected = _select_project(store, context, form.get("project_id"))
    if selected is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    repo = domain_repository_for_store(store)
    try:
        correct_product_match(
            repo,
            account_id=context.key.account_id or "",
            project_id=selected.id,
            match_id=match_id,
            action=action,  # type: ignore[arg-type]
            actor=context.key.owner or context.key.id,
            note=form.get("note") or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(
        f"/portal/matches?{urlencode({'project_id': selected.id})}", status_code=303
    )


@router.post("/portal/matches/{match_id}/confirm")
async def portal_confirm_match(
    request: Request, match_id: str, store: Any = Depends(get_job_store)
) -> RedirectResponse:
    return await _correct(request, match_id, "confirm", store)


@router.post("/portal/matches/{match_id}/reject")
async def portal_reject_match(
    request: Request, match_id: str, store: Any = Depends(get_job_store)
) -> RedirectResponse:
    return await _correct(request, match_id, "reject", store)


@router.post("/portal/matches/{match_id}/replace")
async def portal_replace_match(
    request: Request, match_id: str, store: Any = Depends(get_job_store)
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "match:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    selected = _select_project(store, context, form.get("project_id"))
    if selected is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    replacement_product_id = form.get("replacement_product_id", "").strip()
    if not replacement_product_id:
        raise HTTPException(status_code=422, detail="Choose a replacement product.")
    repo = domain_repository_for_store(store)
    try:
        replace_product_match(
            repo,
            account_id=context.key.account_id or "",
            project_id=selected.id,
            match_id=match_id,
            replacement_product_id=replacement_product_id,
            actor=context.key.owner or context.key.id,
            note=form.get("note") or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(
        f"/portal/matches?{urlencode({'project_id': selected.id})}", status_code=303
    )
