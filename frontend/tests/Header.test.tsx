import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Header } from "@/components/Header";
import type { ConnectionState } from "@/lib/types";

function renderHeader(connection: ConnectionState = "connected") {
  return render(
    <Header
      totalValue={10472.8}
      cashBalance={8075}
      unrealizedPnl={-2.2}
      unrealizedPnlPercent={-0.09}
      connection={connection}
    />,
  );
}

describe("Header", () => {
  it("shows the live total and cash", () => {
    renderHeader();
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,472.80");
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$8,075.00");
  });

  it("reports the stream state on the connection dot", () => {
    const states: ConnectionState[] = ["connected", "reconnecting", "disconnected"];
    for (const state of states) {
      const { unmount } = renderHeader(state);
      expect(screen.getByTestId("connection-status")).toHaveAttribute(
        "data-status",
        state,
      );
      unmount();
    }
  });

  it("signs the unrealized P&L", () => {
    renderHeader();
    expect(screen.getByText("-$2.20")).toBeInTheDocument();
    expect(screen.getByText("-0.09%")).toBeInTheDocument();
  });
});
