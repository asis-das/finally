import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MAX_POINTS, usePriceStream } from "@/lib/usePriceStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

const original = globalThis.EventSource;

function tick(ticker: string, price: number, timestamp: number) {
  return {
    [ticker]: {
      ticker,
      price,
      previous_price: price - 0.5,
      timestamp,
      change: 0.5,
      change_percent: 0.26,
      direction: "up" as const,
    },
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
});

afterEach(() => {
  globalThis.EventSource = original;
});

describe("usePriceStream", () => {
  it("subscribes to the contract's stream endpoint", () => {
    renderHook(() => usePriceStream());
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/stream/prices");
  });

  it("starts as reconnecting and goes live on open", () => {
    const { result } = renderHook(() => usePriceStream());
    expect(result.current.connection).toBe("reconnecting");

    act(() => FakeEventSource.instances[0].onopen?.(new Event("open")));
    expect(result.current.connection).toBe("connected");
  });

  it("merges ticker-keyed payloads and accumulates sparkline history", () => {
    const { result } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];

    act(() => source.emit(tick("AAPL", 192.5, 1)));
    act(() => source.emit(tick("AAPL", 193.0, 2)));
    act(() => source.emit(tick("NVDA", 118.2, 2)));

    expect(result.current.prices.AAPL.price).toBe(193.0);
    expect(result.current.prices.NVDA.price).toBe(118.2);
    expect(result.current.history.AAPL.map((point) => point.p)).toEqual([192.5, 193.0]);
    expect(result.current.history.NVDA).toHaveLength(1);
  });

  it(`caps history at ${MAX_POINTS} points per ticker`, () => {
    const { result } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];

    act(() => {
      for (let i = 0; i < MAX_POINTS + 40; i += 1) source.emit(tick("AAPL", 100 + i, i));
    });

    const points = result.current.history.AAPL;
    expect(points).toHaveLength(MAX_POINTS);
    expect(points[points.length - 1].p).toBe(100 + MAX_POINTS + 39);
  });

  it("ignores malformed frames without dropping the stream", () => {
    const { result } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];

    act(() => source.onmessage?.({ data: "{not json" } as MessageEvent<string>));
    act(() => source.emit(tick("AAPL", 192.5, 1)));

    expect(result.current.prices.AAPL.price).toBe(192.5);
  });

  it("shows reconnecting first and only reports disconnected after 3 failures", () => {
    const { result } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];

    act(() => source.onopen?.(new Event("open")));
    act(() => source.onerror?.(new Event("error")));
    expect(result.current.connection).toBe("reconnecting");

    act(() => source.onerror?.(new Event("error")));
    expect(result.current.connection).toBe("reconnecting");

    act(() => source.onerror?.(new Event("error")));
    expect(result.current.connection).toBe("disconnected");

    act(() => source.emit(tick("AAPL", 192.5, 9)));
    expect(result.current.connection).toBe("connected");
  });

  it("closes the connection on unmount", () => {
    const { unmount } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
  });
});
