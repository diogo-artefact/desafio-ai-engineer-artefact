interface ErrorCalloutProps {
  statusCode: number;
  message: string;
  onRetry: () => void;
  onEdit: () => void;
}

function titleForStatus(statusCode: number): string {
  if (statusCode === 503 || statusCode === 429) {
    return "Modelo com alta demanda temporária";
  }
  return "Não foi possível concluir a resposta";
}

export function ErrorCallout({ statusCode, message, onRetry, onEdit }: ErrorCalloutProps) {
  return (
    <div
      role="alert"
      className="flex gap-4 rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-subtle)] p-4"
    >
      <div className="w-0.5 shrink-0 rounded-[2px] bg-[var(--color-status-danger)]" />
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              {titleForStatus(statusCode)}
            </span>
            {statusCode > 0 && (
              <span className="tabular-nums shrink-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
                HTTP {statusCode}
              </span>
            )}
          </div>
          <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
            {message}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="flex h-8 items-center justify-center rounded-full border-0 bg-[var(--color-accent-primary)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-inverse)] hover:opacity-90"
          >
            Tentar novamente
          </button>
          <button
            type="button"
            onClick={onEdit}
            className="flex h-8 items-center justify-center rounded-full border-0 bg-[var(--color-bg-hover)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-primary)] hover:opacity-80"
          >
            Editar pergunta
          </button>
        </div>
      </div>
    </div>
  );
}
