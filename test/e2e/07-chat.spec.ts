import { test, expect } from "../fixtures/app";

/**
 * Contract §9 scenario 7 — AI chat against the deterministic mock.
 *
 * The rules under test are `backend/app/llm/README.md` §"Mock mode — the exact
 * rules". Requires the app under test to be running with LLM_MOCK=true (or with
 * no OPENROUTER_API_KEY); global-setup cannot detect that, so a live-model run
 * will surface here as a message-text mismatch.
 */
test.describe("scenario 7 — chat (mock LLM)", () => {
  test("mock mode is actually active", async ({ api }) => {
    const { status, body } = await api.chat("what is my portfolio worth?");
    expect(status).toBe(200);
    expect(
      body.message,
      `POST /api/chat did not return the mock summary — is LLM_MOCK=true? Got: ${JSON.stringify(body.message)}`,
    ).toMatch(/^You have \$[\d,]+\.\d{2} in cash across \d+ positions, total value \$[\d,]+\.\d{2}\.$/);
    expect(body.actions).toEqual([]);
  });

  test("'buy 5 AAPL' answers, shows an action line, and opens a real position", async ({
    app,
    api,
  }) => {
    await api.closePosition("AAPL");
    await app.open();

    await app.sendChat("buy 5 AAPL");

    await expect(app.page.getByTestId("chat-message-user").last()).toHaveText("buy 5 AAPL");
    await expect(app.lastAssistantMessage).toHaveText("Bought 5 AAPL.");

    const action = app.chatActions().last();
    await expect(action, "no chat-action line rendered for the executed trade").toBeVisible();
    await expect(action).toHaveAttribute("data-status", "executed");
    await expect(action).toContainText("AAPL");
    await expect(action).toContainText(/Bought 5 AAPL @ \$[\d,]+\.\d{2}/);

    // The trade is real, not just narrated.
    await expect(app.positionQty("AAPL")).toHaveText("5");
    expect(await api.positionQuantity("AAPL")).toBe(5);
    await expect(app.heatmapTile("AAPL")).toBeVisible();
  });

  test("the loading indicator appears while the reply is in flight", async ({ app }) => {
    await app.open();

    // Hold the response open so the indicator is observable without a sleep.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await app.page.route("**/api/chat", async (route) => {
      await gate;
      await route.continue();
    });

    await app.sendChat("how am I doing?");
    await expect(app.page.getByTestId("chat-loading")).toBeVisible();

    release();
    await expect(app.page.getByTestId("chat-loading")).toHaveCount(0);
    await expect(app.lastAssistantMessage).toContainText("You have $");
    await app.page.unroute("**/api/chat");
  });

  test("a rejected trade reports status=failed even though the mock text says otherwise", async ({
    app,
    api,
  }) => {
    // Documented mock quirk: the message is composed before the action runs.
    await app.open();
    const cashBefore = await app.readCash();

    await app.sendChat("buy 100000 AAPL");

    const action = app.chatActions().last();
    await expect(action).toBeVisible();
    await expect(action).toHaveAttribute("data-status", "failed");
    await expect(action).toContainText(/Insufficient cash: need \$[\d,.]+, have \$[\d,.]+/);

    const portfolio = await api.portfolio();
    expect(portfolio.cash_balance).toBeCloseTo(cashBefore, 2);
  });

  test("'sell N TICKER' closes down a position", async ({ app, api }) => {
    await api.closePosition("GOOGL");
    await api.trade("GOOGL", 4, "buy");
    await app.open();
    await expect(app.positionQty("GOOGL")).toHaveText("4");

    await app.sendChat("sell 4 GOOGL");

    await expect(app.lastAssistantMessage).toHaveText("Sold 4 GOOGL.");
    await expect(app.chatActions().last()).toHaveAttribute("data-status", "executed");
    await expect(app.positionRow("GOOGL")).toHaveCount(0);
    expect(await api.positionQuantity("GOOGL")).toBe(0);
  });

  test("the assistant manages the watchlist", async ({ app, api }) => {
    await api.closePosition("PYPL");
    await api.ensureTickerAbsent("PYPL");
    await app.open();

    await app.sendChat("add PYPL to my watchlist");

    await expect(app.lastAssistantMessage).toHaveText("Added PYPL to your watchlist.");
    await expect(app.chatActions().last()).toHaveAttribute("data-status", "executed");
    await expect(app.watchlistRow("PYPL")).toBeVisible();

    await app.sendChat("remove PYPL from my watchlist");

    await expect(app.lastAssistantMessage).toHaveText("Removed PYPL from your watchlist.");
    await expect(app.watchlistRow("PYPL")).toHaveCount(0);
  });

  test("conversation history survives a reload", async ({ app }) => {
    await app.open();
    const marker = "how concentrated am I?";

    await app.sendChat(marker);
    await expect(app.lastAssistantMessage).toContainText("You have $");

    await app.page.reload();
    await expect(app.page.getByTestId("total-value")).toHaveText(/^\$/);

    await expect(
      app.page.getByTestId("chat-message-user").filter({ hasText: marker }).last(),
      "the persisted turn did not come back from GET /api/chat/history",
    ).toBeVisible();
  });
});
