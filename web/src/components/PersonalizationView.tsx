import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "../lib/api";
import type { UserMemory } from "../types/api";

interface PersonalizationViewProps {
  token: string;
  onUnauthorized: () => void;
}

const MAX_INSTRUCTIONS_LEN = 500;

const MEMORY_LABELS: Record<string, string> = {
  instrumento_interesse: "Instrumento",
  nivel_musical: "Nível musical",
  cidade_entrega: "Cidade de entrega",
  preferencia_pagamento: "Pagamento",
  preferencia_cordas: "Tipo de cordas",
  orcamento: "Orçamento",
  estilo_musical: "Estilo musical",
  preferencia_marca: "Marca",
};

function labelForKey(factKey: string): string {
  return MEMORY_LABELS[factKey] ?? factKey.replace(/_/g, " ");
}

export function PersonalizationView({ token, onUnauthorized }: PersonalizationViewProps) {
  const [instructions, setInstructions] = useState("");
  const [savedInstructions, setSavedInstructions] = useState("");
  const [memories, setMemories] = useState<UserMemory[]>([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState(false);
  const [instructionsError, setInstructionsError] = useState<string | null>(null);

  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [clearingMemories, setClearingMemories] = useState(false);
  const [memoriesError, setMemoriesError] = useState<string | null>(null);

  const loadPersonalization = useCallback(async () => {
    setLoading(true);
    setInstructionsError(null);
    setMemoriesError(null);
    try {
      const data = await api.getPersonalization(token);
      setInstructions(data.custom_instructions);
      setSavedInstructions(data.custom_instructions);
      setMemories(data.memories);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setInstructionsError(err.detail);
      } else {
        setInstructionsError("Não foi possível carregar suas preferências agora.");
      }
    } finally {
      setLoading(false);
    }
  }, [token, onUnauthorized]);

  useEffect(() => {
    void loadPersonalization();
  }, [loadPersonalization]);

  async function saveInstructions(nextValue: string): Promise<void> {
    if (saving) {
      return;
    }
    setSaving(true);
    setSavedNotice(false);
    setInstructionsError(null);
    try {
      const updated = await api.updatePersonalization(token, nextValue);
      setInstructions(updated.custom_instructions);
      setSavedInstructions(updated.custom_instructions);
      setMemories(updated.memories);
      setSavedNotice(true);
      window.setTimeout(() => setSavedNotice(false), 2500);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setInstructionsError(err.detail);
      } else {
        setInstructionsError("Não foi possível salvar suas instruções agora.");
      }
    } finally {
      setSaving(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void saveInstructions(instructions);
  }

  async function handleDeleteMemory(factKey: string): Promise<void> {
    if (deletingKey !== null || clearingMemories) {
      return;
    }
    setDeletingKey(factKey);
    setMemoriesError(null);
    try {
      await api.deleteMemory(token, factKey);
      setMemories((prev) => prev.filter((item) => item.fact_key !== factKey));
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setMemoriesError(err.detail);
      } else {
        setMemoriesError("Não foi possível remover esta memória.");
      }
    } finally {
      setDeletingKey(null);
    }
  }

  async function handleClearMemories(): Promise<void> {
    if (clearingMemories || deletingKey !== null) {
      return;
    }
    setClearingMemories(true);
    setMemoriesError(null);
    try {
      await api.clearMemories(token);
      setMemories([]);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setMemoriesError(err.detail);
      } else {
        setMemoriesError("Não foi possível limpar suas memórias agora.");
      }
    } finally {
      setClearingMemories(false);
    }
  }

  const isDirty = instructions.trim() !== savedInstructions.trim();

  return (
    <main className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 py-8 md:px-8 md:py-12">
      <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-8">
        <header className="flex flex-col gap-1">
          <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
            Personalização
          </h1>
          <p className="m-0 text-[16px] font-normal leading-[130%] text-[var(--color-ink-secondary)]">
            Ajuste como o assistente escreve para você e gerencie suas preferências lembradas
          </p>
        </header>

        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
              Instruções para o assistente
            </h2>
            <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              Defina preferências de tom, concisão ou formato. Regras da loja, preços e segurança
              LGPD não podem ser alterados por aqui.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <textarea
              value={instructions}
              maxLength={MAX_INSTRUCTIONS_LEN}
              rows={4}
              disabled={loading || saving}
              onChange={(event) => {
                setInstructions(event.target.value);
                setSavedNotice(false);
                if (instructionsError) {
                  setInstructionsError(null);
                }
              }}
              placeholder="Ex.: Prefiro respostas curtas e diretas, sempre destacando madeiras e tipo de corda do instrumento."
              className="min-h-[120px] w-full resize-y rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] p-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-primary)] placeholder:text-[var(--color-ink-muted)] focus:border-[var(--color-ink-primary)] focus:outline-none disabled:opacity-45"
            />

            {instructionsError && (
              <div
                role="alert"
                className="border-l-2 border-[var(--color-status-danger)] py-0.5 pl-3 text-[14px] leading-[140%] text-[var(--color-status-danger)]"
              >
                {instructionsError}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="tabular-nums text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
                  {instructions.length} / {MAX_INSTRUCTIONS_LEN}
                </span>
                {savedNotice && (
                  <span className="text-[12px] font-medium leading-[140%] text-[var(--color-status-success)]">
                    Instruções salvas
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {savedInstructions.length > 0 && (
                  <button
                    type="button"
                    disabled={saving || loading}
                    onClick={() => void saveInstructions("")}
                    className="flex h-9 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)] disabled:opacity-45"
                  >
                    Limpar
                  </button>
                )}
                <button
                  type="submit"
                  disabled={saving || loading || !isDirty}
                  className="flex h-9 items-center justify-center rounded-full border-0 bg-[var(--color-accent-primary)] px-4 text-[14px] font-medium leading-[140%] text-[var(--color-ink-inverse)] transition-opacity hover:opacity-90 disabled:opacity-45"
                >
                  {saving ? "Validando..." : "Salvar instruções"}
                </button>
              </div>
            </div>
          </form>
        </section>

        <section className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h2 className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
                Memórias salvas
              </h2>
              <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                Preferências lembradas entre suas conversas. Dados pessoais sensíveis e pedidos
                nunca são salvos aqui.
              </p>
            </div>

            {memories.length > 0 && (
              <button
                type="button"
                disabled={clearingMemories || deletingKey !== null}
                onClick={() => void handleClearMemories()}
                className="shrink-0 border-0 bg-transparent p-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)] hover:text-[var(--color-status-danger)] disabled:opacity-45"
              >
                {clearingMemories ? "Limpando..." : "Limpar tudo"}
              </button>
            )}
          </div>

          {memoriesError && (
            <p
              role="alert"
              className="m-0 border-l-2 border-[var(--color-status-danger)] pl-3 text-[14px] leading-[140%] text-[var(--color-status-danger)]"
            >
              {memoriesError}
            </p>
          )}

          {loading ? (
            <div className="flex flex-col gap-3 py-2" aria-label="Carregando memórias">
              <div className="h-3 w-48 animate-pulse rounded-[6px] bg-[var(--color-bg-hover)]" />
              <div className="h-3 w-36 animate-pulse rounded-[6px] bg-[var(--color-bg-subtle)]" />
            </div>
          ) : memories.length === 0 ? (
            <p className="m-0 border-t border-[var(--color-border-default)] pt-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              Nenhuma memória salva ainda. Quando você mencionar preferências como instrumento,
              nível musical, tipo de cordas ou cidade de entrega, elas aparecem aqui.
            </p>
          ) : (
            <div className="flex w-full flex-col border-t border-[var(--color-border-default)]">
              {memories.map((memory) => {
                const busy = deletingKey === memory.fact_key || clearingMemories;
                return (
                  <div
                    key={memory.fact_key}
                    className="flex items-center justify-between gap-4 border-b border-[var(--color-border-default)] py-3"
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                      <span className="shrink-0 text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                        {labelForKey(memory.fact_key)}
                      </span>
                      <span className="text-[14px] font-normal leading-[140%] text-[var(--color-ink-body)] sm:text-right">
                        {memory.content}
                      </span>
                    </div>

                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleDeleteMemory(memory.fact_key)}
                      aria-label={`Remover memória ${labelForKey(memory.fact_key)}`}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] border-0 bg-transparent text-[var(--color-ink-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-status-danger)] disabled:opacity-45"
                    >
                      <Trash2 size={14} strokeWidth={1.5} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
