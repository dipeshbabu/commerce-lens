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


def portal_shell(title: str, content: str, token_query: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(title)} - CommerceLens</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #18212f; background: #f7f8fa; }}
    header {{ background: #0f172a; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
    header a {{ color: #bfdbfe; text-decoration: none; margin-left: 16px; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; }}
    h2 {{ font-size: 17px; margin: 26px 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 6px; }}
    .panel {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 16px; margin-top: 16px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dfe4ea; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e6eaf0; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #f1f5f9; color: #475569; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: #64748b; }}
    .danger {{ color: #b91c1c; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 16px; }} }}
    @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} th, td {{ font-size: 13px; }} }}
  </style>
</head>
<body>
  <header>
    <div><strong>CommerceLens</strong> <span class="muted">customer portal</span></div>
    <nav><a href="/portal{token_query}">Overview</a><a href="/docs">API Docs</a></nav>
  </header>
  <main>{content}</main>
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


def portal_href(path: str, token_query: str) -> str:
    return f"{path}{token_query}"
