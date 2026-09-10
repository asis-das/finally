import { test, expect, PRICE } from "../fixtures/app";

const STREAM = "**/api/stream/prices";

/**
 * Contract §9 scenario 8 — the tape survives losing the network.
 *
 * Mechanism note. `browserContext.setOffline(true)` is NOT usable here: it was
 * measured against this build and an already-established EventSource keeps
 * delivering frames right through the offline window (probe: 41 messages
 * received while offline, dot never left "connected"). Chromium applies the
 * offline emulation to new connections, not to an open response body. So the
 * outage is simulated by aborting the stream request at the route layer, which
 * is what a dropped connection looks like to EventSource, and recovery is left
 * entirely to the browser's built-in retry — no application code re-subscribes.
 */
test.describe("scenario 8 — SSE resilience", () => {
  test("the dot degrades while the stream is down and prices resume when it returns", async ({
    app,
  }) => {
    await app.open();
    await expect(app.connectionStatus).toHaveAttribute("data-status", "connected");
    await expect(app.watchlistPrice("AAPL")).toHaveText(PRICE);

    // Cut the stream, then force the client to notice by re-subscribing.
    let blocked = true;
    await app.page.route(STREAM, async (route) => {
      if (blocked) await route.abort("connectionfailed");
      else await route.continue();
    });
    await app.page.reload();

    await expect(
      app.connectionStatus,
      "the connection dot still claims 'connected' with the stream refusing connections",
    ).not.toHaveAttribute("data-status", "connected", { timeout: 30_000 });

    // Three failed retries must escalate yellow -> red (frontend contract §7.2).
    await expect(
      app.connectionStatus,
      "the dot never escalated to 'disconnected' after repeated failures",
    ).toHaveAttribute("data-status", "disconnected", { timeout: 45_000 });

    // The rest of the workstation still works while the tape is dark.
    await expect(app.totalValue).toHaveText(/^\$[\d,]+\.\d{2}$/);

    const stalled = await app.watchlistPrice("AAPL").textContent();

    blocked = false;

    // No user action, no reload: EventSource retries on its own.
    await expect(
      app.connectionStatus,
      "the stream never re-opened after the outage cleared",
    ).toHaveAttribute("data-status", "connected", { timeout: 45_000 });

    await expect
      .poll(async () => app.watchlistPrice("AAPL").textContent(), {
        message: "prices did not resume ticking after reconnection",
        timeout: 45_000,
        intervals: [250, 500, 1_000],
      })
      .not.toBe(stalled);

    await app.page.unroute(STREAM);
  });

  test("trading still works once the stream has recovered", async ({ app, api }) => {
    await api.closePosition("META");
    await app.open();

    let blocked = true;
    await app.page.route(STREAM, async (route) => {
      if (blocked) await route.abort("connectionfailed");
      else await route.continue();
    });
    await app.page.reload();
    await expect(app.connectionStatus).not.toHaveAttribute("data-status", "connected", {
      timeout: 30_000,
    });

    blocked = false;
    await expect(app.connectionStatus).toHaveAttribute("data-status", "connected", {
      timeout: 45_000,
    });

    await app.placeOrder("META", 1, "buy");
    await expect(app.positionRow("META")).toBeVisible();
    expect(await api.positionQuantity("META")).toBe(1);

    await app.page.unroute(STREAM);
    await api.closePosition("META");
  });

  test("a trade placed while the tape is dark is still accepted by the server", async ({
    app,
    api,
  }) => {
    // Prices come from the server-side cache, not from the browser's stream, so
    // an outage in the tape must not block order entry.
    await api.closePosition("JPM");
    await app.page.route(STREAM, (route) => route.abort("connectionfailed"));
    await app.open();
    await expect(app.connectionStatus).not.toHaveAttribute("data-status", "connected", {
      timeout: 30_000,
    });

    await app.placeOrder("JPM", 1, "buy");

    await expect(app.positionRow("JPM")).toBeVisible();
    expect(await api.positionQuantity("JPM")).toBe(1);

    await app.page.unroute(STREAM);
    await api.closePosition("JPM");
  });
});
