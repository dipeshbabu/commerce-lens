from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from commercelens.alerts.config import MonitorTarget
from commercelens.api.auth import get_job_store
from commercelens.api.portal_auth import require_portal_csrf, require_portal_session
from commercelens.api.presentation import escape_html as esc
from commercelens.api.quota import require_quota, require_scope
from commercelens.api.portal_management_core import (
    _audit,
    _existing_target_urls,
    _form,
    _hidden,
    _page,
    _project_query,
    _tenant_job,
    _urls_from_text,
    _validate_targets,
)
from commercelens.jobs.models import JobStatus, MonitoringJobUpdate, ScheduleKind, UsageMetric
from commercelens.jobs.worker import run_job_now

router = APIRouter()


@router.get("/portal/manage/jobs/{job_id}/edit", response_class=HTMLResponse)
def portal_edit_monitor_page(
    job_id: str,
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    job = _tenant_job(store, context, job_id, project_id)
    target_text = "\n".join(str(target.url) for target in job.config.targets)
    content = f"""
    <div class="page-heading">
      <div><h1>Edit monitor</h1><p class="muted">Update targets, schedule, and extraction mode. Existing alert rules remain unchanged.</p></div>
      <a class="button-link" href="/portal/jobs/{esc(job.id)}">Back to job</a>
    </div>
    <form class="form-grid" method="post" action="/portal/manage/jobs/{esc(job.id)}/edit">
      {_hidden("csrf_token", context.csrf_token)}
      {_hidden("project_id", job.project_id or "")}
      <label class="span-2">Monitor name<input name="name" required maxlength="120" value="{esc(job.name)}"></label>
      <label>Schedule
        <select name="schedule_kind">
          <option value="interval" {"selected" if job.schedule_kind == ScheduleKind.interval else ""}>Recurring interval</option>
          <option value="manual" {"selected" if job.schedule_kind == ScheduleKind.manual else ""}>Manual only</option>
        </select>
      </label>
      <label>Interval minutes<input name="interval_minutes" type="number" min="1" value="{esc(job.interval_minutes)}"></label>
      <label>Extraction mode
        <select name="render">
          <option value="false" {"selected" if not job.config.render else ""}>Standard HTML</option>
          <option value="true" {"selected" if job.config.render else ""}>Browser rendered</option>
        </select>
      </label>
      <label class="span-2">Product URLs, one per line<textarea name="urls" rows="10" required>{esc(target_text)}</textarea></label>
      <button class="primary" type="submit">Save changes</button>
    </form>
    """
    return _page("Edit monitor", content, context)


@router.post("/portal/manage/jobs/{job_id}/edit")
async def portal_edit_monitor(
    job_id: str,
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    job = _tenant_job(store, context, job_id, form.get("project_id"))
    existing = _existing_target_urls(
        store,
        context.key.account_id,
        job.project_id,
        exclude_job_id=job.id,
    )
    current_urls = {str(target.url) for target in job.config.targets}
    urls, errors, duplicates = _validate_targets(
        _urls_from_text(form.get("urls", "")),
        existing,
        allow_existing=current_urls,
    )
    if errors or duplicates or not urls:
        raise HTTPException(
            status_code=422,
            detail="; ".join(errors + duplicates) or "At least one valid target is required.",
        )
    render = form.get("render", "false").lower() == "true"
    try:
        schedule_kind = ScheduleKind(form.get("schedule_kind", job.schedule_kind.value))
        interval_minutes = int(form.get("interval_minutes", str(job.interval_minutes)))
        if interval_minutes < 1:
            raise ValueError("Interval minutes must be at least 1.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    config = job.config.model_copy(
        update={
            "render": render,
            "targets": [MonitorTarget(url=url) for url in urls],
        }
    )
    updated = store.update_job(
        job.id,
        MonitoringJobUpdate(
            name=form.get("name", "").strip() or job.name,
            config=config,
            schedule_kind=schedule_kind,
            interval_minutes=interval_minutes,
        ),
        account_id=context.key.account_id,
        project_id=job.project_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found.")
    _audit(
        store,
        context,
        "portal_monitor_edited",
        project_id=job.project_id,
        job_id=job.id,
        metadata={"target_count": len(urls)},
    )
    return RedirectResponse(f"/portal/jobs/{job.id}", status_code=303)


async def _job_action(
    request: Request,
    store: Any,
    job_id: str,
    operation: str,
) -> RedirectResponse:
    context = require_portal_session(request, store)
    require_scope(context.key, "jobs:write")
    form = await _form(request)
    require_portal_csrf(store, context, form.get("csrf_token"))
    job = _tenant_job(store, context, job_id, form.get("project_id"))
    if operation == "pause":
        if job.status != JobStatus.active:
            raise HTTPException(status_code=409, detail="Only an active monitor can be paused.")
        updated = store.update_job(
            job.id,
            MonitoringJobUpdate(status=JobStatus.paused),
            account_id=context.key.account_id,
            project_id=job.project_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Job not found.")
    elif operation == "resume":
        if job.status != JobStatus.paused:
            raise HTTPException(status_code=409, detail="Only a paused monitor can be resumed.")
        updated = store.update_job(
            job.id,
            MonitoringJobUpdate(status=JobStatus.active),
            account_id=context.key.account_id,
            project_id=job.project_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Job not found.")
    elif operation == "run":
        if job.status == JobStatus.disabled:
            raise HTTPException(status_code=409, detail="A disabled monitor cannot be run.")
        require_quota(context.key, UsageMetric.job_run, 1)
        run_job_now(store, job.id)
    elif operation == "delete":
        if not store.delete_job(
            job.id,
            account_id=context.key.account_id,
            project_id=job.project_id,
        ):
            raise HTTPException(status_code=404, detail="Job not found.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported monitor action.")
    _audit(
        store,
        context,
        f"portal_monitor_{operation}",
        project_id=job.project_id,
        job_id=job.id,
        metadata={"previous_status": job.status.value},
    )
    if operation == "delete":
        return RedirectResponse(f"/portal/manage{_project_query(job.project_id)}", status_code=303)
    return RedirectResponse(f"/portal/jobs/{job.id}", status_code=303)


@router.post("/portal/manage/jobs/{job_id}/pause")
async def portal_pause_monitor(
    job_id: str,
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    return await _job_action(request, store, job_id, "pause")


@router.post("/portal/manage/jobs/{job_id}/resume")
async def portal_resume_monitor(
    job_id: str,
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    return await _job_action(request, store, job_id, "resume")


@router.post("/portal/manage/jobs/{job_id}/run")
async def portal_run_monitor(
    job_id: str,
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    return await _job_action(request, store, job_id, "run")


@router.post("/portal/manage/jobs/{job_id}/delete")
async def portal_delete_monitor(
    job_id: str,
    request: Request,
    store: Any = Depends(get_job_store),
) -> RedirectResponse:
    return await _job_action(request, store, job_id, "delete")
