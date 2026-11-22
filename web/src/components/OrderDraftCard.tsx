import { useEffect, useRef, useState } from "react";

import type { OrderDraft } from "../types/api";

interface OrderDraftCardProps {
  draft: OrderDraft;
  busy: boolean;
  error?: string | null;
  onConfirm: (draftId: string) => void;
  onCancel: (draftId: string) => void;
  onDeliveryDue: () => void;
}

function formatBrl(value: number): string {
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function computeRemainingSeconds(deliverAt: string | null): number {
  if (!deliverAt) {
    return 0;
  }
  const targetMs = Date.parse(deliverAt);
  if (Number.isNaN(targetMs)) {
    return 0;
  }
  return Math.max(0, Math.ceil((targetMs - Date.now()) / 1000));
}

function formatCountdown(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins <= 0) {
    return `${secs}s`;
  }
  return `${mins}m ${String(secs).padStart(2, "0")}s`;
}

export function OrderDraftCard({
  draft,
  busy,
  error,
  onConfirm,
  onCancel,
  onDeliveryDue,
}: OrderDraftCardProps) {
  const [remainingSec, setRemainingSec] = useState<number>(() =>
    draft.status === "confirmed" ? computeRemainingSeconds(draft.deliver_at) : 0,
  );
  const notifiedDueRef = useRef(false);

  useEffect(() => {
    if (draft.status !== "confirmed" || !draft.deliver_at) {
      notifiedDueRef.current = false;
      setRemainingSec(0);
      return;
    }

    const update = () => {
      const next = computeRemainingSeconds(draft.deliver_at);
      setRemainingSec(next);
      if (next === 0 && !notifiedDueRef.current) {
        notifiedDueRef.current = true;
        onDeliveryDue();
      }
    };

    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [draft.status, draft.deliver_at, onDeliveryDue]);

  const title =
    draft.status === "pending"
      ? "Confirmar pedido"
      : draft.status === "cancelled"
        ? "Pedido cancelado"
        : `Pedido #${draft.order_id ?? ""}`;

  return (
    <section
      aria-label={title}
      className="flex w-full flex-col gap-4 rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-subtle)] p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className={`text-[14px] font-medium leading-[140%] ${
            draft.status === "cancelled"
              ? "text-[var(--color-ink-muted)]"
              : "text-[var(--color-ink-primary)]"
          }`}
        >
          {title}
        </span>

        {draft.status === "pending" && (
          <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
            Aguardando confirmação
          </span>
        )}

        {draft.status === "confirmed" && (
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-ink-primary)]" />
            <span className="tabular-nums text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              {remainingSec > 0
                ? `Confirmado · entrega em ${formatCountdown(remainingSec)}`
                : "Atualizando entrega..."}
            </span>
          </div>
        )}

        {draft.status === "delivered" && (
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-status-success)]" />
            <span className="text-[12px] font-medium leading-[140%] text-[var(--color-status-success)]">
              Entregue
            </span>
          </div>
        )}

        {draft.status === "cancelled" && (
          <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
            Cancelado
          </span>
        )}
      </div>

      <dl className="m-0 flex w-full flex-col border-t border-[var(--color-border-default)]">
        <div className="flex flex-col justify-between gap-0.5 border-b border-[var(--color-border-default)] py-2 sm:flex-row sm:items-baseline sm:gap-4">
          <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            Instrumento
          </dt>
          <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
            {draft.quantity}x {draft.product_name}
          </dd>
        </div>

        <div className="flex flex-col justify-between gap-0.5 border-b border-[var(--color-border-default)] py-2 sm:flex-row sm:items-baseline sm:gap-4">
          <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            Pagamento
          </dt>
          <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
            {draft.payment_label}
          </dd>
        </div>

        <div className="flex flex-col justify-between gap-0.5 border-b border-[var(--color-border-default)] py-2 sm:flex-row sm:items-baseline sm:gap-4">
          <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            Entrega
          </dt>
          <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
            {draft.shipping_note}
          </dd>
        </div>

        {draft.tracking_code && (
          <div className="flex flex-col justify-between gap-0.5 border-b border-[var(--color-border-default)] py-2 sm:flex-row sm:items-baseline sm:gap-4">
            <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              Rastreio
            </dt>
            <dd className="m-0 font-mono text-[13px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
              {draft.tracking_code}
            </dd>
          </div>
        )}

        <div className="flex items-baseline justify-between gap-4 border-b border-[var(--color-border-default)] py-2">
          <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            Total
          </dt>
          <dd className="m-0 tabular-nums text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            {formatBrl(draft.total_brl)}
          </dd>
        </div>
      </dl>

      {error && (
        <p
          role="alert"
          className="m-0 border-l-2 border-[var(--color-status-danger)] pl-3 text-[13px] leading-[140%] text-[var(--color-status-danger)]"
        >
          {error}
        </p>
      )}

      {draft.status === "pending" && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
            Para teste, o pedido será marcado como entregue em 5 minutos após confirmar.
          </span>

          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => onCancel(draft.draft_id)}
              className="flex h-9 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)] disabled:opacity-45"
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onConfirm(draft.draft_id)}
              className="flex h-9 items-center justify-center rounded-full border-0 bg-[var(--color-accent-primary)] px-4 text-[14px] font-medium leading-[140%] text-[var(--color-ink-inverse)] transition-opacity hover:opacity-90 disabled:opacity-45"
            >
              {busy ? "Confirmando..." : "Confirmar pedido"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
