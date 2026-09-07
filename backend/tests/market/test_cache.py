"""Tests for PriceCache."""

from app.market.cache import PriceCache


class TestPriceCache:
    """Unit tests for the PriceCache."""

    def test_update_and_get(self):
        """Test updating and getting a price."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.ticker == "AAPL"
        assert update.price == 190.50
        assert cache.get("AAPL") == update

    def test_first_update_is_flat(self):
        """Test that the first update has flat direction."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.direction == "flat"
        assert update.previous_price == 190.50

    def test_direction_up(self):
        """Test price update with upward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 191.00)
        assert update.direction == "up"
        assert update.change == 1.00

    def test_direction_down(self):
        """Test price update with downward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 189.00)
        assert update.direction == "down"
        assert update.change == -1.00

    def test_remove(self):
        """Test removing a ticker from cache."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get("AAPL") is None

    def test_remove_nonexistent(self):
        """Test removing a ticker that doesn't exist."""
        cache = PriceCache()
        cache.remove("AAPL")  # Should not raise

    def test_get_all(self):
        """Test getting all prices."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        all_prices = cache.get_all()
        assert set(all_prices.keys()) == {"AAPL", "GOOGL"}

    def test_version_increments(self):
        """Test that version counter increments."""
        cache = PriceCache()
        v0 = cache.version
        cache.update("AAPL", 190.00)
        assert cache.version == v0 + 1
        cache.update("AAPL", 191.00)
        assert cache.version == v0 + 2

    def test_get_price_convenience(self):
        """Test the convenience get_price method."""
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("NOPE") is None

    def test_len(self):
        """Test __len__ method."""
        cache = PriceCache()
        assert len(cache) == 0
        cache.update("AAPL", 190.00)
        assert len(cache) == 1
        cache.update("GOOGL", 175.00)
        assert len(cache) == 2

    def test_contains(self):
        """Test __contains__ method."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert "AAPL" in cache
        assert "GOOGL" not in cache

    def test_custom_timestamp(self):
        """Test updating with a custom timestamp."""
        cache = PriceCache()
        custom_ts = 1234567890.0
        update = cache.update("AAPL", 190.50, timestamp=custom_ts)
        assert update.timestamp == custom_ts

    def test_price_rounding(self):
        """Test that prices are rounded to 2 decimal places."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.12345)
        assert update.price == 190.12


class TestPriceCacheThreadSafety:
    """The cache is written from worker threads (Massive runs its REST client
    via asyncio.to_thread), so concurrent writes must not lose updates."""

    def test_concurrent_writes_do_not_lose_updates(self):
        from threading import Thread

        cache = PriceCache()
        writes_per_thread = 500
        tickers = ["AAPL", "GOOGL", "MSFT", "AMZN"]

        def writer(ticker: str) -> None:
            for i in range(writes_per_thread):
                cache.update(ticker, 100.0 + i * 0.01)

        threads = [Thread(target=writer, args=(t,)) for t in tickers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.version == writes_per_thread * len(tickers)
        assert len(cache) == len(tickers)
        for ticker in tickers:
            assert cache.get_price(ticker) == round(100.0 + (writes_per_thread - 1) * 0.01, 2)

    def test_concurrent_reads_during_writes_are_consistent(self):
        from threading import Event, Thread

        cache = PriceCache()
        cache.update("AAPL", 190.0)
        stop = Event()
        errors: list[Exception] = []

        def writer() -> None:
            while not stop.is_set():
                cache.update("AAPL", 190.0)

        def reader() -> None:
            try:
                for _ in range(2000):
                    snapshot = cache.get_all()
                    # A snapshot must never expose a half-written entry
                    assert snapshot["AAPL"].ticker == "AAPL"
                    assert snapshot["AAPL"].price > 0
            except Exception as exc:  # pragma: no cover - only on failure
                errors.append(exc)

        w = Thread(target=writer)
        r = Thread(target=reader)
        w.start()
        r.start()
        r.join()
        stop.set()
        w.join()

        assert not errors
