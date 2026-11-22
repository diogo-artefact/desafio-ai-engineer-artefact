import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import type { TraceEntry } from "../types/api";

export interface DisplayTraceStep {
  id: string;
  type: "thinking" | "tool";
  label: string;
  status: "running" | "done";
  detailLines: string[];
  startedAt?: number;
  durationMs?: number;
}

function formatArgsHint(args: Record<string, unknown>): string | null {
  const entries = Object.entries(args).filter(
    ([, value]) => value !== null && value !== undefined && String(value).trim() !== "",
  );
  if (entries.length === 0) {
    return null;
  }
  return entries
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

export function traceEntriesToSteps(trace: TraceEntry[], prefix: string): DisplayTraceStep[] {
  return trace.map((entry, index) => {
    if (entry.type === "thinking") {
      const text = entry.content.trim();
      return {
        id: `${prefix}-t-${index}`,
        type: "thinking",
        label: entry.label || "Pensou",
        status: "done",
        detailLines: text ? [text] : [],
        durationMs: entry.duration_ms,
      };
    }

    const lines: string[] = [];
    const argsLine = formatArgsHint(entry.args);
    if (argsLine) {
      lines.push(`Consulta: ${argsLine}`);
    }
    if (entry.summary) {
      lines.push(`Retorno: ${entry.summary}`);
    }
    return {
      id: `${prefix}-tool-${index}`,
      type: "tool",
      label: entry.label,
      status: "done",
      detailLines: lines,
      durationMs: entry.duration_ms,
    };
  });
}

function formatDuration(ms?: number): string | null {
  if (ms === undefined || ms < 100) {
    return null;
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  const seconds = ms / 1000;
  return seconds >= 10 ? `${Math.round(seconds)}s` : `${seconds.toFixed(1)}s`;
}

function LiveTimer({ startedAt }: { startedAt: number }) {
  const [elapsedSec, setElapsedSec] = useState(() =>
    Math.max(0, Math.floor((Date.now() - startedAt) / 1000)),
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsedSec(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 500);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  return (
    <span className="tabular-nums text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
      {elapsedSec}s
    </span>
  );
}

interface TraceStepsProps {
  steps: DisplayTraceStep[];
}

export function TraceSteps({ steps }: TraceStepsProps) {
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

  if (steps.length === 0) {
    return null;
  }

  function toggleStep(stepId: string): void {
    setExpandedIds((prev) => ({ ...prev, [stepId]: !prev[stepId] }));
  }

  return (
    <div className="flex flex-col gap-2">
      {steps.map((step) => {
        const hasDetails = step.detailLines.length > 0;
        const expanded = Boolean(expandedIds[step.id]);
        const durationLabel = formatDuration(step.durationMs);

        return (
          <div key={step.id} className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
              {hasDetails ? (
                <button
                  type="button"
                  onClick={() => toggleStep(step.id)}
                  className={`group flex items-center gap-1 border-0 bg-transparent p-0 text-left text-[14px] leading-[140%] transition-colors ${
                    expanded
                      ? "font-medium text-[var(--color-ink-primary)]"
                      : "font-normal text-[var(--color-ink-secondary)] hover:text-[var(--color-ink-primary)]"
                  }`}
                >
                  <span>{step.label}</span>
                  <ChevronDown
                    size={14}
                    strokeWidth={1.5}
                    className={`shrink-0 text-[var(--color-ink-muted)] transition-transform ${
                      expanded ? "rotate-180 opacity-100" : "opacity-0 group-hover:opacity-100"
                    }`}
                  />
                </button>
              ) : (
                <span className="text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                  {step.label}
                </span>
              )}

              {step.status === "running" && step.startedAt !== undefined ? (
                <LiveTimer startedAt={step.startedAt} />
              ) : expanded && durationLabel ? (
                <span className="tabular-nums text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
                  {durationLabel}
                </span>
              ) : null}
            </div>

            {expanded && hasDetails && (
              <div className="flex flex-col gap-1 border-l-2 border-[var(--color-border-strong)] pl-4">
                {step.detailLines.map((line, index) => (
                  <p
                    key={`${step.id}-d-${index}`}
                    className="m-0 whitespace-pre-wrap text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]"
                  >
                    {line}
                  </p>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
