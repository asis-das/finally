/**
 * Payloads copied from planning/BUILD_CONTRACT.md §5–§7. These double as the
 * fixtures the components are developed against, so a contract drift shows up
 * as a failing unit test rather than a broken screen.
 */
import type {
  ChatMessage,
  ChatReply,
  Portfolio,
  PriceMap,
  Snapshot,
  TradeResult,
  WatchlistEntry,
} from "@/lib/types";

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
] as const;

export const priceMap: PriceMap = {
  AAPL: {
    ticker: "AAPL",
    price: 192.5,
    previous_price: 192.0,
    timestamp: 1757505600.0,
    change: 0.5,
    change_percent: 0.26,
    direction: "up",
  },
  NVDA: {
    ticker: "NVDA",
    price: 118.2,
    previous_price: 118.9,
    timestamp: 1757505600.0,
    change: -0.7,
    change_percent: -0.59,
    direction: "down",
  },
};

export const watchlist: WatchlistEntry[] = [
  {
    ticker: "AAPL",
    price: 192.5,
    previous_price: 192.45,
    change: 0.05,
    change_percent: 0.03,
    direction: "up",
    previous_close: 190.0,
    day_change: 2.5,
    day_change_percent: 1.32,
  },
  {
    ticker: "NVDA",
    price: 118.2,
    previous_price: 118.9,
    change: -0.7,
    change_percent: -0.59,
    direction: "down",
    previous_close: 125.0,
    day_change: -6.8,
    day_change_percent: -5.44,
  },
  // Never priced: no reference, so no daily move to report.
  {
    ticker: "JPM",
    price: null,
    previous_price: null,
    change: 0,
    change_percent: 0,
    direction: "flat",
    previous_close: null,
    day_change: 0,
    day_change_percent: 0,
  },
];

export const portfolio: Portfolio = {
  cash_balance: 8075.0,
  positions: [
    {
      ticker: "AAPL",
      quantity: 10.0,
      avg_cost: 190.0,
      current_price: 192.5,
      market_value: 1925.0,
      unrealized_pnl: 25.0,
      unrealized_pnl_percent: 1.32,
      weight: 0.19,
    },
    {
      ticker: "NVDA",
      quantity: 4.0,
      avg_cost: 125.0,
      current_price: 118.2,
      market_value: 472.8,
      unrealized_pnl: -27.2,
      unrealized_pnl_percent: -5.44,
      weight: 0.05,
    },
  ],
  positions_value: 2397.8,
  total_value: 10472.8,
  total_cost_basis: 2400.0,
  total_unrealized_pnl: -2.2,
  total_unrealized_pnl_percent: -0.09,
};

export const snapshots: Snapshot[] = [
  { total_value: 10000.0, recorded_at: "2026-09-10T12:00:00+00:00" },
  { total_value: 10120.5, recorded_at: "2026-09-10T12:00:30+00:00" },
  { total_value: 10472.8, recorded_at: "2026-09-10T12:01:00+00:00" },
];

export const tradeResult: TradeResult = {
  trade: {
    id: "b0f1c2d3-0000-4000-8000-000000000001",
    ticker: "AAPL",
    side: "buy",
    quantity: 10.0,
    price: 192.5,
    executed_at: "2026-09-10T12:00:00+00:00",
  },
  cash_balance: 8075.0,
  position: { ticker: "AAPL", quantity: 10.0, avg_cost: 192.5 },
  total_value: 10000.0,
};

export const chatMessages: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    content: "buy me 10 apple shares",
    actions: null,
    created_at: "2026-09-10T12:00:00+00:00",
  },
  {
    id: "m2",
    role: "assistant",
    content: "Bought 10 AAPL at $192.50. Your cash is now $8,075.00.",
    actions: [
      {
        type: "trade",
        status: "executed",
        ticker: "AAPL",
        side: "buy",
        quantity: 10.0,
        price: 192.5,
        detail: "Bought 10 AAPL @ $192.50",
      },
      {
        type: "watchlist",
        status: "failed",
        ticker: "PYPL",
        action: "add",
        detail: "Ticker PYPL is already on the watchlist",
      },
    ],
    created_at: "2026-09-10T12:00:00+00:00",
  },
];

export const chatReply: ChatReply = {
  message: "Bought 5 NVDA.",
  actions: [
    {
      type: "trade",
      status: "executed",
      ticker: "NVDA",
      side: "buy",
      quantity: 5,
      price: 118.2,
      detail: "Bought 5 NVDA @ $118.20",
    },
  ],
  created_at: "2026-09-10T12:02:00+00:00",
};

export function seriesFor(ticker: string, values: number[]) {
  void ticker;
  return values.map((p, index) => ({ t: 1757505600 + index * 0.5, p }));
}
