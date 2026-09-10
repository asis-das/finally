"use client";

import { useState } from "react";
import { Panel } from "./Panel";
import { Sparkline } from "./Sparkline";
import { useFlash } from "@/lib/useFlash";
import { formatPercent, formatPrice, isValidTicker, normalizeTicker, toneClass } from "@/lib/format";
import type { PriceMap, PricePoint, WatchlistEntry } from "@/lib/types";

interface WatchlistProps {
  entries: WatchlistEntry[];
  prices: PriceMap;
  history: Record<string, PricePoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

/** Session move: how far the price has travelled since this page loaded. */
function sessionPercent(points: PricePoint[], fallback: number): number {
  if (points.length < 2) return fallback;
  const first = points[0].p;
  if (!first) return fallback;
  return ((points[points.length - 1].p - first) / first) * 100;
}

function Row({
  entry,
  price,
  points,
  selected,
  onSelect,
  onRemove,
}: {
  entry: WatchlistEntry;
  price: number | null;
  points: PricePoint[];
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const flash = useFlash(price);
  const change = sessionPercent(points, entry.change_percent ?? 0);

  return (
    <div
      data-testid={`watchlist-row-${entry.ticker}`}
      data-selected={selected ? "true" : "false"}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      className={`group grid h-9 cursor-pointer grid-cols-[1fr_68px_auto] items-center gap-2 border-l-2 pr-1.5 pl-2 transition-colors ${
        selected
          ? "border-l-accent bg-raised"
          : "border-l-transparent hover:bg-raised/60"
      }`}
    >
      <div className="min-w-0">
        <div className="truncate text-[13px] leading-tight font-semibold">
          {entry.ticker}
        </div>
        <div className={`num text-[10.5px] leading-tight ${toneClass(change)}`}>
          {formatPercent(change)}
        </div>
      </div>

      <Sparkline points={points} className="justify-self-center" />

      <div className="flex items-center gap-1">
        <span
          data-testid={`watchlist-price-${entry.ticker}`}
          className="num w-[72px] text-right text-[13px]"
        >
          <span key={flash.nonce} className={`inline-block px-1 ${flash.className}`}>
            {formatPrice(price)}
          </span>
        </span>
        <button
          type="button"
          data-testid={`watchlist-remove-${entry.ticker}`}
          aria-label={`Remove ${entry.ticker} from watchlist`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="flex size-5 items-center justify-center text-mute opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 hover:text-down focus-visible:opacity-100"
        >
          <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden>
            <path
              d="M1 1l7 7M8 1l-7 7"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}

export function Watchlist({
  entries,
  prices,
  history,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ticker = normalizeTicker(draft);
    if (!ticker) return;
    if (!isValidTicker(ticker)) {
      setError(`${ticker} is not a ticker symbol`);
      return;
    }

    setBusy(true);
    try {
      await onAdd(ticker);
      setDraft("");
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not add that ticker");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Watchlist"
      testId="watchlist"
      aside={<span className="num text-[10.5px] text-mute">{entries.length}</span>}
      bodyClassName="flex flex-col"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        {entries.length === 0 ? (
          <p className="p-3 text-[12px] text-dim">
            Nothing on the watchlist. Add a symbol below to start streaming prices.
          </p>
        ) : (
          entries.map((entry) => {
            const live = prices[entry.ticker];
            return (
              <Row
                key={entry.ticker}
                entry={entry}
                price={live ? live.price : entry.price}
                points={history[entry.ticker] ?? []}
                selected={selected === entry.ticker}
                onSelect={() => onSelect(entry.ticker)}
                onRemove={() => void onRemove(entry.ticker)}
              />
            );
          })
        )}
      </div>

      <form
        onSubmit={submit}
        className="shrink-0 border-t border-line bg-ground/70 px-2 py-2"
      >
        <div className="flex gap-1.5">
          <input
            data-testid="watchlist-add-input"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setError(null);
            }}
            placeholder="Add symbol"
            aria-label="Add symbol to watchlist"
            spellCheck={false}
            autoComplete="off"
            className="num min-w-0 flex-1 border border-line bg-panel px-2 py-1 text-[12px] uppercase placeholder:font-[family-name:var(--font-sans)] placeholder:normal-case placeholder:text-mute focus:border-primary focus:outline-none"
          />
          <button
            type="submit"
            data-testid="watchlist-add-submit"
            disabled={busy}
            className="border border-line-hi bg-raised px-2.5 text-[12px] font-medium text-ink transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
          >
            Add
          </button>
        </div>
        {error && (
          <p role="alert" className="mt-1.5 text-[11px] text-down">
            {error}
          </p>
        )}
      </form>
    </Panel>
  );
}
