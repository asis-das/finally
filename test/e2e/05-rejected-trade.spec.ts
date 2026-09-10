import { test, expect } from "../fixtures/app";

const SUBJECT = "NVDA";

/** Contract §9 scenario 5 — a rejected trade surfaces inline, and changes nothing. */
test.describe("scenario 5 — rejected trades", () => {
  test("buying beyond the cash balance shows trade-error and moves no money", async ({
    app,
    api,
  }) => {
    await app.open();
    const cashBefore = await app.readCash();
    const qtyBefore = await app.readPositionQuantity(SUBJECT);

    await app.placeOrder(SUBJECT, 1_000_000, "buy");

    await expect(app.tradeError, "no inline error after an unaffordable buy").toBeVisible();
    await expect(app.tradeError).toHaveText(/Insufficient cash: need \$[\d,.]+, have \$[\d,.]+/);

    // Nothing moved.
    await expect(app.cashBalance).toHaveText(
      `$${cashBefore.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    );
    expect(await app.readPositionQuantity(SUBJECT)).toBe(qtyBefore);

    const portfolio = await api.portfolio();
    expect(portfolio.cash_balance).toBeCloseTo(cashBefore, 2);
  });

  test("an unknown ticker is rejected for want of a price", async ({ app, api }) => {
    const bogus = "ZZZZ";
    await api.ensureTickerAbsent(bogus);
    await app.open();

    await app.placeOrder(bogus, 1, "buy");

    await expect(app.tradeError).toBeVisible();
    await expect(app.tradeError).toHaveText(new RegExp(`No price available for ${bogus}`));
  });

  test("a zero quantity never reaches the server", async ({ app }) => {
    await app.open();

    await app.placeOrder("AAPL", 0, "buy");

    await expect(app.tradeError).toBeVisible();
    await expect(app.tradeError).toHaveText(/quantity greater than zero/i);
  });

  test("the error clears once a valid order is placed", async ({ app, api }) => {
    await app.open();
    await app.placeOrder("AAPL", 1_000_000, "buy");
    await expect(app.tradeError).toBeVisible();

    await app.placeOrder("AAPL", 1, "buy");

    await expect(app.tradeError).toHaveCount(0);
    await api.closePosition("AAPL");
  });
});
