from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from commercelens.core.renderer import render_html
from commercelens.extractors.product import extract_product_from_html


pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCELENS_RUN_BROWSER_TESTS") != "1",
    reason="Set COMMERCELENS_RUN_BROWSER_TESTS=1 to run the Chromium integration test.",
)


class QuietFixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def test_chromium_renders_and_extracts_a_local_fixture(monkeypatch) -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "benchmarks"
    handler = partial(QuietFixtureHandler, directory=str(fixture_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("COMMERCELENS_ALLOWED_PRIVATE_HOSTS", "127.0.0.1")

    try:
        url = f"http://127.0.0.1:{server.server_port}/product_jsonld.html"
        rendered = render_html(url, timeout_ms=15_000)
        result = extract_product_from_html(rendered.html, url=rendered.final_url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.product.name == "Benchmark Widget"
    assert result.product.price is not None
    assert result.product.price.amount == 49.99
