import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  placeholder: string;
  streaming: boolean;
  disabled?: boolean;
  large?: boolean;
  focusSignal?: number;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
}

export function ChatComposer({
  value,
  placeholder,
  streaming,
  disabled = false,
  large = false,
  focusSignal = 0,
  onChange,
  onSubmit,
  onStop,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    const minHeight = large ? 48 : 24;
    const maxHeight = 160;
    el.style.height = `${Math.min(maxHeight, Math.max(minHeight, el.scrollHeight))}px`;
  }, [value, large]);

  useEffect(() => {
    if (focusSignal > 0) {
      textareaRef.current?.focus();
    }
  }, [focusSignal]);

  const canSend = value.trim().length > 0 && !disabled && !streaming;

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSend) {
        onSubmit();
      }
    }
  }

  return (
    <div className="flex w-full flex-col gap-4 rounded-[16px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] p-4 focus-within:border-[var(--color-ink-primary)]">
      <textarea
        ref={textareaRef}
        rows={large ? 2 : 1}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        className="w-full resize-none border-0 bg-transparent p-0 text-[16px] font-normal leading-[130%] text-[var(--color-ink-primary)] placeholder:text-[var(--color-ink-muted)] focus:outline-none disabled:opacity-45"
      />

      <div className="flex items-center justify-end gap-2">
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Interromper resposta"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-0 bg-[var(--color-accent-primary)] text-[var(--color-ink-inverse)] hover:opacity-90"
          >
            <Square size={12} fill="currentColor" strokeWidth={0} />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            aria-label="Enviar mensagem"
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-0 transition-opacity ${
              canSend
                ? "bg-[var(--color-accent-primary)] text-[var(--color-ink-inverse)] hover:opacity-90"
                : "bg-[var(--color-bg-hover)] text-[var(--color-ink-secondary)]"
            }`}
          >
            <ArrowUp size={16} strokeWidth={1.75} />
          </button>
        )}
      </div>
    </div>
  );
}
