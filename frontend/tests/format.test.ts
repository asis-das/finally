import { describe, expect, it } from "vitest";
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  isValidTicker,
  normalizeTicker,
  toneClass,
} from "@/lib/format";

describe("formatting", () => {
  it("renders money with two decimals and thousands separators", () => {
    expect(formatCurrency(10000)).toBe("$10,000.00");
    expect(formatCurrency(8075)).toBe("$8,075.00");
  });

  it("falls back to an em dash for missing numbers", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
  });

  it("signs P&L explicitly", () => {
    expect(formatSignedCurrency(25)).toBe("+$25.00");
    expect(formatSignedCurrency(-27.2)).toBe("-$27.20");
    expect(formatSignedCurrency(0)).toBe("$0.00");
  });

  it("signs positive percentages and rounds to 2dp", () => {
    expect(formatPercent(1.324)).toBe("+1.32%");
    expect(formatPercent(-5.437)).toBe("-5.44%");
  });

  it("keeps whole share counts bare and trims fractional noise", () => {
    expect(formatQuantity(10)).toBe("10");
    expect(formatQuantity(0.5)).toBe("0.5");
    expect(formatQuantity(1.23456789)).toBe("1.2346");
  });

  it("maps sign to a direction colour", () => {
    expect(toneClass(1)).toBe("text-up");
    expect(toneClass(-1)).toBe("text-down");
    expect(toneClass(0)).toBe("text-dim");
  });

  it("normalises and validates tickers the way the API does", () => {
    expect(normalizeTicker(" pypl ")).toBe("PYPL");
    expect(isValidTicker("brk.b")).toBe(true);
    expect(isValidTicker("VERYLONGTICKER")).toBe(false);
    expect(isValidTicker("A1")).toBe(false);
    expect(isValidTicker("")).toBe(false);
  });
});
