from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.api.auth import get_job_store
from commercelens.api.portal_auth import require_portal_csrf, require_portal_session
from commercelens.api.presentation import escape_html as esc, table
from commercelens.api.quota import require_quota, require_scope
from commercelens.api.portal_management_core import (
    _MAX_TARGETS,
    _audit,
    _available_projects,
    _existing_target_urls,
    _form,
    _hidden,
    _job_rows,
    _monitor_form,
    _page,
    _preview_allowed,
    _preview_product,
    _require_account,
    _resolve_category_urls,
    _rules_from_form,
    _select_project,
    _urls_from_csv,
    _urls_from_text,
    _validate_targets,
    _write_allowed,
)
from commercelens.jobs.models import (
    MonitoringJobCreate,
    ProjectCreate,
    ScheduleKind,
    UsageMetric,
)

router = APIRouter()


@router.get("/portal/manage", response_class=HTMLResponse)
def portal_manage(
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    projects = _available_projects(store, context)
    selected = _select_project(store, context, project_id)
    can_write = _write_allowed(context)
    can_preview = _preview_allowed(context)
    project_options = "".join(
        f'<option value="{esc(project.id)}" {"selected" if selected and project.id == selected.id else ""}>{esc(project.name)} ({esc(project.id)})</option>'
        for project in projects
    )
    project_selector = (
        f"""
    <section class="panel">
      <h2>Project</h2>
      <form class="inline-form" method="get" action="/portal/manage">
        <label>Selected project
          <select name="project_id">{project_options}</select>
        </label>
        <button type="submit">Switch project</button>
      </form>
    </section>
    """
        if projects
        else """
    <section class="panel"><h2>Project</h2><p class="muted">No project is available for this account yet.</p></section>
    """
    )
    create_project = ""
    if context.key.project_id is None and can_write:
        create_project = f"""
        <section class="panel">
          <h2>Create a project</h2>
          <form class="form-grid compact" method="post" action="/portal/manage/projects">
            <input type="hidden" name="csrf_token" value="{esc(context.csrf_token)}">
            <label>Project name<input name="name" required maxlength="120"></label>
            <label>Slug<input name="slug" pattern="[a-zA-Z0-9_-]+" placeholder="optional-slug"></label>
            <button type="submit">Create project</button>
          </form>
        </section>
        """
    elif context.key.project_id is not None:
        create_project = '<p class="muted">This portal key is locked to one project. Use an account-level portal key to create or switch projects.</p>'

    manage_body = ""
    if selected:
        jobs = store.list_jobs(limit=100, account_id=context.key.account_id, project_id=selected.id)
        manage_body = f"""
        <section class="panel">
          <h2>Monitors</h2>
          {table(["ID", "Name", "Status", "Schedule", "Interval", "Targets", "Manage"], _job_rows(jobs, selected.id, context))}
        </section>
        """
        if can_write and can_preview:
            manage_body += _monitor_form(context, selected)
        elif not can_write:
            manage_body += '<p class="danger" role="alert">This key can view monitors but does not have jobs:write permission.</p>'
        else:
            manage_body += '<p class="danger" role="alert">This key can manage monitors but does not have extract:write permission for onboarding previews.</p>'

    content = f"""
    <div class="page-heading">
      <div><h1>Monitor management</h1><p class="muted">Create, preview, activate, and control monitors without leaving the customer portal.</p></div>
      <a class="button-link" href="/portal">Back to overview</a>
    </div>
    {project_selector}
    {create_project}
    {manage_body}
    """
    return _page("Monitor management", content, context)


@router.post("/portal/manage/projects")
async def portal_create_project(
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    account_id = _require_account(context)
    if context.key.project_id is not None:
        raise HTTPException(status_code=403, detail="This portal key is locked to one project.")
    name = form.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required.")
    slug = form.get("slug", "").strip() or None
    project = store.create_project(account_id, ProjectCreate(name=name, slug=slug))
    _audit(
        store,
        context,
        "portal_project_created",
        project_id=project.id,
        metadata={"project_name": project.name},
    )
    return RedirectResponse(
        f"/portal/manage?{urlencode({'project_id': project.id})}", status_code=303
    )


@router.post("/portal/manage/preview", response_class=HTMLResponse)
async def portal_monitor_preview(
    request: Request,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    require_scope(context.key, "extract:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    selected = _select_project(store, context, form.get("project_id"))
    if not selected:
        raise HTTPException(status_code=400, detail="Create or select a project first.")

    direct = _urls_from_text(form.get("urls", ""))
    csv_urls, csv_warnings = _urls_from_csv(form.get("csv_file", ""))
    category_raw = _urls_from_text(form.get("category_urls", ""))
    valid_categories, category_errors, category_duplicates = _validate_targets(
        category_raw, set()
    )
    existing = _existing_target_urls(store, context.key.account_id, selected.id)
    valid, errors, duplicates = _validate_targets(direct + csv_urls, existing)
    errors.extend(category_errors)
    duplicates.extend(category_duplicates)

    name = form.get("name", "").strip()
    if not name:
        errors.append("Monitor name is required.")

    render_raw = form.get("render", "false").lower()
    if render_raw not in {"true", "false"}:
        errors.append("Extraction mode is invalid.")
    render = render_raw == "true"

    schedule_kind: ScheduleKind | None = None
    interval_minutes: int | None = None
    try:
        schedule_kind = ScheduleKind(form.get("schedule_kind", "interval"))
        interval_minutes = int(form.get("interval_minutes", "360"))
        if interval_minutes < 1:
            raise ValueError("Interval minutes must be at least 1.")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        rules = _rules_from_form(form)
    except (ValueError, ValidationError) as exc:
        errors.append(str(exc))
        rules = []

    if len(valid) > _MAX_TARGETS:
        errors.append(f"A monitor can contain at most {_MAX_TARGETS} product targets.")

    category_products: list[str] = []
    listing_previews: list[dict[str, Any]] = []
    warnings = list(csv_warnings)
    if valid_categories and not errors and not duplicates:
        try:
            category_products, listing_previews, category_warnings = _resolve_category_urls(
                store,
                context,
                valid_categories,
                render=render,
                project_id=selected.id,
            )
            warnings.extend(category_warnings)
        except (ValueError, HTTPException) as exc:
            if isinstance(exc, HTTPException):
                raise
            errors.append(str(exc))

    resolved, resolved_errors, resolved_duplicates = _validate_targets(
        valid + category_products, existing
    )
    errors.extend(resolved_errors)
    duplicates.extend(resolved_duplicates)
    if len(resolved) > _MAX_TARGETS:
        errors.append(f"A monitor can contain at most {_MAX_TARGETS} product targets.")
    if not resolved and not errors and not duplicates:
        errors.append(
            "No valid product targets were found. Add a product URL, CSV URL, or a category page that resolves products."
        )

    preview_payload: dict[str, Any] | None = None
    preview_error: str | None = None
    if resolved and not errors and not duplicates:
        preview_payload, preview_error = _preview_product(
            store,
            context,
            resolved[0],
            render=render,
            project_id=selected.id,
        )
        if preview_error:
            errors.append(f"First extraction preview failed: {preview_error}")

    validation_rows: list[list[object]] = [
        ["Monitor name", esc(name or "missing")],
        ["Valid product targets", esc(len(resolved))],
        ["Category pages", esc(len(valid_categories))],
        ["Schedule", esc(schedule_kind.value if schedule_kind else "invalid")],
        ["Interval minutes", esc(interval_minutes if interval_minutes is not None else "invalid")],
        ["Alert rules", esc(len(rules))],
        ["Extraction mode", esc("browser rendered" if render else "standard HTML")],
    ]
    problems = errors + duplicates
    problem_html = (
        '<section class="notice error" role="alert"><strong>Fix these items before activation</strong><ul>'
        + "".join(f"<li>{esc(item)}</li>" for item in problems)
        + "</ul></section>"
        if problems
        else '<section class="notice success" role="status"><strong>Validation passed.</strong> The monitor is ready to activate.</section>'
    )
    warning_html = (
        '<section class="notice warning"><strong>Notes</strong><ul>'
        + "".join(f"<li>{esc(item)}</li>" for item in warnings)
        + "</ul></section>"
        if warnings
        else ""
    )
    target_rows = [[esc(index + 1), esc(url)] for index, url in enumerate(resolved[:100])]
    if len(resolved) > 100:
        target_rows.append(["…", esc(f"{len(resolved) - 100} more targets")])

    if preview_payload:
        product = preview_payload.get("product", preview_payload)
        product_rows = [
            ["URL", esc(resolved[0])],
            ["Name", esc(product.get("name"))],
            ["Brand", esc(product.get("brand"))],
            ["Price", esc((product.get("price") or {}).get("amount"))],
            ["Currency", esc((product.get("price") or {}).get("currency"))],
            ["Availability", esc(product.get("availability"))],
            ["Confidence", esc(preview_payload.get("confidence"))],
        ]
        preview_html = f"<h2>First extraction preview</h2>{table(['Field', 'Value'], product_rows)}"
    elif preview_error:
        preview_html = f'<section class="notice error" role="alert"><strong>First extraction could not be previewed.</strong><p>{esc(preview_error)}</p></section>'
    elif listing_previews:
        first = listing_previews[0]
        preview_html = (
            "<h2>Category extraction preview</h2>"
            + table(
                ["Field", "Value"],
                [
                    ["Category URL", esc(first.get("url"))],
                    ["Products discovered", esc(first.get("product_count"))],
                    ["Confidence", esc(first.get("confidence"))],
                ],
            )
        )
    else:
        preview_html = '<p class="muted">Add at least one valid product or category URL to preview extraction.</p>'

    activation = ""
    if resolved and not problems and preview_payload is not None:
        activation = f"""
        <form class="form-grid compact" method="post" action="/portal/manage/monitors">
          {_hidden("csrf_token", context.csrf_token)}
          {_hidden("project_id", selected.id)}
          {_hidden("name", form.get("name", "").strip())}
          {_hidden("schedule_kind", form.get("schedule_kind", "interval"))}
          {_hidden("interval_minutes", form.get("interval_minutes", "360"))}
          {_hidden("render", "true" if render else "false")}
          {_hidden("resolved_urls", "\n".join(resolved))}
          {_hidden("alert_name", form.get("alert_name", ""))}
          {_hidden("alert_condition", form.get("alert_condition", ""))}
          {_hidden("alert_threshold", form.get("alert_threshold", ""))}
          {_hidden("destination_type", form.get("destination_type", ""))}
          {_hidden("destination_value", form.get("destination_value", ""))}
          <button class="primary" type="submit">Activate monitor</button>
        </form>
        """
    content = f"""
    <div class="page-heading">
      <div><h1>Review monitor</h1><p class="muted">Nothing is activated until you confirm this page.</p></div>
      <a class="button-link" href="/portal/manage?project_id={esc(selected.id)}">Edit inputs</a>
    </div>
    {problem_html}
    {warning_html}
    {table(["Check", "Result"], validation_rows)}
    <h2>Resolved product targets</h2>
    {table(["#", "URL"], target_rows)}
    {preview_html}
    {activation}
    """
    return _page("Review monitor", content, context, status_code=422 if problems else 200)


@router.post("/portal/manage/monitors")
async def portal_create_monitor(
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    selected = _select_project(store, context, form.get("project_id"))
    if not selected:
        raise HTTPException(status_code=400, detail="Create or select a project first.")
    name = form.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Monitor name is required.")
    existing = _existing_target_urls(store, context.key.account_id, selected.id)
    resolved, errors, duplicates = _validate_targets(
        _urls_from_text(form.get("resolved_urls", "")), existing
    )
    if errors or duplicates or not resolved:
        detail = "; ".join(errors + duplicates) or "At least one valid target is required."
        raise HTTPException(status_code=422, detail=detail)
    if len(resolved) > _MAX_TARGETS:
        raise HTTPException(status_code=422, detail=f"Use at most {_MAX_TARGETS} product targets.")
    render = form.get("render", "false").lower() == "true"
    try:
        rules = _rules_from_form(form)
        schedule_kind = ScheduleKind(form.get("schedule_kind", "interval"))
        interval_minutes = int(form.get("interval_minutes", "360"))
        if interval_minutes < 1:
            raise ValueError("Interval minutes must be at least 1.")
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    require_quota(context.key, UsageMetric.api_request, 1)
    job = store.create_job(
        MonitoringJobCreate(
            name=name,
            config=MonitorConfig(
                render=render,
                targets=[MonitorTarget(url=url) for url in resolved],
                rules=rules,
            ),
            schedule_kind=schedule_kind,
            interval_minutes=interval_minutes,
            owner=context.key.owner,
            account_id=context.key.account_id,
            project_id=selected.id,
        )
    )
    _audit(
        store,
        context,
        "portal_monitor_activated",
        project_id=selected.id,
        job_id=job.id,
        metadata={"target_count": len(resolved), "schedule_kind": schedule_kind.value},
    )
    return RedirectResponse(f"/portal/jobs/{job.id}", status_code=303)
