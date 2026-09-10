import { test, expect, PRICE } from "../fixtures/app";

const SUBJECT = "PYPL";

/** Contract §9 scenario 2 — watchlist add + remove round trip. */
test.describe("scenario 2 — watchlist", () => {
  test.beforeEach(async ({ api }) => {
    // Re-runnable against a persistent database: start from a known absence.
    await api.closePosition(SUBJECT);
    await api.ensureTickerAbsent(SUBJECT);
  });

  test.afterEach(async ({ api }) => {
    await api.closePosition(SUBJECT);
    await api.ensureTickerAbsent(SUBJECT);
  });

  test("adds a ticker and starts pricing it", async ({ app, api }) => {
    await app.open();
    await expect(app.watchlistRow(SUBJECT)).toHaveCount(0);

    await app.addWatchlistTicker(SUBJECT.toLowerCase());

    await expect(app.watchlistRow(SUBJECT)).toBeVisible();
    await expect(
      app.watchlistPrice(SUBJECT),
      `${SUBJECT} was added but never priced — market_source.add_ticker did not take effect`,
    ).toHaveText(PRICE, { timeout: 20_000 });

    expect(await api.hasTicker(SUBJECT)).toBe(true);
  });

  test("removes a ticker", async ({ app, api }) => {
    await api.ensureTickerPresent(SUBJECT);
    await app.open();
    await expect(app.watchlistRow(SUBJECT)).toBeVisible();

    // The remove button only becomes opaque on hover; Playwright's click
    // auto-scrolls and dispatches regardless of opacity, which is what we want.
    await app.page.getByTestId(`watchlist-remove-${SUBJECT}`).click();

    await expect(app.watchlistRow(SUBJECT)).toHaveCount(0);
    expect(await api.hasTicker(SUBJECT)).toBe(false);
  });

  test("rejects a duplicate ticker with the API's message", async ({ app, api }) => {
    await api.ensureTickerPresent(SUBJECT);
    await app.open();
    await expect(app.watchlistRow(SUBJECT)).toBeVisible();

    await app.addWatchlistTicker(SUBJECT);

    await expect(
      app.page.getByText(`Ticker ${SUBJECT} is already on the watchlist`),
    ).toBeVisible();
  });

  test("the ten defaults survive an add/remove cycle", async ({ app, api }) => {
    const before = (await api.watchlist()).tickers.map((entry) => entry.ticker);

    await app.open();
    await app.addWatchlistTicker(SUBJECT);
    await expect(app.watchlistRow(SUBJECT)).toBeVisible();
    await app.page.getByTestId(`watchlist-remove-${SUBJECT}`).click();
    await expect(app.watchlistRow(SUBJECT)).toHaveCount(0);

    const after = (await api.watchlist()).tickers.map((entry) => entry.ticker);
    expect(after).toEqual(before);
  });
});
