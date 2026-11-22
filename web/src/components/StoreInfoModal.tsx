import { X } from "lucide-react";
import { useEffect } from "react";

import type { StoreInfo } from "../types/api";

interface StoreInfoModalProps {
  open: boolean;
  store: StoreInfo | null;
  onClose: () => void;
}

const DEFAULT_POLICIES = [
  {
    title: "Pagamento",
    detail:
      "PIX com 5% à vista (não acumula com promoções) e cartão em até 12x sem juros.",
  },
  {
    title: "Entregas",
    detail:
      "Frete grátis em Campo Grande acima de R$ 500,00; outras cidades via Correios ou Jadlog.",
  },
  {
    title: "Devoluções e LGPD",
    detail:
      "Arrependimento em 7 dias corridos; consulta de pedidos com verificação em 2 fatores.",
  },
];

function formatHoursStatus(store: StoreInfo | null): { open: boolean; label: string } | null {
  if (!store) {
    return null;
  }
  if (store.hours.is_open) {
    const closingHour = store.hours.weekday_pt.toLowerCase().includes("sábado") ? "13:00" : "18:00";
    return { open: true, label: `Aberta agora · até ${closingHour}` };
  }
  const suffix = store.hours.next_opening ? ` · abre ${store.hours.next_opening}` : "";
  return { open: false, label: `Fechada agora${suffix}` };
}

export function StoreInfoModal({ open, store, onClose }: StoreInfoModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  const hoursBadge = formatHoursStatus(store);
  const address = store
    ? store.address.replace(" — ", " · ").replace(", CEP 79202-333", "")
    : "Rua 14 de Maio, 3200 · Centro, Campo Grande - MS";
  const phones = store
    ? `${store.phone_primary} · ${store.phone_whatsapp_manual}`
    : "(67) 3341-4444 · (67) 3321-4500";
  const email = store ? store.email : "contato@emporiodamusica.com.br";
  const policies =
    store && store.policies_highlights.length > 0 ? store.policies_highlights : DEFAULT_POLICIES;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="store-info-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#1111113D] p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-[560px] flex-col gap-6 overflow-y-auto rounded-[16px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <h2
                id="store-info-title"
                className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]"
              >
                Sobre a loja
              </h2>
              {hoursBadge && (
                <div className="flex items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      hoursBadge.open
                        ? "bg-[var(--color-status-success)]"
                        : "bg-[var(--color-ink-muted)]"
                    }`}
                  />
                  <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                    {hoursBadge.label}
                  </span>
                </div>
              )}
            </div>
            <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              Instrumentos musicais em Campo Grande desde 2008. Não vendemos acessórios.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] border-0 bg-transparent text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>

        <dl className="m-0 flex w-full flex-col border-t border-[var(--color-border-default)]">
          <div className="flex flex-col justify-between gap-1 border-b border-[var(--color-border-default)] py-2.5 sm:min-h-10 sm:flex-row sm:items-baseline sm:gap-4">
            <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              Endereço
            </dt>
            <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
              {address}
            </dd>
          </div>

          <div className="flex flex-col justify-between gap-1 border-b border-[var(--color-border-default)] py-2.5 sm:min-h-10 sm:flex-row sm:items-baseline sm:gap-4">
            <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              Horário
            </dt>
            <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
              Seg a Sex 09:00–18:00 · Sáb 09:00–13:00
            </dd>
          </div>

          <div className="flex flex-col justify-between gap-1 border-b border-[var(--color-border-default)] py-2.5 sm:min-h-10 sm:flex-row sm:items-baseline sm:gap-4">
            <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              Telefone e WhatsApp
            </dt>
            <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
              {phones}
            </dd>
          </div>

          <div className="flex flex-col justify-between gap-1 border-b border-[var(--color-border-default)] py-2.5 sm:min-h-10 sm:flex-row sm:items-baseline sm:gap-4">
            <dt className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              E-mail
            </dt>
            <dd className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
              {email}
            </dd>
          </div>
        </dl>

        <section className="flex flex-col gap-2">
          <h3 className="m-0 text-[12px] font-medium leading-[140%] text-[var(--color-ink-muted)]">
            Políticas em resumo
          </h3>
          <div className="flex flex-col gap-2">
            {policies.map((item) => (
              <p
                key={item.title}
                className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]"
              >
                <span className="font-medium text-[var(--color-ink-primary)]">{item.title}.</span>{" "}
                {item.detail}
              </p>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
