import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  /** Set on the scrolling body, not the frame. */
  bodyClassName?: string;
  className?: string;
  testId?: string;
}

/**
 * A workspace pane. Panels carry no border of their own — the workspace grid is
 * a 1px rule that shows through the gaps, so every pane shares its edges.
 */
export function Panel({
  title,
  aside,
  children,
  bodyClassName = "",
  className = "",
  testId,
}: PanelProps) {
  return (
    <section
      className={`flex h-full min-h-0 min-w-0 flex-col bg-panel ${className}`}
      data-testid={testId}
    >
      <header className="flex h-7 shrink-0 items-center justify-between gap-2 border-b border-line bg-ground px-2.5">
        <h2 className="panel-title">{title}</h2>
        {aside}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
