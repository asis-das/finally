import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TradeBar } from "@/components/TradeBar";
import { tradeResult } from "./fixtures";

function setup(onSubmit = vi.fn().mockResolvedValue(tradeResult)) {
  const onTickerChange = vi.fn();
  render(
    <TradeBar
      ticker="AAPL"
      onTickerChange={onTickerChange}
      price={192.5}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, onTickerChange, user: userEvent.setup() };
}

describe("TradeBar", () => {
  it("exposes the contract's test hooks", () => {
    setup();
    expect(screen.getByTestId("trade-ticker")).toHaveValue("AAPL");
    expect(screen.getByTestId("trade-quantity")).toBeInTheDocument();
    expect(screen.getByTestId("trade-buy")).toBeInTheDocument();
    expect(screen.getByTestId("trade-sell")).toBeInTheDocument();
    expect(screen.queryByTestId("trade-error")).not.toBeInTheDocument();
  });

  it("sends a buy as a market order and reports the fill", async () => {
    const { onSubmit, user } = setup();

    await user.type(screen.getByTestId("trade-quantity"), "10");
    await user.click(screen.getByTestId("trade-buy"));

    expect(onSubmit).toHaveBeenCalledWith("AAPL", 10, "buy");
    expect(await screen.findByText(/Bought 10 AAPL at 192.50/)).toBeInTheDocument();
    expect(screen.getByTestId("trade-quantity")).toHaveValue("");
  });

  it("sends a sell with the same inputs", async () => {
    const { onSubmit, user } = setup();
    await user.type(screen.getByTestId("trade-quantity"), "2.5");
    await user.click(screen.getByTestId("trade-sell"));
    expect(onSubmit).toHaveBeenCalledWith("AAPL", 2.5, "sell");
  });

  it("previews the order value from the live price", async () => {
    const { user } = setup();
    await user.type(screen.getByTestId("trade-quantity"), "4");
    expect(screen.getByText("$770.00")).toBeInTheDocument();
  });

  it("shows the server's rejection in trade-error", async () => {
    const { user } = setup(
      vi
        .fn()
        .mockRejectedValue(new Error("Insufficient cash: need $1925.00, have $100.00")),
    );

    await user.type(screen.getByTestId("trade-quantity"), "10");
    await user.click(screen.getByTestId("trade-buy"));

    expect(await screen.findByTestId("trade-error")).toHaveTextContent(
      "Insufficient cash: need $1925.00, have $100.00",
    );
  });

  it("blocks a non-positive quantity without calling the API", async () => {
    const { onSubmit, user } = setup();
    await user.type(screen.getByTestId("trade-quantity"), "0");
    await user.click(screen.getByTestId("trade-buy"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByTestId("trade-error")).toHaveTextContent(
      "quantity greater than zero",
    );
  });

  it("blocks an empty symbol", async () => {
    const onSubmit = vi.fn();
    render(
      <TradeBar ticker="  " onTickerChange={vi.fn()} price={null} onSubmit={onSubmit} />,
    );
    await userEvent.setup().click(screen.getByTestId("trade-buy"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Enter a symbol");
  });

  it("upper-cases what the user types into the symbol field", async () => {
    const { onTickerChange, user } = setup();
    await user.type(screen.getByTestId("trade-ticker"), "n");
    expect(onTickerChange).toHaveBeenCalledWith("AAPLN");
  });
});
