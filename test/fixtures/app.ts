import {
  test as base,
  expect as baseExpect,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";

export const expect = baseExpect;

/** Money as the UI renders it: "$10,000.00" or "-$12.34" or "+$1,925.00". */
export const MONEY = /^[+-]?\$[\d,]+\.\d{2}$/;
/** Bare prices in the watchlist / positions table: "189.89". */
export const PRICE = /^[\d,]+\.\d{2}$/;

export const DEFAULT_TICKERS = [
  "AAPL",
  "GOOGL",
  "MSFT",
  "AMZN",
  "TSLA",
  "NVDA",
  "META",
  "JPM",
  "V",
  "NFLX",
];

/** Set FRESH_DB=1 when the app under test was started on an empty volume. */
export const FRESH_DB = process.env.FRESH_DB === "1" || process.env.FRESH_DB === "true";

/** "$10,000.00" -> 10000, "-$12.34" -> -12.34, "—" -> null. */
export function parseMoney(text: string | null): number | null {
  if (!text) return null;
  const cleaned = text.replace(/[$,\s]/g, "");
  if (!/^[+-]?\d+(\.\d+)?$/.test(cleaned)) return null;
  return Number(cleaned);
}

export function parseQuantity(text: string | null): number | null {
  if (!text) return null;
  const cleaned = text.replace(/[,\s]/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  return Number(cleaned);
}

async function money(locator: Locator): Promise<number> {
  const raw = (await locator.textContent())?.trim() ?? "";
  const value = parseMoney(raw);
  if (value === null) throw new Error(`Not a money value: ${JSON.stringify(raw)}`);
  return value;
}

/**
 * Page-object-ish helpers. Deliberately thin: the assertions stay in the specs
 * so a failure message points at the behaviour, not at a helper.
 */
export class Workstation {
  constructor(
    readonly page: Page,
    readonly api: ApiClient,
  ) {}

  async open() {
    await this.page.goto("/");
    // The header total only leaves "$0.00" once /api/portfolio has resolved.
    await expect(this.page.getByTestId("total-value")).toHaveText(MONEY);
    await expect(this.page.getByTestId("watchlist")).toBeVisible();
  }

  get totalValue() {
    return this.page.getByTestId("total-value");
  }
  get cashBalance() {
    return this.page.getByTestId("cash-balance");
  }
  get connectionStatus() {
    return this.page.getByTestId("connection-status");
  }
  watchlistRow(ticker: string) {
    return this.page.getByTestId(`watchlist-row-${ticker}`);
  }
  watchlistPrice(ticker: string) {
    return this.page.getByTestId(`watchlist-price-${ticker}`);
  }
  positionRow(ticker: string) {
    return this.page.getByTestId(`position-row-${ticker}`);
  }
  positionQty(ticker: string) {
    return this.page.getByTestId(`position-qty-${ticker}`);
  }
  positionPnl(ticker: string) {
    return this.page.getByTestId(`position-pnl-${ticker}`);
  }
  heatmapTile(ticker: string) {
    return this.page.getByTestId(`heatmap-tile-${ticker}`);
  }
  get tradeError() {
    return this.page.getByTestId("trade-error");
  }

  readCash() {
    return money(this.cashBalance);
  }
  readTotalValue() {
    return money(this.totalValue);
  }

  /** Quantity currently shown for a position, or 0 when there is no row. */
  async readPositionQuantity(ticker: string): Promise<number> {
    if ((await this.positionRow(ticker).count()) === 0) return 0;
    return parseQuantity(await this.positionQty(ticker).textContent()) ?? 0;
  }

  async placeOrder(ticker: string, quantity: number | string, side: "buy" | "sell") {
    await this.page.getByTestId("trade-ticker").fill(ticker);
    await this.page.getByTestId("trade-quantity").fill(String(quantity));
    await this.page.getByTestId(side === "buy" ? "trade-buy" : "trade-sell").click();
  }

  async addWatchlistTicker(ticker: string) {
    await this.page.getByTestId("watchlist-add-input").fill(ticker);
    await this.page.getByTestId("watchlist-add-submit").click();
  }

  async sendChat(message: string) {
    await this.page.getByTestId("chat-input").fill(message);
    await this.page.getByTestId("chat-send").click();
  }

  /** The last assistant bubble. Many exist across a session. */
  get lastAssistantMessage() {
    return this.page.getByTestId("chat-message-assistant").last();
  }

  chatActions() {
    return this.page.getByTestId("chat-action");
  }
}

/** Direct REST access, for arranging state without driving the UI. */
export class ApiClient {
  constructor(readonly request: APIRequestContext) {}

  async health() {
    const res = await this.request.get("/api/health");
    expect(res.ok(), `GET /api/health -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async portfolio() {
    const res = await this.request.get("/api/portfolio");
    expect(res.ok(), `GET /api/portfolio -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async watchlist(): Promise<{ tickers: Array<Record<string, unknown>> }> {
    const res = await this.request.get("/api/watchlist");
    expect(res.ok(), `GET /api/watchlist -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async history(limit = 500) {
    const res = await this.request.get(`/api/portfolio/history?limit=${limit}`);
    expect(res.ok(), `GET /api/portfolio/history -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  /** Raw trade call; returns status and body so specs can assert on failures too. */
  async tryTrade(ticker: string, quantity: number, side: "buy" | "sell") {
    const res = await this.request.post("/api/portfolio/trade", {
      data: { ticker, quantity, side },
    });
    return { status: res.status(), body: await res.json().catch(() => null) };
  }

  async trade(ticker: string, quantity: number, side: "buy" | "sell") {
    const result = await this.tryTrade(ticker, quantity, side);
    expect(
      result.status,
      `POST /api/portfolio/trade ${side} ${quantity} ${ticker} -> ${result.status} ${JSON.stringify(result.body)}`,
    ).toBe(200);
    return result.body;
  }

  async hasTicker(ticker: string) {
    const { tickers } = await this.watchlist();
    return tickers.some((entry) => entry.ticker === ticker);
  }

  async ensureTickerAbsent(ticker: string) {
    if (await this.hasTicker(ticker)) {
      await this.request.delete(`/api/watchlist/${ticker}`);
    }
  }

  async ensureTickerPresent(ticker: string) {
    if (!(await this.hasTicker(ticker))) {
      const res = await this.request.post("/api/watchlist", { data: { ticker } });
      expect(res.ok(), `POST /api/watchlist ${ticker} -> ${res.status()}`).toBeTruthy();
    }
  }

  /** Guarantees at least `minimum` shares are held, buying the shortfall. */
  async ensurePosition(ticker: string, minimum: number) {
    const held = await this.positionQuantity(ticker);
    if (held < minimum) await this.trade(ticker, minimum - held, "buy");
  }

  async positionQuantity(ticker: string): Promise<number> {
    const portfolio = await this.portfolio();
    const position = (portfolio.positions ?? []).find(
      (p: { ticker: string }) => p.ticker === ticker,
    );
    return position ? position.quantity : 0;
  }

  async closePosition(ticker: string) {
    const held = await this.positionQuantity(ticker);
    if (held > 0) await this.trade(ticker, held, "sell");
  }

  async chat(message: string) {
    const res = await this.request.post("/api/chat", { data: { message } });
    return { status: res.status(), body: await res.json().catch(() => null) };
  }
}

type Fixtures = {
  api: ApiClient;
  app: Workstation;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },

  /**
   * Attaches every /api/* response body seen during the test to the report, so a
   * failure carries the payload that caused it without a second run.
   */
  app: async ({ page, api }, use, testInfo) => {
    const traffic: string[] = [];
    page.on("response", async (response) => {
      const url = new URL(response.url());
      if (!url.pathname.startsWith("/api/") || url.pathname.startsWith("/api/stream/")) return;
      let body = "<unreadable>";
      try {
        body = (await response.text()).slice(0, 4_000);
      } catch {
        /* body already consumed or connection closed */
      }
      traffic.push(
        `${new Date().toISOString()} ${response.request().method()} ${url.pathname}${url.search} -> ${response.status()}\n${body}`,
      );
    });

    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

    await use(new Workstation(page, api));

    if (testInfo.status !== testInfo.expectedStatus) {
      if (traffic.length) {
        await testInfo.attach("api-traffic.log", {
          body: traffic.join("\n\n"),
          contentType: "text/plain",
        });
      }
      if (consoleErrors.length) {
        await testInfo.attach("browser-console-errors.log", {
          body: consoleErrors.join("\n"),
          contentType: "text/plain",
        });
      }
    }
  },
});
