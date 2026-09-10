"""Tests for app wiring: lifespan, static hosting, CORS and the chat guard."""

from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from app.db import database, list_snapshots
from app.main import _record_snapshot, _snapshot_loop, create_app
from app.market import PriceCache


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """A database path that does not exist yet, so lazy init is exercised."""
    path = tmp_path / "nested" / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    monkeypatch.setattr(database, "_db_path", None, raising=False)
    return path


def test_lifespan_initialises_db_and_market_data(fresh_db, monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    app = create_app()

    with TestClient(app) as client:
        assert fresh_db.exists()
        health = client.get("/api/health").json()
        assert health == {"status": "ok", "market_source": "simulator", "tickers": 10, "db": "ok"}

        assert app.state.market_source is not None
        assert app.state.snapshot_task is not None

        rows = client.get("/api/watchlist").json()["tickers"]
        assert len(rows) == 10
        # The simulator seeds the cache on start, so every ticker is priced.
        assert all(row["price"] is not None for row in rows)

    assert app.state.market_source is None
    assert app.state.snapshot_task is None


def test_record_snapshot_writes_current_total(temp_db):
    _record_snapshot(PriceCache())
    snapshots = list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["total_value"] == 10000.0


async def test_snapshot_loop_records_then_repeats(temp_db):
    task = asyncio.create_task(_snapshot_loop(PriceCache(), interval=0.01))
    try:
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(list_snapshots()) >= 2:
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(list_snapshots()) >= 2


def test_static_export_is_served_when_present(temp_db, tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>FinAlly</html>")
    (static_dir / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(static_dir))

    client = TestClient(create_app())
    assert client.get("/").text == "<html>FinAlly</html>"
    assert client.get("/app.js").status_code == 200
    # Unknown non-API paths fall back to the SPA entry point.
    assert client.get("/anything/deep").text == "<html>FinAlly</html>"
    # Unknown API paths must still 404 rather than returning HTML.
    assert client.get("/api/nope").status_code == 404


def test_api_routes_win_over_the_static_mount(
    temp_db, tmp_path, monkeypatch, price_cache, market_source
):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>FinAlly</html>")
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(static_dir))

    app = create_app()
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    client = TestClient(app)

    assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0
    assert client.get("/api/health").json()["status"] == "ok"


def test_missing_static_dir_is_not_fatal(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "does-not-exist"))
    client = TestClient(create_app())
    assert client.get("/").status_code == 404


def test_dev_cors_allows_the_local_frontend(temp_db, monkeypatch):
    monkeypatch.setenv("DEV_CORS", "true")
    monkeypatch.setenv("FINALLY_STATIC_DIR", "does-not-exist")
    app = create_app()
    app.state.market_source = None
    client = TestClient(app)

    response = client.options(
        "/api/portfolio",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_is_off_by_default(client):
    response = client.get("/api/portfolio", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in response.headers


def test_app_starts_when_chat_router_is_unavailable(temp_db, monkeypatch):
    # None in sys.modules makes `import app.api.chat` raise ImportError.
    monkeypatch.setitem(sys.modules, "app.api.chat", None)
    app = create_app()
    assert not any(getattr(route, "path", "").startswith("/api/chat") for route in app.routes)
    assert any(getattr(route, "path", "") == "/api/health" for route in app.routes)
