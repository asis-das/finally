import { test, expect, MONEY } from "../fixtures/app";

const SUBJECT = "AAPL";

/** Contract §9 scenario 3 — buy. */
test.describe("scenario 3 — buy", () => {
  test("cash falls, the position appears, total value is conserved", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await app.open();

    const cashBefore = await app.readCash();
    const totalBefore = await app.readTotalValue();
    await expect(app.positionRow(SUBJECT)).toHaveCount(0);

    await app.placeOrder(SUBJECT, 3, "buy");

    // The row is the primary evidence the trade landed.
    await expect(
      app.positionRow(SUBJECT),
      `no position row for ${SUBJECT} after buying 3`,
    ).toBeVisible();
    await expect(app.positionQty(SUBJECT)).toHaveText("3");
    await expect(app.positionPnl(SUBJECT)).toHaveText(MONEY);

    // Stochastic price, so assert direction and a plausible magnitude, never a value.
    await expect
      .poll(async () => app.readCash(), {
        message: "cash did not fall after a buy",
        timeout: 20_000,
      })
      .toBeLessThan(cashBefore);

    const cashAfter = await app.readCash();
    const spend = cashBefore - cashAfter;
    const price = spend / 3;
    expect(
      price,
      `implied fill price $${price.toFixed(2)} is not a plausible ${SUBJECT} price`,
    ).toBeGreaterThan(1);
    expect(price).toBeLessThan(10_000);

    // Buying converts cash into stock; it does not create or destroy value.
    const totalAfter = await app.readTotalValue();
    expect(
      Math.abs(totalAfter - totalBefore) / totalBefore,
      `total value moved from ${totalBefore} to ${totalAfter} across a single buy`,
    ).toBeLessThan(0.03);

    // And the server agrees with the screen.
    const portfolio = await api.portfolio();
    expect(portfolio.cash_balance).toBeCloseTo(cashAfter, 2);
    const position = portfolio.positions.find((p: { ticker: string }) => p.ticker === SUBJECT);
    expect(position, `${SUBJECT} missing from GET /api/portfolio`).toBeTruthy();
    expect(position.quantity).toBe(3);
  });

  test("a second buy averages the cost and adds to the existing row", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await api.trade(SUBJECT, 2, "buy");
    await app.open();
    await expect(app.positionQty(SUBJECT)).toHaveText("2");

    await app.placeOrder(SUBJECT, 4, "buy");

    await expect(app.positionQty(SUBJECT)).toHaveText("6");
    expect(await app.page.getByTestId(`position-row-${SUBJECT}`).count()).toBe(1);

    const portfolio = await api.portfolio();
    const position = portfolio.positions.find((p: { ticker: string }) => p.ticker === SUBJECT);
    expect(position.quantity).toBe(6);
    expect(position.avg_cost).toBeGreaterThan(0);
  });

  test("buying a ticker does not add it to the watchlist", async ({ app, api }) => {
    // Contract §5.2: "Buying a ticker not on the watchlist ... must not add it."
    const before = (await api.watchlist()).tickers.map((entry) => entry.ticker);
    await app.open();

    await app.placeOrder(SUBJECT, 1, "buy");
    await expect(app.positionRow(SUBJECT)).toBeVisible();

    const after = (await api.watchlist()).tickers.map((entry) => entry.ticker);
    expect(after).toEqual(before);
  });

  test("fractional share quantities are supported", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await app.open();

    await app.placeOrder(SUBJECT, "2.5", "buy");

    await expect(app.positionQty(SUBJECT)).toHaveText("2.5");
    expect(await api.positionQuantity(SUBJECT)).toBeCloseTo(2.5, 6);
  });
});
