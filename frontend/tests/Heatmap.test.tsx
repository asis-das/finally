import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Heatmap } from "@/components/Heatmap";
import { portfolio } from "./fixtures";

describe("Heatmap", () => {
  it("draws one tile per position, sized by weight", () => {
    render(
      <Heatmap positions={portfolio.positions} selected={null} onSelect={vi.fn()} />,
    );

    expect(screen.getByTestId("portfolio-heatmap")).toBeInTheDocument();
    const apple = screen.getByTestId("heatmap-tile-AAPL");
    const nvidia = screen.getByTestId("heatmap-tile-NVDA");

    const area = (element: HTMLElement) =>
      Number.parseFloat(element.style.width) * Number.parseFloat(element.style.height);
    expect(area(apple)).toBeGreaterThan(area(nvidia));
  });

  it("colours winners green and losers red", () => {
    render(
      <Heatmap positions={portfolio.positions} selected={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByTestId("heatmap-tile-AAPL").style.backgroundColor).toContain(
      "--color-up",
    );
    expect(screen.getByTestId("heatmap-tile-NVDA").style.backgroundColor).toContain(
      "--color-down",
    );
  });

  it("selects the ticker behind a tile", () => {
    const onSelect = vi.fn();
    render(
      <Heatmap positions={portfolio.positions} selected={null} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByTestId("heatmap-tile-NVDA"));
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("stays mounted and explains itself with no positions", () => {
    render(<Heatmap positions={[]} selected={null} onSelect={vi.fn()} />);
    expect(screen.getByTestId("portfolio-heatmap")).toBeInTheDocument();
    expect(screen.getByText(/No positions yet/i)).toBeInTheDocument();
  });
});
