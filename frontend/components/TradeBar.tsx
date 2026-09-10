"use client";

import { useState } from "react";
import { formatCurrency, formatPrice, normalizeTicker } from "@/lib/format";
import type { TradeResult } from "@/lib/types";

interface TradeBarProps {
  ticker: string;
  onTickerChange: (ticker: string) => void;
  /** Live price for the typed symbol, for the order-value preview. */
  price: number | null;
  onSubmit: (
    ticker: string,
    quantity: number,
    side: "buy" | "sell",
  ) => Promise<TradeResult>;
}

/**
 * The command bar. It sits on the bottom edge of the workspace the way an order
 * line does on a dealing terminal — always reachable, never in a dialog.
 */
export function TradeBar({ ticker, onTickerChange, price, onSubmit }: TradeBarProps) {
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const parsedQuantity = Number.parseFloat(quantity);
  const orderValue =
    price !== null && Number.isFinite(parsedQuantity) && parsedQuantity > 0
      ? parsedQuantity * price
      : null;

  async function place(side: "buy" | "sell") {
    const symbol = normalizeTicker(ticker);
    setReceipt(null);

    if (!symbol) {
      setError("Enter a symbol");
      return;
    }
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setError("Enter a quantity greater than zero");
      return;
    }

    setBusy(true);
    try {
      const result = await onSubmit(symbol, parsedQuantity, side);
      setError(null);
      setQuantity("");
      setReceipt(
        `${side === "buy" ? "Bought" : "Sold"} ${result.trade.quantity} ${result.trade.ticker} at ${formatPrice(result.trade.price)}`,
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Trade rejected");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(event) => event.preventDefault()}
      className="flex h-12 shrink-0 items-center gap-3 border-t border-line bg-ground px-3"
    >
      <span className="panel-title hidden md:block">Order</span>

      <input
        data-testid="trade-ticker"
        value={ticker}
        onChange={(event) => {
          onTickerChange(event.target.value.toUpperCase());
          setError(null);
        }}
        placeholder="SYMBOL"
        aria-label="Order symbol"
        spellCheck={false}
        autoComplete="off"
        className="num w-24 border border-line bg-panel px-2 py-1.5 text-[13px] uppercase placeholder:text-mute focus:border-primary focus:outline-none"
      />

      <input
        data-testid="trade-quantity"
        value={quantity}
        onChange={(event) => {
          setQuantity(event.target.value);
          setError(null);
        }}
        inputMode="decimal"
        placeholder="QTY"
        aria-label="Order quantity"
        autoComplete="off"
        className="num w-24 border border-line bg-panel px-2 py-1.5 text-right text-[13px] placeholder:text-mute focus:border-primary focus:outline-none"
      />

      <div className="hidden w-52 shrink-0 flex-col leading-none lg:flex">
        <span className="col-head mb-1">Order value</span>
        <span className="num truncate text-[12.5px] whitespace-nowrap text-dim">
          {orderValue !== null ? formatCurrency(orderValue) : "—"}
          {price !== null && (
            <span className="ml-1.5 text-mute">@ {formatPrice(price)}</span>
          )}
        </span>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          data-testid="trade-buy"
          disabled={busy}
          onClick={() => void place("buy")}
          className="h-8 w-20 bg-secondary text-[12.5px] font-semibold tracking-wide text-white transition-colors hover:brightness-115 disabled:opacity-50"
        >
          Buy
        </button>
        <button
          type="button"
          data-testid="trade-sell"
          disabled={busy}
          onClick={() => void place("sell")}
          className="h-8 w-20 border border-secondary text-[12.5px] font-semibold tracking-wide text-secondary-lit transition-colors hover:bg-secondary/20 disabled:opacity-50"
        >
          Sell
        </button>
      </div>

      <div className="min-w-0 flex-1 truncate text-[12px]">
        {error ? (
          <span data-testid="trade-error" role="alert" className="text-down">
            {error}
          </span>
        ) : receipt ? (
          <span className="text-dim">{receipt}</span>
        ) : null}
      </div>
    </form>
  );
}
