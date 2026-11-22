import { useEffect, useRef, useState } from "react";

import type { AuthUser, ChatMessage } from "../types/api";
import { ChatComposer } from "./ChatComposer";
import { ErrorCallout } from "./ErrorCallout";
import { MarkdownMessage } from "./MarkdownMessage";
import { TraceSteps, traceEntriesToSteps, type DisplayTraceStep } from "./TraceSteps";

export interface ChatTurnError {
  statusCode: number;
  message: string;
  failedPrompt: string;
}

interface ChatViewProps {
  user: AuthUser;
  serviceReady: boolean;
  messages: ChatMessage[];
  loadingSession: boolean;
  streaming: boolean;
  streamingText: string;
  liveSteps: DisplayTraceStep[];
  chatError: ChatTurnError | null;
  draft: string;
  focusSignal: number;
  onDraftChange: (value: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  onRetryError: () => void;
  onEditError: () => void;
  onRetryMessage: (prompt: string) => void;
  onOpenStoreInfo: () => void;
  onOpenSettings: () => void;
}

const STARTER_PROMPTS = [
  "Violões até R$ 1.000",
  "Takamine GD20 no PIX ou parcelado",
  "Troca e devolução",
];

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-label="Carregando resposta">
      <div className="h-3 w-[88%] animate-pulse rounded-[6px] bg-[var(--color-bg-hover)]" />
      <div className="h-3 w-[72%] animate-pulse rounded-[6px] bg-[var(--color-bg-hover)]" />
      <div className="h-3 w-[52%] animate-pulse rounded-[6px] bg-[var(--color-bg-subtle)]" />
    </div>
  );
}

function CopyAction({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      return;
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className="border-0 bg-transparent p-0 text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]"
    >
      {copied ? "Copiado" : "Copiar"}
    </button>
  );
}

export function ChatView({
  user,
  serviceReady,
  messages,
  loadingSession,
  streaming,
  streamingText,
  liveSteps,
  chatError,
  draft,
  focusSignal,
  onDraftChange,
  onSend,
  onStop,
  onRetryError,
  onEditError,
  onRetryMessage,
  onOpenStoreInfo,
  onOpenSettings,
}: ChatViewProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, streamingText, liveSteps.length, chatError]);

  if (user.role === "customer" && !serviceReady) {
    return (
      <main className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 pb-16">
        <div className="flex w-full max-w-[var(--container-chat)] flex-col items-start gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
              Atendimento indisponível
            </h1>
            <p className="m-0 max-w-[540px] text-[16px] font-normal leading-[130%] text-[var(--color-ink-secondary)]">
              Nosso atendimento virtual não está disponível no momento. Entre em contato com a nossa
              equipe pelo telefone (67) 3341-4444 ou pelo e-mail contato@emporiodamusica.com.br.
            </p>
          </div>
          <button
            type="button"
            onClick={onOpenStoreInfo}
            className="flex h-10 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-5 text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)]"
          >
            Sobre a loja
          </button>
        </div>
      </main>
    );
  }

  if (loadingSession) {
    return (
      <main className="flex min-h-0 flex-1 flex-col items-center px-4 pt-8 md:px-8">
        <div className="w-full max-w-[var(--container-chat)]">
          <LoadingSkeleton />
        </div>
      </main>
    );
  }

  const isEmpty = messages.length === 0 && !streaming && !chatError;

  if (isEmpty) {
    return (
      <main className="flex min-h-0 flex-1 flex-col items-center justify-center px-4 pb-16 md:px-8">
        <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="m-0 text-[24px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
              Em que posso ajudar?
            </h1>
            <p className="m-0 text-[16px] font-normal leading-[130%] text-[var(--color-ink-secondary)]">
              Consulte estoque real, condições de PIX e parcelamento, políticas da loja ou seu
              pedido
            </p>
          </div>

          <ChatComposer
            value={draft}
            placeholder="Pergunte sobre instrumentos, preços, entregas ou seu pedido..."
            streaming={streaming}
            large={true}
            focusSignal={focusSignal}
            onChange={onDraftChange}
            onSubmit={() => onSend(draft)}
            onStop={onStop}
          />

          <div className="flex flex-wrap gap-2">
            {STARTER_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => onSend(prompt)}
                className="flex h-8 items-center rounded-[8px] border border-[var(--color-border-default)] bg-[var(--color-bg-canvas)] px-3 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] transition-colors hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-ink-primary)]"
              >
                {prompt}
              </button>
            ))}
          </div>

          {user.role === "admin" && !serviceReady && (
            <p className="m-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
              Base da loja ainda não carregada.{" "}
              <button
                type="button"
                onClick={onOpenSettings}
                className="border-0 bg-transparent p-0 text-[12px] font-medium text-[var(--color-ink-primary)] underline underline-offset-2"
              >
                Abrir Ajustes
              </button>
            </p>
          )}
        </div>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <main className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 py-6 md:px-8 md:py-8">
        <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-6">
          {messages.map((message, index) => {
            if (message.role === "user") {
              return (
                <div
                  key={`${message.id}-${index}`}
                  className="w-full rounded-[12px] bg-[var(--color-bg-hover)] p-4 text-[16px] font-normal leading-[130%] text-[var(--color-ink-primary)]"
                >
                  <p className="m-0 whitespace-pre-wrap">{message.content}</p>
                </div>
              );
            }

            const steps = traceEntriesToSteps(message.trace, `msg-${message.id}-${index}`);
            const previousUserMessage = [...messages.slice(0, index)]
              .reverse()
              .find((item) => item.role === "user");

            return (
              <article key={`${message.id}-${index}`} className="flex flex-col gap-4">
                {steps.length > 0 && <TraceSteps steps={steps} />}
                <MarkdownMessage content={message.content} />
                <div className="flex items-center gap-4 pt-1">
                  <CopyAction text={message.content} />
                  {previousUserMessage && !streaming && (
                    <button
                      type="button"
                      onClick={() => onRetryMessage(previousUserMessage.content)}
                      className="border-0 bg-transparent p-0 text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]"
                    >
                      Tentar novamente
                    </button>
                  )}
                </div>
              </article>
            );
          })}

          {streaming && (
            <div className="flex flex-col gap-4">
              {liveSteps.length > 0 && <TraceSteps steps={liveSteps} />}
              {streamingText ? (
                <MarkdownMessage content={streamingText} />
              ) : (
                <LoadingSkeleton />
              )}
            </div>
          )}

          {chatError && (
            <ErrorCallout
              statusCode={chatError.statusCode}
              message={chatError.message}
              onRetry={onRetryError}
              onEdit={onEditError}
            />
          )}

          <div ref={bottomRef} />
        </div>
      </main>

      <div className="flex shrink-0 justify-center px-4 pb-6 pt-2 md:px-8">
        <div className="w-full max-w-[var(--container-chat)]">
          <ChatComposer
            value={draft}
            placeholder="Faça outra pergunta..."
            streaming={streaming}
            focusSignal={focusSignal}
            onChange={onDraftChange}
            onSubmit={() => onSend(draft)}
            onStop={onStop}
          />
        </div>
      </div>
    </div>
  );
}
