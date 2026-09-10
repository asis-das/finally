import { test, expect, PRICE } from "../fixtures/app";

/**
 * Behaviour the contract requires but that does not sit inside any single §9
 * scenario: the flash animation (§7.3 / PLAN.md §10) and the pricing rule that
 * spans the API, the market source and the positions table (§5.2).
 */
test.describe("cross-layer behaviour", () => {
  test("prices flash green or red as they move", async ({ app }) => {
    await app.open();
    await expect(app.watchlistPrice("AAPL")).toHaveText(PRICE);

    // The class lives on the inner span, is applied for ~520ms and removed
    // again, so this polls for the window rather than asserting a steady state.
    const flashed = app.page.locator(
      '[data-testid="watchlist-price-AAPL"] span, [data-testid="watchlist-price-GOOGL"] span, [data-testid="watchlist-price-NVDA"] span',
    );

    await expect
      .poll(
        async () => {
          const classes = await flashed.evaluateAll((nodes) =>
            nodes.map((node) => node.className),
          );
          return classes.some((name) => /flash-(up|down)/.test(name));
        },
        {
          message:
            "no price cell ever carried flash-up/flash-down — the tick animation is not firing",
          timeout: 25_000,
          intervals: [100, 100, 200],
        },
      )
      .toBe(true);
  });

  test("a held position keeps its live price after leaving the watchlist", async ({
    app,
    api,
  }) => {
    // Contract §5.2: DELETE only untracks the ticker when no open position holds it.
    const subject = "NFLX";
    await api.ensureTickerPresent(subject);
    await api.closePosition(subject);
    await api.trade(subject, 1, "buy");

    await app.open();
    await expect(app.positionRow(subject)).toBeVisible();

    await app.page.getByTestId(`watchlist-remove-${subject}`).click();
    await expect(app.watchlistRow(subject)).toHaveCount(0);

    // The row survives, and the price behind it is still moving.
    await expect(
      app.positionRow(subject),
      `${subject} position vanished when the ticker left the watchlist`,
    ).toBeVisible();

    const priceCell = app.positionRow(subject).locator("td").nth(3);
    await expect(priceCell).toHaveText(PRICE);
    const before = await priceCell.textContent();

    await expect
      .poll(async () => priceCell.textContent(), {
        message: `${subject} stopped repricing after being removed from the watchlist`,
        timeout: 30_000,
        intervals: [250, 500],
      })
      .not.toBe(before);

    // And it can still be traded out of.
    await app.placeOrder(subject, 1, "sell");
    await expect(app.positionRow(subject)).toHaveCount(0);
    await api.ensureTickerPresent(subject);
  });

  test("the header total tracks the tape, not just the last portfolio poll", async ({ app, api }) => {
    await api.ensurePosition("TSLA", 5);
    await app.open();

    const before = await app.readTotalValue();
    await expect
      .poll(async () => app.readTotalValue(), {
        message: "header total value never moved while holding a live position",
        timeout: 30_000,
        intervals: [250, 500],
      })
      .not.toBe(before);

    await api.closePosition("TSLA");
  });

  test("a manual trade and a chat trade land in the same book", async ({ app, api }) => {
    await api.closePosition("AMZN");
    await app.open();

    await app.placeOrder("AMZN", 2, "buy");
    await expect(app.positionQty("AMZN")).toHaveText("2");

    await app.sendChat("buy 3 AMZN");
    await expect(app.positionQty("AMZN")).toHaveText("5");

    expect(await api.positionQuantity("AMZN")).toBe(5);

    // Selling the lot through the trade bar closes the row the chat opened.
    await app.placeOrder("AMZN", 5, "sell");
    await expect(app.positionRow("AMZN")).toHaveCount(0);
    expect(await api.positionQuantity("AMZN")).toBe(0);
  });
});
