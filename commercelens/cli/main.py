from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from commercelens.core.crawler import crawl_catalog
from commercelens.core.monitor import monitor_product, monitor_products
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.storage.exporters import write_csv, write_jsonl
from commercelens.storage.price_store import PriceSnapshotStore

app = typer.Typer(help="CommerceLens: product and catalog extraction for developers.")
console = Console()

OutputFormat = Literal["json", "jsonl", "csv"]


def _write_or_print(payload: dict | list, out: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote result to {out}[/green]")
    else:
        console.print_json(text)


@app.command()
def product(
    url: str = typer.Argument(..., help="Product page URL to extract."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
    render: bool = typer.Option(False, "--render", help="Render the page with Playwright before extraction."),
    screenshot: Path | None = typer.Option(None, "--screenshot", help="Optional screenshot path when rendering."),
    html_snapshot: Path | None = typer.Option(None, "--html-snapshot", help="Optional rendered HTML snapshot path."),
) -> None:
    """Extract a normalized product object from a product page URL."""
    result = extract_product(
        url,
        render=render,
        screenshot_path=screenshot,
        html_snapshot_path=html_snapshot,
    )
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def html(
    path: Path = typer.Argument(..., help="Local HTML file to extract from."),
    url: str | None = typer.Option(None, "--url", help="Optional source URL for resolving relative links."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Extract a normalized product object from a local HTML file."""
    result = extract_product_from_html(path.read_text(encoding="utf-8"), url=url)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def listing(
    url: str = typer.Argument(..., help="Listing/category page URL to extract."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional output path."),
    fmt: OutputFormat = typer.Option("json", "--format", "-f", help="Output format: json, jsonl, csv."),
    render: bool = typer.Option(False, "--render", help="Render the page with Playwright before extraction."),
    screenshot: Path | None = typer.Option(None, "--screenshot", help="Optional screenshot path when rendering."),
    html_snapshot: Path | None = typer.Option(None, "--html-snapshot", help="Optional rendered HTML snapshot path."),
) -> None:
    """Extract product cards from a listing or category page."""
    result = extract_listing(
        url,
        render=render,
        screenshot_path=screenshot,
        html_snapshot_path=html_snapshot,
    )
    if out and fmt == "jsonl":
        write_jsonl(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    if out and fmt == "csv":
        write_csv(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def listing_html(
    path: Path = typer.Argument(..., help="Local listing HTML file to extract from."),
    url: str | None = typer.Option(None, "--url", help="Optional source URL for resolving links."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional output path."),
    fmt: OutputFormat = typer.Option("json", "--format", "-f", help="Output format: json, jsonl, csv."),
) -> None:
    """Extract product cards from a local listing/category HTML file."""
    result = extract_listing_from_html(path.read_text(encoding="utf-8"), url=url)
    if out and fmt == "jsonl":
        write_jsonl(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    if out and fmt == "csv":
        write_csv(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def crawl(
    url: str = typer.Argument(..., help="Catalog/listing URL to start crawling from."),
    max_pages: int = typer.Option(5, "--max-pages", min=1, max=100, help="Maximum listing pages."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional output path."),
    fmt: OutputFormat = typer.Option("json", "--format", "-f", help="Output format: json, jsonl, csv."),
    render: bool = typer.Option(False, "--render", help="Render each page with Playwright before extraction."),
    debug_dir: Path | None = typer.Option(None, "--debug-dir", help="Save rendered screenshots/HTML snapshots per page."),
) -> None:
    """Crawl listing pages by following next-page links and collect product cards."""
    result = crawl_catalog(url, max_pages=max_pages, render=render, debug_dir=debug_dir)
    if out and fmt == "jsonl":
        write_jsonl(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    if out and fmt == "csv":
        write_csv(result.products, out)
        console.print(f"[green]Wrote {len(result.products)} products to {out}[/green]")
        return
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def monitor(
    url: str = typer.Argument(..., help="Product URL to snapshot and compare."),
    db: Path = typer.Option(Path("commercelens.db"), "--db", help="SQLite database path."),
    render: bool = typer.Option(False, "--render", help="Render the page before extraction."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Extract a product, save a price snapshot, and report changes."""
    result = monitor_product(url, db_path=db, render=render)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def monitor_batch(
    urls_file: Path = typer.Argument(..., help="Text file with one product URL per line."),
    db: Path = typer.Option(Path("commercelens.db"), "--db", help="SQLite database path."),
    render: bool = typer.Option(False, "--render", help="Render each page before extraction."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Monitor many product URLs from a text file."""
    urls = [line.strip() for line in urls_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = monitor_products(urls, db_path=db, render=render)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def history(
    product_key: str = typer.Argument(..., help="Product key to inspect."),
    db: Path = typer.Option(Path("commercelens.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(20, "--limit", min=1, max=1000, help="Maximum snapshots to return."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Show price history for a product key."""
    store = PriceSnapshotStore(db)
    snapshots = [snapshot.__dict__ for snapshot in store.history(product_key, limit=limit)]
    _write_or_print(snapshots, out=out)


@app.command()
def changes(
    db: Path = typer.Option(Path("commercelens.db"), "--db", help="SQLite database path."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Show detected latest price and availability changes."""
    store = PriceSnapshotStore(db)
    detected = [change.__dict__ for change in store.detect_changes()]
    _write_or_print(detected, out=out)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    reload: bool = typer.Option(False, help="Enable development reload."),
) -> None:
    """Run the CommerceLens FastAPI server."""
    import uvicorn

    uvicorn.run("commercelens.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
