import { Menu, Plus } from "lucide-react";

interface MobileHeaderProps {
  onOpenMenu: () => void;
  onNewChat: () => void;
}

export function MobileHeader({ onOpenMenu, onNewChat }: MobileHeaderProps) {
  return (
    <header className="flex h-12 w-full shrink-0 items-center justify-between border-b border-[var(--color-border-default)] bg-[var(--color-bg-canvas)] px-4 md:hidden">
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Abrir menu"
        className="flex h-8 w-8 items-center justify-center rounded-[8px] border-0 bg-transparent text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)]"
      >
        <Menu size={18} strokeWidth={1.5} />
      </button>

      <span className="text-[16px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
        Empório da Música
      </span>

      <button
        type="button"
        onClick={onNewChat}
        aria-label="Nova conversa"
        className="flex h-8 w-8 items-center justify-center rounded-[8px] border-0 bg-transparent text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)]"
      >
        <Plus size={18} strokeWidth={1.5} />
      </button>
    </header>
  );
}
