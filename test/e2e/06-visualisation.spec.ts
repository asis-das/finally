import { test, expect } from "../fixtures/app";

/** Contract §9 scenario 6 — heatmap tiles and the P&L chart render with data. */
test.describe("scenario 6 — portfolio visualisation", () => {
  test("the heatmap draws one sized, P&L-coloured tile per position", async ({ app, api }) => {
    await api.closePosition("AAPL");
    await api.closePosition("TSLA");
    await api.trade("AAPL", 5, "buy");
    await api.trade("TSLA", 2, "buy");

    await app.open();

    for (const ticker of ["AAPL", "TSLA"]) {
      const tile = app.heatmapTile(ticker);
      await expect(tile, `no heatmap tile for ${ticker}`).toBeVisible();

      const box = await tile.boundingBox();
      expect(box, `${ticker} tile has no layout box`).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);
    }

    // Sizing follows weight: AAPL (5 shares ~$190) outweighs TSLA (2 ~$250).
    const aapl = (await app.heatmapTile("AAPL").boundingBox())!;
    const tsla = (await app.heatmapTile("TSLA").boundingBox())!;
    expect(
      aapl.width * aapl.height,
      "the larger position did not get the larger tile",
    ).toBeGreaterThan(tsla.width * tsla.height);

    // Colour tracks the sign of P&L. The tile mixes --color-up or --color-down
    // into the panel background, so the declaration itself is the assertion.
    const portfolio = await api.portfolio();
    for (const ticker of ["AAPL", "TSLA"]) {
      const position = portfolio.positions.find((p: { ticker: string }) => p.ticker === ticker);
      const style = (await app.heatmapTile(ticker).getAttribute("style")) ?? "";
      const expected = position.unrealized_pnl_percent >= 0 ? "--color-up" : "--color-down";
      expect(
        style,
        `${ticker} P&L is ${position.unrealized_pnl_percent}% but the tile is not ${expected}`,
      ).toContain(expected);
    }
  });

  test("the P&L chart plots the snapshot series", async ({ app, api }) => {
    await api.trade("AAPL", 1, "buy"); // a trade snapshots immediately (contract §5.2)
    const history = await api.history();
    expect(history.snapshots.length, "GET /api/portfolio/history returned nothing").toBeGreaterThan(
      0,
    );

    await app.open();

    const chart = app.page.getByTestId("pnl-chart");
    await expect(chart).toBeVisible();
    await expect(
      chart.locator("svg"),
      "the P&L chart rendered its empty state instead of a series",
    ).toBeVisible();
    await expect(chart.locator("path.recharts-curve").first()).toBeVisible();

    // A real path, not a degenerate one-point stub.
    const d = await chart.locator("path.recharts-curve").first().getAttribute("d");
    expect(d, "P&L area path has no geometry").toBeTruthy();
    expect(d!.length, `P&L path is suspiciously short: ${d}`).toBeGreaterThan(20);
  });

  test("the detail chart draws the selected ticker's session history", async ({ app }) => {
    await app.open();
    await app.watchlistRow("NVDA").click();

    const chart = app.page.getByTestId("detail-chart");
    await expect(chart).toBeVisible();
    await expect(chart).toContainText("NVDA");
    // Sparkline history accumulates from the stream, so the line needs a few ticks.
    await expect(chart.locator("svg")).toBeVisible({ timeout: 25_000 });
  });

  test("sparklines accumulate in the watchlist", async ({ app }) => {
    await app.open();

    // The component always renders an <svg>; it only renders a <polyline> once
    // two ticks have accumulated, so the polyline is the real assertion.
    const sparkline = app.watchlistRow("AAPL").locator("svg polyline");
    await expect(
      sparkline,
      "no sparkline polyline drew for AAPL — client-side price history is not accumulating",
    ).toBeVisible({ timeout: 25_000 });

    const points = await sparkline.getAttribute("points");
    expect(points?.split(" ").length ?? 0).toBeGreaterThan(1);
  });
});
