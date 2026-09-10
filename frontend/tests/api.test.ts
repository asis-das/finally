import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import { portfolio, tradeResult, watchlist } from "./fixtures";

function mockFetch(body: unknown, init: { status?: number; ok?: boolean } = {}) {
  const status = init.status ?? 200;
  const response = {
    ok: init.ok ?? status < 400,
    status,
    json: async () => body,
  };
  const spy = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("reads the portfolio from the contract path", async () => {
    const spy = mockFetch(portfolio);
    await expect(api.getPortfolio()).resolves.toEqual(portfolio);
    expect(spy.mock.calls[0][0]).toBe("/api/portfolio");
  });

  it("posts a trade as JSON", async () => {
    const spy = mockFetch(tradeResult);
    await expect(api.trade("AAPL", 10, "buy")).resolves.toEqual(tradeResult);

    const [url, init] = spy.mock.calls[0];
    expect(url).toBe("/api/portfolio/trade");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ ticker: "AAPL", quantity: 10, side: "buy" });
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("deletes a watchlist ticker by path segment", async () => {
    const spy = mockFetch({ ticker: "PYPL", removed: true });
    await api.removeTicker("PYPL");
    expect(spy.mock.calls[0][0]).toBe("/api/watchlist/PYPL");
    expect(spy.mock.calls[0][1].method).toBe("DELETE");
  });

  it("unwraps the watchlist payload", async () => {
    mockFetch({ tickers: watchlist });
    await expect(api.getWatchlist()).resolves.toEqual({ tickers: watchlist });
  });

  it("turns FastAPI's detail into the thrown message", async () => {
    mockFetch({ detail: "Insufficient cash: need $1925.00, have $100.00" }, { status: 400 });
    await expect(api.trade("AAPL", 10, "buy")).rejects.toThrow(
      "Insufficient cash: need $1925.00, have $100.00",
    );
  });

  it("keeps the status code on the error", async () => {
    mockFetch({ detail: "No price available for AAPL" }, { status: 404 });
    await expect(api.trade("AAPL", 1, "buy")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });

  it("surfaces the message from FastAPI's 422 validation array", async () => {
    mockFetch(
      {
        detail: [
          {
            type: "greater_than",
            loc: ["body", "quantity"],
            msg: "Input should be greater than 0",
            input: 0,
          },
        ],
      },
      { status: 422 },
    );
    await expect(api.trade("AAPL", 0, "buy")).rejects.toThrow(
      "Input should be greater than 0",
    );
  });

  it("joins a multi-field 422 rather than dropping all but one", async () => {
    mockFetch(
      {
        detail: [
          { loc: ["body", "quantity"], msg: "Input should be greater than 0" },
          { loc: ["body", "side"], msg: "Input should be 'buy' or 'sell'" },
        ],
      },
      { status: 422 },
    );
    await expect(api.trade("AAPL", 0, "buy")).rejects.toThrow(
      "Input should be greater than 0; Input should be 'buy' or 'sell'",
    );
  });

  it("keeps the generic message when a 422 array carries no usable msg", async () => {
    mockFetch({ detail: [{ loc: ["body"] }, "not an object"] }, { status: 422 });
    await expect(api.trade("AAPL", 0, "buy")).rejects.toThrow("Request failed (422)");
  });

  it("falls back to a generic message for a non-JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );
    await expect(api.getPortfolio()).rejects.toBeInstanceOf(ApiError);
  });
});
