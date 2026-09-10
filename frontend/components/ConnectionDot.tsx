import type { ConnectionState } from "@/lib/types";

const LABEL: Record<ConnectionState, string> = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
};

const TONE: Record<ConnectionState, string> = {
  connected: "bg-up",
  reconnecting: "bg-accent",
  disconnected: "bg-down",
};

export function ConnectionDot({ state }: { state: ConnectionState }) {
  return (
    <span
      data-testid="connection-status"
      data-status={state}
      title={LABEL[state]}
      className="flex items-center gap-1.5 text-dim"
    >
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${TONE[state]} ${
          state === "connected" ? "dot-live" : ""
        }`}
      />
      <span className="col-head hidden sm:inline">{LABEL[state]}</span>
    </span>
  );
}
