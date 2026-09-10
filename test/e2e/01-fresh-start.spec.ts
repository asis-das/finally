import { test, expect, DEFAULT_TICKERS, FRESH_DB, MONEY, PRICE } from "../fixtures/app";

/**
 * Contract §9 scenario 1 — fresh start.
 *
 * The $10,000.00 seed is only a fact on an empty volume, so that assertion is
 * gated on FRESH_DB. Everywhere else the suite asserts shape, because the same
 * database is reused across runs by design.
 */
test.describe("scenario 1 — fresh start", () => {
  test("the ten default tickers are on the watchlist", async ({ app, api }) => {
    await app.open();

    const { tickers } = await api.watchlist();
    const symbols = tickers.map((entry) => entry.ticker);

    // Present, in seed order. Extra tickers are allowed on a reused database
    // (an earlier run may have added one) but the ten defaults must be there.
    for (const ticker of DEFAULT_TICKERS) {
      await expect(
        app.watchlistRow(ticker),
        `default ticker ${ticker} missing from the watchlist panel`,
      ).toBeVisible();
    }
    expect(symbols.slice(0, DEFAULT_TICKERS.length)).toEqual(DEFAULT_TICKERS);

    if (FRESH_DB) {
      expect(symbols, "a fresh database must hold exactly the ten seed tickers").toEqual(
        DEFAULT_TICKERS,
      );
    }
  });

  test("cash and total value render as money", async ({ app }) => {
    await app.open();

    await expect(app.cashBalance).toHaveText(MONEY);
    await expect(app.totalValue).toHaveText(MONEY);

    if (FRESH_DB) {
      await expect(app.cashBalance).toHaveText("$10,000.00");
      await expect(app.totalValue).toHaveText("$10,000.00");
    }
  });

  test("prices stream in and tick", async ({ app }) => {
    await app.open();

    await expect(app.connectionStatus).toHaveAttribute("data-status", "connected");

    // Every default ticker must be priced, not "—".
    for (const ticker of DEFAULT_TICKERS) {
      await expect(
        app.watchlistPrice(ticker),
        `${ticker} never received a price from the SSE stream`,
      ).toHaveText(PRICE);
    }

    // GBM at 2dp: an individual ticker can sit still for a few seconds, so the
    // assertion is that the tape as a whole moves, not that AAPL specifically does.
    const snapshot = async () =>
      Promise.all(
        DEFAULT_TICKERS.map((ticker) => app.watchlistPrice(ticker).textContent()),
      );

    const before = await snapshot();
    await expect
      .poll(async () => (await snapshot()).some((price, i) => price !== before[i]), {
        message: "no watchlist price changed — the price stream is not ticking",
        timeout: 20_000,
        intervals: [250, 250, 500],
      })
      .toBe(true);
  });

  test("the workstation panels all render", async ({ app }) => {
    await app.open();

    for (const testId of [
      "watchlist",
      "detail-chart",
      "portfolio-heatmap",
      "pnl-chart",
      "positions-table",
      "chat-panel",
      "trade-ticker",
      "trade-quantity",
      "trade-buy",
      "trade-sell",
    ]) {
      await expect(app.page.getByTestId(testId), `${testId} is not visible`).toBeVisible();
    }
  });
});
