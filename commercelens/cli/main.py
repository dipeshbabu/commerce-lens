from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from commercelens.core.crawler import crawl_catalog
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.storage.exporters import write_csv, write_jsonl

app = typer.Typer(help="CommerceLens: product and catalog extraction for developers.")
console = Console()

OutputFormat = Literal["json", "jsonl", "csv"]


def _write_or_print(payload: dict, out: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote extraction result to {out}[/green]")
    else:
        console.print_json(text)


@app.command()
def product(
    url: str = typer.Argument(..., help="Product page URL to extract."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional JSON output path."),
) -> None:
    """Extract a normalized product object from a product page URL."""
    result = extract_product(url)
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
) -> None:
    """Extract product cards from a listing or category page."""
    result = extract_listing(url)
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
) -> None:
    """Crawl listing pages by following next-page links and collect product cards."""
    result = crawl_catalog(url, max_pages=max_pages)
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
