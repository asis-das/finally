import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PositionsTable } from "@/components/PositionsTable";
import { portfolio, priceMap } from "./fixtures";

describe("PositionsTable", () => {
  it("renders a row per position with the contract's test hooks", () => {
    render(
      <PositionsTable
        positions={portfolio.positions}
        prices={priceMap}
        selected={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByTestId("positions-table")).toBeInTheDocument();
    expect(screen.getByTestId("position-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("position-qty-AAPL")).toHaveTextContent("10");
    expect(screen.getByTestId("position-pnl-AAPL")).toHaveTextContent("+$25.00");
    expect(screen.getByTestId("position-pnl-NVDA")).toHaveTextContent("-$27.20");
  });

  it("re-values against the live tick instead of the payload price", () => {
    render(
      <PositionsTable
        positions={portfolio.positions}
        prices={{ ...priceMap, AAPL: { ...priceMap.AAPL, price: 200 } }}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    // 10 shares bought at 190, marked at 200.
    expect(screen.getByTestId("position-pnl-AAPL")).toHaveTextContent("+$100.00");
  });

  it("falls back to the payload price when the tape has no quote", () => {
    render(
      <PositionsTable
        positions={portfolio.positions}
        prices={{}}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId("position-pnl-AAPL")).toHaveTextContent("+$25.00");
  });

  it("selects the ticker when a row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <PositionsTable
        positions={portfolio.positions}
        prices={priceMap}
        selected={null}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("position-row-NVDA"));
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("points at the command bar when there is nothing to show", () => {
    render(
      <PositionsTable positions={[]} prices={{}} selected={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByText(/No open positions/i)).toBeInTheDocument();
    expect(screen.getByTestId("positions-table")).toBeInTheDocument();
  });
});
