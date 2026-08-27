from __future__ import annotations

import json
from html import escape
from typing import Sequence


def escape_html(value: object) -> str:
    return escape("" if value is None else str(value))


def dashboard_shell(title: str, content: str, token_query: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(title)} - CommerceLens</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #17202a; background: #f6f8fb; }}
    header {{ background: #111827; color: white; padding: 18px 28px; display: flex; justify-content: space-between; align-items: center; }}
    header a {{ color: #dbeafe; text-decoration: none; margin-left: 18px; }}
    main {{ padding: 28px; max-width: 1280px; margin: 0 auto; }}
    h1 {{ font-size: 28px; margin: 0 0 20px; }}
    h2 {{ font-size: 18px; margin: 26px 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .metric {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
    .metric strong {{ display: block; font-size: 26px; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #f9fafb; color: #4b5563; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    form {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; margin: 12px 0; display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    label {{ display: grid; gap: 4px; font-size: 13px; color: #4b5563; }}
    input, select {{ font: inherit; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 6px; }}
    button {{ font: inherit; padding: 9px 12px; border: 1px solid #111827; border-radius: 6px; background: #111827; color: white; cursor: pointer; align-self: end; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: #6b7280; }}
    .danger {{ color: #b91c1c; }}
    @media (max-width: 900px) {{ .grid, form {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 18px; }} }}
    @media (max-width: 560px) {{ form {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <div><strong>CommerceLens</strong> <span class="muted">operator dashboard</span></div>
    <nav><a href="/dashboard{token_query}">Dashboard</a><a href="/docs">API Docs</a></nav>
  </header>
  <main>{content}</main>
</body>
</html>"""


def portal_shell(title: str, content: str, csrf_token: str = "") -> str:
    session_actions = ""
    if csrf_token:
        escaped_token = escape_html(csrf_token)
        session_actions = f"""
      <form class="session-action" method="post" action="/portal/session/rotate">
        <input type="hidden" name="csrf_token" value="{escaped_token}">
        <button type="submit">Rotate session</button>
      </form>
      <form class="session-action" method="post" action="/portal/logout">
        <input type="hidden" name="csrf_token" value="{escaped_token}">
        <button type="submit">Log out</button>
      </form>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(title)} - CommerceLens</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #18212f; background: #f7f8fa; line-height: 1.45; }}
    header {{ background: #0f172a; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; gap: 18px; }}
    header a {{ color: #bfdbfe; text-decoration: none; }}
    header a:hover, header a:focus-visible {{ color: white; text-decoration: underline; }}
    header nav {{ display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }}
    .session-action {{ display: inline; margin: 0; padding: 0; border: 0; background: transparent; }}
    .session-action button {{ border: 0; background: transparent; color: #bfdbfe; padding: 0; cursor: pointer; font: inherit; }}
    .session-action button:hover, .session-action button:focus-visible {{ color: white; text-decoration: underline; }}
    .session-action input {{ display: none; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 26px; margin: 0 0 8px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    p {{ margin: 8px 0; }}
    .page-heading {{ display: flex; align-items: start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 6px; }}
    .panel {{ background: white; border: 1px solid #dfe4ea; border-radius: 10px; padding: 18px; margin-top: 16px; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dfe4ea; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e6eaf0; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #f1f5f9; color: #475569; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; overflow-wrap: anywhere; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .muted {{ color: #64748b; }}
    .danger {{ color: #b91c1c; }}
    .help {{ color: #64748b; font-size: 12px; font-weight: 400; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }}
    .form-grid.compact {{ grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto; align-items: end; }}
    .form-grid label, .inline-form label {{ display: grid; gap: 6px; color: #334155; font-size: 13px; font-weight: 600; }}
    .form-grid input, .form-grid select, .form-grid textarea, .inline-form input, .inline-form select {{
      width: 100%; font: inherit; padding: 10px 11px; border: 1px solid #cbd5e1; border-radius: 7px; background: white; color: #18212f;
    }}
    .form-grid textarea {{ resize: vertical; min-height: 92px; }}
    .form-grid fieldset {{ border: 1px solid #dfe4ea; border-radius: 8px; padding: 14px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .form-grid legend {{ padding: 0 6px; font-weight: 700; }}
    .span-2 {{ grid-column: 1 / -1; }}
    button, .button-link {{ font: inherit; padding: 9px 12px; border: 1px solid #0f172a; border-radius: 7px; background: white; color: #0f172a; cursor: pointer; text-decoration: none; display: inline-block; }}
    button:hover, button:focus-visible, .button-link:hover, .button-link:focus-visible {{ background: #f1f5f9; }}
    button.primary, .primary {{ background: #0f172a; color: white; }}
    button.primary:hover, button.primary:focus-visible {{ background: #1e293b; }}
    .danger-button {{ color: #b91c1c; border-color: #fecaca; }}
    .danger-button:hover, .danger-button:focus-visible {{ background: #fef2f2; }}
    .inline-form {{ display: flex; gap: 10px; align-items: end; flex-wrap: wrap; }}
    .inline-form label {{ min-width: min(420px, 100%); flex: 1; }}
    .table-actions, .action-row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    .action-form {{ display: inline; margin: 0; padding: 0; border: 0; background: transparent; }}
    .action-form input {{ display: none; }}
    .action-form button {{ padding: 5px 8px; font-size: 12px; }}
    .notice {{ border-radius: 8px; padding: 12px 14px; margin: 14px 0; border: 1px solid; }}
    .notice ul {{ margin: 8px 0 0; padding-left: 20px; }}
    .notice.error {{ color: #991b1b; border-color: #fecaca; background: #fef2f2; }}
    .notice.success {{ color: #166534; border-color: #bbf7d0; background: #f0fdf4; }}
    .notice.warning {{ color: #854d0e; border-color: #fde68a; background: #fffbeb; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      main {{ padding: 16px; }}
      header {{ align-items: flex-start; flex-direction: column; }}
      .page-heading {{ flex-direction: column; }}
    }}
    @media (max-width: 640px) {{
      .grid, .form-grid, .form-grid.compact, .form-grid fieldset {{ grid-template-columns: 1fr; }}
      .span-2 {{ grid-column: auto; }}
      th, td {{ font-size: 13px; }}
      main {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div><strong>CommerceLens</strong> <span class="muted">customer portal</span></div>
    <nav><a href="/portal">Overview</a><a href="/portal/manage">Manage monitors</a><a href="/docs">API Docs</a>{session_actions}</nav>
  </header>
  <main>{content}</main>
</body>
</html>"""


def portal_login(csrf_token: str, message: str = "") -> str:
    error = f'<p class="error" role="alert">{escape_html(message)}</p>' if message else ""
    escaped_token = escape_html(csrf_token)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in - CommerceLens</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px; box-sizing: border-box; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #18212f; background: #f7f8fa; }}
    main {{ width: min(100%, 440px); background: white; border: 1px solid #dfe4ea; border-radius: 10px; padding: 24px; box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08); }}
    h1 {{ margin: 0 0 10px; font-size: 26px; }}
    p {{ color: #64748b; line-height: 1.5; }}
    form {{ display: grid; gap: 14px; margin-top: 20px; }}
    label {{ display: grid; gap: 6px; font-weight: 600; }}
    input {{ font: inherit; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 6px; }}
    button {{ font: inherit; padding: 10px 14px; border: 0; border-radius: 6px; background: #0f172a; color: white; cursor: pointer; }}
    .error {{ color: #b91c1c; }}
  </style>
</head>
<body>
  <main>
    <h1>Sign in to CommerceLens</h1>
    <p>Enter the API key provided by your workspace administrator. The key is exchanged for an expiring browser session and is never placed in the URL.</p>
    {error}
    <form method="post" action="/portal/login">
      <input name="csrf_token" type="hidden" value="{escaped_token}">
      <label>API key<input name="api_key" type="password" required autocomplete="off"></label>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>"""


def table(headers: list[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f"<th>{escape_html(header)}</th>" for header in headers)
    if not rows:
        return (
            f"<table><thead><tr>{head}</tr></thead><tbody><tr>"
            f"<td colspan='{len(headers)}' class='muted'>No records</td>"
            "</tr></tbody></table>"
        )
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def preformatted_json(value: object) -> str:
    return f"<pre>{escape_html(json.dumps(value, indent=2, sort_keys=True, default=str))}</pre>"


def portal_href(path: str) -> str:
    return path
