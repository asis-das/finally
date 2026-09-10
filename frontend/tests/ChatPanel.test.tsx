import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatPanel } from "@/components/ChatPanel";
import { chatMessages } from "./fixtures";

describe("ChatPanel", () => {
  it("renders user and assistant bubbles with their own hooks", () => {
    render(
      <ChatPanel messages={chatMessages} pending={false} error={null} onSend={vi.fn()} />,
    );

    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
    expect(screen.getByTestId("chat-message-user")).toHaveTextContent(
      "buy me 10 apple shares",
    );
    expect(screen.getByTestId("chat-message-assistant")).toHaveTextContent(
      "Bought 10 AAPL at $192.50",
    );
  });

  it("renders every action's detail inline, marked executed or failed", () => {
    render(
      <ChatPanel messages={chatMessages} pending={false} error={null} onSend={vi.fn()} />,
    );

    const actions = screen.getAllByTestId("chat-action");
    expect(actions).toHaveLength(2);
    expect(actions[0]).toHaveTextContent("Bought 10 AAPL @ $192.50");
    expect(actions[0]).toHaveAttribute("data-status", "executed");
    expect(actions[1]).toHaveTextContent("Ticker PYPL is already on the watchlist");
    expect(actions[1]).toHaveAttribute("data-status", "failed");
  });

  it("shows the loading indicator only while a reply is in flight", () => {
    const { rerender } = render(
      <ChatPanel messages={chatMessages} pending={false} error={null} onSend={vi.fn()} />,
    );
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();

    rerender(
      <ChatPanel messages={chatMessages} pending error={null} onSend={vi.fn()} />,
    );
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
  });

  it("sends the trimmed message and clears the field", async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ChatPanel messages={[]} pending={false} error={null} onSend={onSend} />);

    await user.type(screen.getByTestId("chat-input"), "  buy 5 NVDA  ");
    await user.click(screen.getByTestId("chat-send"));

    expect(onSend).toHaveBeenCalledWith("buy 5 NVDA");
    expect(screen.getByTestId("chat-input")).toHaveValue("");
  });

  it("keeps send disabled while empty or pending", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ChatPanel messages={[]} pending={false} error={null} onSend={vi.fn()} />,
    );
    expect(screen.getByTestId("chat-send")).toBeDisabled();

    await user.type(screen.getByTestId("chat-input"), "hello");
    expect(screen.getByTestId("chat-send")).toBeEnabled();

    rerender(<ChatPanel messages={[]} pending error={null} onSend={vi.fn()} />);
    expect(screen.getByTestId("chat-send")).toBeDisabled();
  });

  it("surfaces a transport failure without losing the conversation", () => {
    render(
      <ChatPanel
        messages={chatMessages}
        pending={false}
        error="The assistant is unreachable"
        onSend={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The assistant is unreachable");
    expect(screen.getByTestId("chat-message-assistant")).toBeInTheDocument();
  });

  it("offers examples before the first message", () => {
    render(<ChatPanel messages={[]} pending={false} error={null} onSend={vi.fn()} />);
    expect(screen.getByText(/Buy 5 NVDA/)).toBeInTheDocument();
  });
});
