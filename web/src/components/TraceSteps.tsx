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

function buildSummaryLabel(steps: DisplayTraceStep[]): string {
  const runningStep = [...steps].reverse().find((step) => step.status === "running");
  if (runningStep) {
    return runningStep.label;
  }

  const thinkingCount = steps.filter((step) => step.type === "thinking").length;
  const toolCount = steps.filter((step) => step.type === "tool").length;

  if (thinkingCount > 0 && toolCount > 0) {
    const suffix = toolCount === 1 ? "consulta" : "consultas";
    return `Pensou · ${toolCount} ${suffix}`;
  }
  if (toolCount > 0) {
    const suffix = toolCount === 1 ? "consulta" : "consultas";
    return `${toolCount} ${suffix}`;
  }
  return "Pensou";
}

interface TraceStepsProps {
  steps: DisplayTraceStep[];
}

export function TraceSteps({ steps }: TraceStepsProps) {
  const [open, setOpen] = useState(false);

  if (steps.length === 0) {
    return null;
  }

  const isRunning = steps.some((step) => step.status === "running");
  const firstStartedAt = steps.find((step) => step.startedAt !== undefined)?.startedAt;
  const totalDurationMs = steps.reduce((acc, step) => acc + (step.durationMs ?? 0), 0);
  const totalDurationLabel = formatDuration(totalDurationMs);
  const summaryLabel = buildSummaryLabel(steps);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
          className={`flex items-center gap-1.5 border-0 bg-transparent p-0 text-left text-[14px] leading-[140%] transition-colors ${
            open
              ? "font-medium text-[var(--color-ink-primary)]"
              : "font-normal text-[var(--color-ink-secondary)] hover:text-[var(--color-ink-primary)]"
          }`}
        >
          <span>{summaryLabel}</span>
          <ChevronDown
            size={14}
            strokeWidth={1.5}
            className={`shrink-0 text-[var(--color-ink-muted)] transition-transform ${
              open ? "rotate-180" : ""
            }`}
          />
        </button>

        {isRunning && firstStartedAt !== undefined ? (
          <LiveTimer startedAt={firstStartedAt} />
        ) : totalDurationLabel ? (
          <span className="tabular-nums text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
            {totalDurationLabel}
          </span>
        ) : null}
      </div>

      {open && (
        <div className="flex flex-col gap-3 border-l-2 border-[var(--color-border-strong)] pl-4">
          {steps.map((step) => {
            const durationLabel = formatDuration(step.durationMs);
            return (
              <div key={step.id} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[13px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                    {step.label}
                  </span>
                  {step.status === "running" && step.startedAt !== undefined ? (
                    <LiveTimer startedAt={step.startedAt} />
                  ) : durationLabel ? (
                    <span className="tabular-nums shrink-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
                      {durationLabel}
                    </span>
                  ) : null}
                </div>
                {step.detailLines.map((line, index) => (
                  <p
                    key={`${step.id}-d-${index}`}
                    className="m-0 whitespace-pre-wrap text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]"
                  >
                    {line}
                  </p>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
