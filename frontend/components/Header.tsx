"use client";

import { ConnectionDot } from "./ConnectionDot";
import { useFlash } from "@/lib/useFlash";
import { formatCurrency, formatPercent, formatSignedCurrency, toneClass } from "@/lib/format";
import type { ConnectionState } from "@/lib/types";

interface HeaderProps {
  totalValue: number;
  cashBalance: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
  connection: ConnectionState;
}

function Readout({
  label,
  children,
  testId,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="col-head mb-1">{label}</span>
      <span data-testid={testId} className={`num ${className}`}>
        {children}
      </span>
    </div>
  );
}

export function Header({
  totalValue,
  cashBalance,
  unrealizedPnl,
  unrealizedPnlPercent,
  connection,
}: HeaderProps) {
  const flash = useFlash(totalValue);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-ground px-4">
      <div className="flex min-w-0 items-center gap-3 sm:gap-5">
        <span className="font-[family-name:var(--font-cond)] text-[17px] leading-none font-semibold tracking-[0.14em] sm:text-[19px] sm:tracking-[0.2em]">
          FIN<span className="text-accent">ALLY</span>
        </span>
        <span className="hidden h-6 w-px bg-line sm:block" />
        <ConnectionDot state={connection} />
      </div>

      <div className="flex shrink-0 items-center gap-4 sm:gap-8">
        <div className="hidden md:block">
          <Readout label="Unrealized" className={`text-[13px] ${toneClass(unrealizedPnl)}`}>
            {formatSignedCurrency(unrealizedPnl)}
            <span className="ml-1.5 text-dim">{formatPercent(unrealizedPnlPercent)}</span>
          </Readout>
        </div>

        <Readout label="Cash" testId="cash-balance" className="text-[13px] text-ink sm:text-[15px]">
          {formatCurrency(cashBalance)}
        </Readout>

        <Readout label="Total value" testId="total-value" className="text-[18px] font-medium sm:text-[22px]">
          <span key={flash.nonce} className={`px-1 ${flash.className}`}>
            {formatCurrency(totalValue)}
          </span>
        </Readout>
      </div>
    </header>
  );
}
