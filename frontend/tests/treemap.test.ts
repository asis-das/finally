import { describe, expect, it } from "vitest";
import { squarify } from "@/lib/treemap";

const entries = [
  { value: 50, item: "A" },
  { value: 30, item: "B" },
  { value: 15, item: "C" },
  { value: 5, item: "D" },
];

describe("squarify", () => {
  it("tiles every positive entry", () => {
    const tiles = squarify(entries, 100, 100);
    expect(tiles.map((tile) => tile.item).sort()).toEqual(["A", "B", "C", "D"]);
  });

  it("fills the box exactly", () => {
    const tiles = squarify(entries, 100, 100);
    const area = tiles.reduce((sum, tile) => sum + tile.w * tile.h, 0);
    expect(area).toBeCloseTo(10000, 5);
  });

  it("keeps every tile inside the box", () => {
    for (const tile of squarify(entries, 100, 100)) {
      expect(tile.x).toBeGreaterThanOrEqual(-1e-9);
      expect(tile.y).toBeGreaterThanOrEqual(-1e-9);
      expect(tile.x + tile.w).toBeLessThanOrEqual(100 + 1e-9);
      expect(tile.y + tile.h).toBeLessThanOrEqual(100 + 1e-9);
    }
  });

  it("gives the biggest holding the biggest tile", () => {
    const tiles = squarify(entries, 100, 100);
    const byItem = Object.fromEntries(tiles.map((tile) => [tile.item, tile.w * tile.h]));
    expect(byItem.A).toBeGreaterThan(byItem.B);
    expect(byItem.B).toBeGreaterThan(byItem.C);
    expect(byItem.C).toBeGreaterThan(byItem.D);
  });

  it("drops zero and negative values and handles an empty set", () => {
    expect(squarify([{ value: 0, item: "A" }], 100, 100)).toEqual([]);
    expect(squarify([], 100, 100)).toEqual([]);
    expect(squarify(entries, 0, 100)).toEqual([]);
  });

  it("handles a single holding", () => {
    const tiles = squarify([{ value: 7, item: "ONLY" }], 100, 100);
    expect(tiles).toHaveLength(1);
    expect(tiles[0].w).toBeCloseTo(100);
    expect(tiles[0].h).toBeCloseTo(100);
  });
});
