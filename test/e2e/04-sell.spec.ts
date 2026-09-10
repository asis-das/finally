import { test, expect } from "../fixtures/app";

const SUBJECT = "MSFT";

/** Contract §9 scenario 4 — sell. */
test.describe("scenario 4 — sell", () => {
  test("a partial sell shrinks the position and returns cash", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await api.trade(SUBJECT, 5, "buy");

    await app.open();
    await expect(app.positionQty(SUBJECT)).toHaveText("5");
    const cashBefore = await app.readCash();

    await app.placeOrder(SUBJECT, 2, "sell");

    await expect(app.positionQty(SUBJECT)).toHaveText("3");
    await expect
      .poll(async () => app.readCash(), {
        message: "cash did not rise after a sell",
        timeout: 20_000,
      })
      .toBeGreaterThan(cashBefore);

    const proceeds = (await app.readCash()) - cashBefore;
    const price = proceeds / 2;
    expect(price, `implied sale price $${price.toFixed(2)} is implausible`).toBeGreaterThan(1);

    expect(await api.positionQuantity(SUBJECT)).toBe(3);
  });

  test("selling the whole holding removes the position row", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await api.trade(SUBJECT, 4, "buy");

    await app.open();
    const held = await app.readPositionQuantity(SUBJECT);
    expect(held).toBe(4);

    await app.placeOrder(SUBJECT, held, "sell");

    await expect(
      app.positionRow(SUBJECT),
      `${SUBJECT} row survived a full liquidation`,
    ).toHaveCount(0);
    await expect(app.heatmapTile(SUBJECT)).toHaveCount(0);
    expect(await api.positionQuantity(SUBJECT)).toBe(0);
  });

  test("selling more than is held is rejected", async ({ app, api }) => {
    await api.closePosition(SUBJECT);
    await api.trade(SUBJECT, 2, "buy");

    await app.open();
    await expect(app.positionQty(SUBJECT)).toHaveText("2");

    await app.placeOrder(SUBJECT, 50, "sell");

    await expect(app.tradeError).toBeVisible();
    await expect(app.tradeError).toHaveText(/Insufficient shares/);
    await expect(app.positionQty(SUBJECT)).toHaveText("2");
  });
});
