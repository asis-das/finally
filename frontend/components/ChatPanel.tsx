"use client";

import { useEffect, useRef, useState } from "react";
import { Panel } from "./Panel";
import { formatClock } from "@/lib/format";
import type { ChatAction, ChatMessage } from "@/lib/types";

interface ChatPanelProps {
  messages: ChatMessage[];
  pending: boolean;
  error: string | null;
  onSend: (message: string) => Promise<void>;
}

function ActionLine({ action }: { action: ChatAction }) {
  const failed = action.status === "failed";
  return (
    <li
      data-testid="chat-action"
      data-status={action.status}
      className={`flex items-start gap-2 border-l-2 py-0.5 pl-2 text-[11.5px] ${
        failed ? "border-l-down text-down" : "border-l-up text-ink/85"
      }`}
    >
      <span className="num shrink-0 font-medium">{action.ticker}</span>
      <span className="min-w-0">{action.detail}</span>
    </li>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const mine = message.role === "user";
  return (
    <div className={`flex flex-col ${mine ? "items-end" : "items-start"}`}>
      <div
        data-testid={mine ? "chat-message-user" : "chat-message-assistant"}
        className={`max-w-[92%] px-2.5 py-1.5 text-[12.5px] leading-relaxed whitespace-pre-wrap ${
          mine
            ? "border border-line-hi bg-raised text-ink"
            : "border-l-2 border-l-primary bg-panel text-ink"
        }`}
      >
        {message.content}
      </div>
      {message.actions && message.actions.length > 0 && (
        <ul className="mt-1 w-full space-y-0.5">
          {message.actions.map((action, index) => (
            <ActionLine key={`${action.ticker}-${index}`} action={action} />
          ))}
        </ul>
      )}
      {message.created_at && (
        <span className="num mt-0.5 text-[10px] text-mute">
          {formatClock(message.created_at)}
        </span>
      )}
    </div>
  );
}

export function ChatPanel({ messages, pending, error, onSend }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, pending]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    await onSend(text);
  }

  return (
    <Panel
      title="FinAlly assistant"
      testId="chat-panel"
      className="border-l border-line"
      bodyClassName="flex flex-col"
    >
      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-2.5 py-3">
        {messages.length === 0 && !pending && (
          <div className="space-y-3 text-[12.5px] text-dim">
            <p>
              Ask about your positions, or hand over an order. The assistant trades
              your simulated account directly.
            </p>
            <ul className="space-y-1 text-mute">
              <li>&ldquo;How concentrated am I?&rdquo;</li>
              <li>&ldquo;Buy 5 NVDA&rdquo;</li>
              <li>&ldquo;Add PYPL to my watchlist&rdquo;</li>
            </ul>
          </div>
        )}

        {messages.map((message) => (
          <Bubble key={message.id} message={message} />
        ))}

        {pending && (
          <div
            data-testid="chat-loading"
            role="status"
            className="flex items-center gap-1.5 pl-1 text-[11.5px] text-dim"
          >
            <span className="size-1.5 animate-pulse rounded-full bg-primary" />
            Thinking
          </div>
        )}

        {error && (
          <p role="alert" className="text-[11.5px] text-down">
            {error}
          </p>
        )}
      </div>

      <form
        onSubmit={submit}
        className="flex shrink-0 gap-1.5 border-t border-line bg-ground/70 p-2"
      >
        <input
          data-testid="chat-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask FinAlly"
          aria-label="Message FinAlly"
          autoComplete="off"
          className="min-w-0 flex-1 border border-line bg-panel px-2 py-1.5 text-[12.5px] placeholder:text-mute focus:border-primary focus:outline-none"
        />
        <button
          type="submit"
          data-testid="chat-send"
          disabled={pending || draft.trim().length === 0}
          className="bg-secondary px-3 text-[12.5px] font-semibold text-white transition-colors hover:brightness-115 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </Panel>
  );
}
