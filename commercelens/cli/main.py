from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from commercelens.alerts.config import save_example_config
from commercelens.alerts.runner import run_monitor_config_file
from commercelens.connectors.datasets import load_product_records, records_from_snapshots, write_product_records
from commercelens.core.crawler import crawl_catalog
from commercelens.core.monitor import monitor_product, monitor_products
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.matching.products import match_products
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
def product(url: str = typer.Argument(...), out: Path | None = typer.Option(None, "--out", "-o"), render: bool = typer.Option(False, "--render"), screenshot: Path | None = typer.Option(None, "--screenshot"), html_snapshot: Path | None = typer.Option(None, "--html-snapshot")) -> None:
    """Extract a normalized product object from a product page URL."""
    result = extract_product(url, render=render, screenshot_path=screenshot, html_snapshot_path=html_snapshot)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def html(path: Path = typer.Argument(...), url: str | None = typer.Option(None, "--url"), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Extract a normalized product object from a local HTML file."""
    result = extract_product_from_html(path.read_text(encoding="utf-8"), url=url)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def listing(url: str = typer.Argument(...), out: Path | None = typer.Option(None, "--out", "-o"), fmt: OutputFormat = typer.Option("json", "--format", "-f"), render: bool = typer.Option(False, "--render"), screenshot: Path | None = typer.Option(None, "--screenshot"), html_snapshot: Path | None = typer.Option(None, "--html-snapshot")) -> None:
    """Extract product cards from a listing or category page."""
    result = extract_listing(url, render=render, screenshot_path=screenshot, html_snapshot_path=html_snapshot)
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
def listing_html(path: Path = typer.Argument(...), url: str | None = typer.Option(None, "--url"), out: Path | None = typer.Option(None, "--out", "-o"), fmt: OutputFormat = typer.Option("json", "--format", "-f")) -> None:
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
def crawl(url: str = typer.Argument(...), max_pages: int = typer.Option(5, "--max-pages", min=1, max=100), out: Path | None = typer.Option(None, "--out", "-o"), fmt: OutputFormat = typer.Option("json", "--format", "-f"), render: bool = typer.Option(False, "--render"), debug_dir: Path | None = typer.Option(None, "--debug-dir")) -> None:
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
def monitor(url: str = typer.Argument(...), db: Path = typer.Option(Path("commercelens.db"), "--db"), render: bool = typer.Option(False, "--render"), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Extract a product, save a price snapshot, and report changes."""
    result = monitor_product(url, db_path=db, render=render)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def monitor_batch(urls_file: Path = typer.Argument(...), db: Path = typer.Option(Path("commercelens.db"), "--db"), render: bool = typer.Option(False, "--render"), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Monitor many product URLs from a text file."""
    urls = [line.strip() for line in urls_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = monitor_products(urls, db_path=db, render=render)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command()
def run(config: Path = typer.Argument(..., help="Monitor config JSON/YAML file."), dry_run: bool = typer.Option(False, "--dry-run", help="Evaluate and build alert payloads without delivering."), no_deliver: bool = typer.Option(False, "--no-deliver", help="Run monitoring without alert delivery."), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Run a monitor config once and optionally deliver alerts."""
    result = run_monitor_config_file(str(config), dry_run=dry_run, deliver=not no_deliver)
    _write_or_print(result.model_dump(mode="json", exclude_none=True), out=out)


@app.command("init-config")
def init_config(path: Path = typer.Argument(Path("commercelens.monitor.json"))) -> None:
    """Create an example monitoring and alert config."""
    save_example_config(path)
    console.print(f"[green]Wrote example config to {path}[/green]")


@app.command()
def history(product_key: str = typer.Argument(...), db: Path = typer.Option(Path("commercelens.db"), "--db"), limit: int = typer.Option(20, "--limit", min=1, max=1000), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Show price history for a product key."""
    store = PriceSnapshotStore(db)
    snapshots = [snapshot.__dict__ for snapshot in store.history(product_key, limit=limit)]
    _write_or_print(snapshots, out=out)


@app.command()
def changes(db: Path = typer.Option(Path("commercelens.db"), "--db"), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Show detected latest price and availability changes."""
    store = PriceSnapshotStore(db)
    detected = [change.__dict__ for change in store.detect_changes()]
    _write_or_print(detected, out=out)


@app.command("export-history")
def export_history(db: Path = typer.Option(Path("commercelens.db"), "--db"), out: Path = typer.Option(..., "--out", "-o"), limit: int = typer.Option(1000, "--limit", min=1, max=100000)) -> None:
    """Export latest tracked product snapshots as CSV, JSON, or JSONL."""
    store = PriceSnapshotStore(db)
    records = records_from_snapshots(store.list_latest(limit=limit))
    result = write_product_records(records, out)
    _write_or_print(result.model_dump(mode="json"))


@app.command("load-records")
def load_records(path: Path = typer.Argument(...), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Load a product dataset from txt/csv/json/jsonl and normalize it."""
    result = load_product_records(path)
    payload = result.model_dump(mode="json", exclude_none=True)
    _write_or_print(payload, out=out)


@app.command("match-records")
def match_records(left: Path = typer.Argument(...), right: Path = typer.Argument(...), threshold: float = typer.Option(0.72, "--threshold"), top_k: int = typer.Option(1, "--top-k", min=1, max=10), out: Path | None = typer.Option(None, "--out", "-o")) -> None:
    """Match products across two CSV/JSON/JSONL datasets."""
    left_result = load_product_records(left)
    right_result = load_product_records(right)
    result = match_products(left_result.records, right_result.records, threshold=threshold, top_k=top_k)
    payload = {
        "matches": [match.model_dump(mode="json", exclude_none=True) for match in result.matches],
        "warnings": left_result.warnings + right_result.warnings,
    }
    _write_or_print(payload, out=out)


@app.command()
def serve(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000), reload: bool = typer.Option(False)) -> None:
    """Run the CommerceLens FastAPI server."""
    import uvicorn

    uvicorn.run("commercelens.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
