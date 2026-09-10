"use client";

import { useCallback, useMemo, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { DetailChart } from "@/components/DetailChart";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { PnlChart } from "@/components/PnlChart";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { api } from "@/lib/api";
import { useAccountData } from "@/lib/useAccountData";
import { useChat } from "@/lib/useChat";
import { usePriceStream } from "@/lib/usePriceStream";

export default function Workstation() {
  const { prices, history, connection } = usePriceStream();
  const { portfolio, watchlist, snapshots, loadError, refresh } = useAccountData();

  const [pickedTicker, setPickedTicker] = useState<string | null>(null);
  const [typedTicker, setTypedTicker] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);

  const chat = useChat(refresh);

  // Both fall back rather than being written by an effect: until the user picks
  // something, the workspace shows the first watched symbol.
  const selected = pickedTicker ?? watchlist[0]?.ticker ?? null;
  const orderTicker = typedTicker ?? selected ?? "";

  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio]);

  // The header must not wait for the next /api/portfolio poll to move, so the
  // total is re-struck from the live tape on every tick.
  const liveTotals = useMemo(() => {
    const cash = portfolio?.cash_balance ?? 0;
    let marketValue = 0;
    let costBasis = 0;
    for (const position of positions) {
      const price = prices[position.ticker]?.price ?? position.current_price;
      marketValue += position.quantity * price;
      costBasis += position.quantity * position.avg_cost;
    }
    const pnl = marketValue - costBasis;
    return {
      totalValue: cash + marketValue,
      cash,
      pnl,
      pnlPercent: costBasis ? (pnl / costBasis) * 100 : 0,
    };
  }, [portfolio, positions, prices]);

  const select = useCallback((ticker: string) => {
    setPickedTicker(ticker);
    setTypedTicker(ticker);
  }, []);

  const addTicker = useCallback(
    async (ticker: string) => {
      await api.addTicker(ticker);
      await refresh();
      select(ticker);
    },
    [refresh, select],
  );

  const removeTicker = useCallback(
    async (ticker: string) => {
      await api.removeTicker(ticker);
      await refresh();
      setPickedTicker((current) => (current === ticker ? null : current));
    },
    [refresh],
  );

  const placeOrder = useCallback(
    async (ticker: string, quantity: number, side: "buy" | "sell") => {
      const result = await api.trade(ticker, quantity, side);
      await refresh();
      return result;
    },
    [refresh],
  );

  const selectedPrice =
    selected && prices[selected] ? prices[selected].price : null;
  const orderPrice = prices[orderTicker.trim().toUpperCase()]?.price ?? null;

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-line">
      <Header
        totalValue={liveTotals.totalValue}
        cashBalance={liveTotals.cash}
        unrealizedPnl={liveTotals.pnl}
        unrealizedPnlPercent={liveTotals.pnlPercent}
        connection={connection}
      />

      {loadError && (
        <p
          role="alert"
          className="shrink-0 border-b border-line bg-down/15 px-4 py-1.5 text-[12px] text-down"
        >
          {loadError} — retrying on the next update.
        </p>
      )}

      {/*
        Below xl the workspace is a scrolling stack of fixed-height panes — the
        charts need a definite height to draw into. At xl it becomes the three
        column terminal, and the panes stretch to their grid tracks instead.
      */}
      <main
        className={`flex min-h-0 flex-1 flex-col gap-px overflow-y-auto bg-line xl:grid xl:overflow-hidden ${
          chatOpen
            ? "xl:grid-cols-[286px_minmax(0,1fr)_356px]"
            : "xl:grid-cols-[286px_minmax(0,1fr)_28px]"
        }`}
      >
        <div className="h-[340px] shrink-0 xl:h-auto xl:min-h-0">
          <Watchlist
            entries={watchlist}
            prices={prices}
            history={history}
            selected={selected}
            onSelect={select}
            onAdd={addTicker}
            onRemove={removeTicker}
          />
        </div>

        <div className="flex flex-col gap-px bg-line xl:grid xl:min-h-0 xl:grid-rows-[minmax(0,1.35fr)_minmax(0,1.1fr)_minmax(0,0.85fr)]">
          <div className="h-[300px] shrink-0 xl:h-auto xl:min-h-0">
            <DetailChart
              ticker={selected}
              points={selected ? (history[selected] ?? []) : []}
              price={selectedPrice}
            />
          </div>

          <div className="flex flex-col gap-px bg-line sm:flex-row xl:grid xl:min-h-0 xl:grid-cols-2">
            <div className="h-[240px] shrink-0 sm:flex-1 xl:h-auto xl:min-h-0 xl:min-w-0">
              <Heatmap positions={positions} selected={selected} onSelect={select} />
            </div>
            <div className="h-[240px] shrink-0 sm:flex-1 xl:h-auto xl:min-h-0 xl:min-w-0">
              <PnlChart snapshots={snapshots} liveValue={liveTotals.totalValue} />
            </div>
          </div>

          <div className="h-[300px] shrink-0 xl:h-auto xl:min-h-0">
            <PositionsTable
              positions={positions}
              prices={prices}
              selected={selected}
              onSelect={select}
            />
          </div>
        </div>

        {chatOpen ? (
          <div className="relative h-[420px] shrink-0 xl:h-auto xl:min-h-0">
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              aria-label="Hide assistant"
              className="absolute top-1 right-2 z-10 hidden size-5 items-center justify-center text-mute hover:text-ink xl:flex"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path
                  d="M1 5h8M6 2l3 3-3 3"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            <ChatPanel
              messages={chat.messages}
              pending={chat.pending}
              error={chat.error}
              onSend={chat.send}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            className="hidden bg-panel text-mute hover:text-accent xl:block"
          >
            <span className="panel-title [writing-mode:vertical-rl]">Assistant</span>
          </button>
        )}
      </main>

      <TradeBar
        ticker={orderTicker}
        onTickerChange={setTypedTicker}
        price={orderPrice}
        onSubmit={placeOrder}
      />
    </div>
  );
}
