import { Info, LogOut, PanelLeft, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";

import { groupSessionsByRecency } from "../lib/dates";
import type { AuthUser, SessionSummary } from "../types/api";

export type AppView = "chat" | "settings";

interface SidebarProps {
  user: AuthUser;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  loadingTitleSessionId?: string | null;
  activeView: AppView;
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
  onNewChat: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onOpenStoreInfo: () => void;
  onOpenSettings: () => void;
  onLogout: () => void;
}

interface SidebarContentProps extends Omit<SidebarProps, "collapsed" | "mobileOpen"> {
  isMobileDrawer: boolean;
}

function SessionRow({
  session,
  active,
  loadingTitle,
  onSelect,
  onDelete,
}: {
  session: SessionSummary;
  active: boolean;
  loadingTitle: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`group flex h-8 items-center rounded-[8px] transition-colors ${
        active
          ? "bg-[var(--color-bg-hover)] text-[var(--color-ink-primary)]"
          : "text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        className={`flex h-full min-w-0 flex-1 items-center border-0 bg-transparent px-2 text-left text-[14px] leading-[140%] ${
          active
            ? "font-medium text-[var(--color-ink-primary)]"
            : "font-normal text-[var(--color-ink-secondary)] group-hover:text-[var(--color-ink-primary)]"
        }`}
      >
        {loadingTitle ? (
          <span
            aria-label="Gerando título da conversa"
            className="block h-3 w-32 animate-pulse rounded-[6px] bg-[var(--color-border-strong)]"
          />
        ) : (
          <span className="truncate">{session.title || "Nova conversa"}</span>
        )}
      </button>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onDelete();
        }}
        aria-label={`Excluir conversa ${session.title || "atual"}`}
        className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border-0 bg-transparent text-[var(--color-ink-muted)] opacity-0 transition-opacity hover:text-[var(--color-status-danger)] focus:opacity-100 group-hover:opacity-100"
      >
        <Trash2 size={14} strokeWidth={1.5} />
      </button>
    </div>
  );
}

function SidebarContent({
  user,
  sessions,
  activeSessionId,
  loadingTitleSessionId,
  activeView,
  isMobileDrawer,
  onToggleCollapse,
  onCloseMobile,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onOpenStoreInfo,
  onOpenSettings,
  onLogout,
}: SidebarContentProps) {
  const { today, earlier } = groupSessionsByRecency(sessions);

  function wrapMobileClose(fn: () => void): () => void {
    return () => {
      fn();
      if (isMobileDrawer) {
        onCloseMobile();
      }
    };
  }

  return (
    <aside className="flex h-full w-[var(--container-sidebar)] shrink-0 flex-col justify-between border-r border-[var(--color-border-default)] bg-[var(--color-bg-subtle)] p-4">
      <div className="flex min-h-0 flex-1 flex-col gap-6">
        <div className="flex h-8 shrink-0 items-center justify-between px-2">
          <span className="w-fit whitespace-nowrap text-[16px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
            Empório da Música
          </span>
          <button
            type="button"
            onClick={isMobileDrawer ? onCloseMobile : onToggleCollapse}
            aria-label={isMobileDrawer ? "Fechar menu" : "Recolher barra lateral"}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border-0 bg-transparent text-[var(--color-ink-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
          >
            {isMobileDrawer ? (
              <X size={16} strokeWidth={1.5} />
            ) : (
              <PanelLeft size={16} strokeWidth={1.5} />
            )}
          </button>
        </div>

        <button
          type="button"
          onClick={wrapMobileClose(onNewChat)}
          className="flex h-8 shrink-0 items-center gap-2 rounded-[8px] border-0 bg-transparent px-2 text-left text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
        >
          <Plus size={16} strokeWidth={1.5} className="shrink-0" />
          <span>Nova conversa</span>
        </button>

        <nav
          aria-label="Conversas"
          className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto"
        >
          {sessions.length === 0 ? (
            <p className="m-0 px-2 text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
              Nenhuma conversa ainda
            </p>
          ) : (
            <>
              {today.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="px-2 text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
                    Hoje
                  </span>
                  {today.map((session) => (
                    <SessionRow
                      key={session.session_id}
                      session={session}
                      active={activeView === "chat" && activeSessionId === session.session_id}
                      loadingTitle={loadingTitleSessionId === session.session_id}
                      onSelect={wrapMobileClose(() => onSelectSession(session.session_id))}
                      onDelete={() => onDeleteSession(session.session_id)}
                    />
                  ))}
                </div>
              )}

              {earlier.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="px-2 text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
                    Anteriores
                  </span>
                  {earlier.map((session) => (
                    <SessionRow
                      key={session.session_id}
                      session={session}
                      active={activeView === "chat" && activeSessionId === session.session_id}
                      loadingTitle={loadingTitleSessionId === session.session_id}
                      onSelect={wrapMobileClose(() => onSelectSession(session.session_id))}
                      onDelete={() => onDeleteSession(session.session_id)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </nav>
      </div>

      <div className="flex shrink-0 flex-col gap-1 border-t border-[var(--color-border-default)] pt-4">
        <button
          type="button"
          onClick={wrapMobileClose(onOpenStoreInfo)}
          className="flex h-8 w-full items-center gap-2 rounded-[8px] border-0 bg-transparent px-2 text-left text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
        >
          <Info size={16} strokeWidth={1.5} className="shrink-0 text-[var(--color-ink-muted)]" />
          <span>Sobre a loja</span>
        </button>

        {user.role === "admin" && (
          <button
            type="button"
            onClick={wrapMobileClose(onOpenSettings)}
            className={`flex h-8 w-full items-center gap-2 rounded-[8px] border-0 px-2 text-left text-[14px] leading-[140%] transition-colors ${
              activeView === "settings"
                ? "bg-[var(--color-bg-hover)] font-medium text-[var(--color-ink-primary)]"
                : "bg-transparent font-normal text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
            }`}
          >
            <SlidersHorizontal
              size={16}
              strokeWidth={1.5}
              className={`shrink-0 ${
                activeView === "settings"
                  ? "text-[var(--color-ink-primary)]"
                  : "text-[var(--color-ink-muted)]"
              }`}
            />
            <span>Ajustes</span>
          </button>
        )}

        <button
          type="button"
          onClick={wrapMobileClose(onLogout)}
          className="flex h-8 w-full items-center gap-2 rounded-[8px] border-0 bg-transparent px-2 text-left text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
        >
          <LogOut size={16} strokeWidth={1.5} className="shrink-0" />
          <span>Sair</span>
        </button>
      </div>
    </aside>
  );
}

export function Sidebar(props: SidebarProps) {
  return (
    <>
      {!props.collapsed && (
        <div className="hidden h-full md:block">
          <SidebarContent {...props} isMobileDrawer={false} />
        </div>
      )}

      {props.mobileOpen && (
        <div
          className="fixed inset-0 z-40 flex bg-[#1111113D] md:hidden"
          onClick={props.onCloseMobile}
        >
          <div className="h-full" onClick={(event) => event.stopPropagation()}>
            <SidebarContent {...props} isMobileDrawer={true} />
          </div>
        </div>
      )}
    </>
  );
}
