import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Watchlist } from "@/components/Watchlist";
import { priceMap, seriesFor, watchlist } from "./fixtures";
import type { PriceMap } from "@/lib/types";

function renderWatchlist(overrides: Partial<React.ComponentProps<typeof Watchlist>> = {}) {
  const props: React.ComponentProps<typeof Watchlist> = {
    entries: watchlist,
    prices: priceMap,
    history: { AAPL: seriesFor("AAPL", [191.8, 192.1, 192.5]) },
    selected: "AAPL",
    onSelect: vi.fn(),
    onAdd: vi.fn().mockResolvedValue(undefined),
    onRemove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return { props, ...render(<Watchlist {...props} />) };
}

describe("Watchlist", () => {
  it("exposes the contract's test hooks for every row", () => {
    renderWatchlist();
    expect(screen.getByTestId("watchlist")).toBeInTheDocument();
    for (const entry of watchlist) {
      expect(screen.getByTestId(`watchlist-row-${entry.ticker}`)).toBeInTheDocument();
      expect(screen.getByTestId(`watchlist-price-${entry.ticker}`)).toBeInTheDocument();
      expect(screen.getByTestId(`watchlist-remove-${entry.ticker}`)).toBeInTheDocument();
    }
  });

  it("prefers the live tick over the payload price and shows a dash when unpriced", () => {
    renderWatchlist({
      prices: { ...priceMap, AAPL: { ...priceMap.AAPL, price: 200.25 } } as PriceMap,
    });
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("200.25");
    expect(screen.getByTestId("watchlist-price-JPM")).toHaveTextContent("—");
  });

  it("shows the backend's daily move, not a since-page-load figure", () => {
    // History that would read as +5.8% if the row computed its own session move.
    renderWatchlist({
      history: { AAPL: seriesFor("AAPL", [182.0, 188.0, 192.5]) },
    });

    const row = screen.getByTestId("watchlist-row-AAPL");
    expect(row).toHaveTextContent("+1.32%");
    expect(row).not.toHaveTextContent("5.7");
    expect(screen.getByTestId("watchlist-row-NVDA")).toHaveTextContent("-5.44%");
  });

  it("holds the day figure steady while ticks keep arriving", () => {
    const { rerender, props } = renderWatchlist();
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveTextContent("+1.32%");

    rerender(
      <Watchlist
        {...props}
        prices={{ ...priceMap, AAPL: { ...priceMap.AAPL, price: 199.9 } }}
        history={{ AAPL: seriesFor("AAPL", [192.5, 196.0, 199.9]) }}
      />,
    );
    // The tape moved; the daily figure only changes when the API says so.
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveTextContent("+1.32%");
  });

  it("reads flat, never NaN, when the ticker has no reference price", () => {
    renderWatchlist();
    const cell = screen.getByTitle("No reference price yet");
    expect(cell).toHaveTextContent("—");
    expect(screen.getByTestId("watchlist-row-JPM")).not.toHaveTextContent("NaN");
    expect(screen.getByTestId("watchlist-row-JPM")).not.toHaveTextContent("%");
  });

  it("names the reference the daily move is measured against", () => {
    renderWatchlist();
    expect(screen.getByTitle("Since 190.00")).toHaveTextContent("+1.32%");
  });

  it("falls back to flat when the backend omits the daily fields entirely", () => {
    const legacy = {
      ticker: "AAPL",
      price: 192.5,
      previous_price: 192.45,
      change: 0.05,
      change_percent: 0.03,
      direction: "up",
    } as unknown as (typeof watchlist)[number];

    renderWatchlist({ entries: [legacy] });
    const row = screen.getByTestId("watchlist-row-AAPL");
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent("NaN");
  });

  it("flashes green on an uptick and red on a downtick, then clears", async () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <Watchlist
        entries={watchlist}
        prices={priceMap}
        history={{}}
        selected={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    const cell = () => screen.getByTestId("watchlist-price-AAPL").firstElementChild!;
    expect(cell().className).not.toMatch(/flash/);

    rerender(
      <Watchlist
        entries={watchlist}
        prices={{ ...priceMap, AAPL: { ...priceMap.AAPL, price: 193.5 } }}
        history={{}}
        selected={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(cell().className).toContain("flash-up");

    rerender(
      <Watchlist
        entries={watchlist}
        prices={{ ...priceMap, AAPL: { ...priceMap.AAPL, price: 190.1 } }}
        history={{}}
        selected={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(cell().className).toContain("flash-down");

    act(() => void vi.advanceTimersByTime(600));
    expect(cell().className).not.toMatch(/flash/);
    vi.useRealTimers();
  });

  it("selects a ticker when its row is clicked", () => {
    const { props } = renderWatchlist();
    fireEvent.click(screen.getByTestId("watchlist-row-NVDA"));
    expect(props.onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("removes without selecting the row", () => {
    const { props } = renderWatchlist();
    fireEvent.click(screen.getByTestId("watchlist-remove-NVDA"));
    expect(props.onRemove).toHaveBeenCalledWith("NVDA");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("adds a normalised ticker and clears the field", async () => {
    const user = userEvent.setup();
    const { props } = renderWatchlist();

    await user.type(screen.getByTestId("watchlist-add-input"), "pypl");
    await user.click(screen.getByTestId("watchlist-add-submit"));

    expect(props.onAdd).toHaveBeenCalledWith("PYPL");
    await waitFor(() =>
      expect(screen.getByTestId("watchlist-add-input")).toHaveValue(""),
    );
  });

  it("rejects a malformed symbol before calling the API", async () => {
    const user = userEvent.setup();
    const { props } = renderWatchlist();

    await user.type(screen.getByTestId("watchlist-add-input"), "abc123");
    await user.click(screen.getByTestId("watchlist-add-submit"));

    expect(props.onAdd).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("not a ticker symbol");
  });

  it("surfaces the server's rejection message", async () => {
    const user = userEvent.setup();
    renderWatchlist({
      onAdd: vi.fn().mockRejectedValue(new Error("Ticker AAPL is already on the watchlist")),
    });

    await user.type(screen.getByTestId("watchlist-add-input"), "AAPL");
    await user.click(screen.getByTestId("watchlist-add-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ticker AAPL is already on the watchlist",
    );
  });

  it("invites the first symbol when the list is empty", () => {
    renderWatchlist({ entries: [] });
    expect(screen.getByText(/Nothing on the watchlist/i)).toBeInTheDocument();
  });
});
