import { PanelLeft } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AuthScreen } from "./components/AuthScreen";
import { MobileHeader } from "./components/MobileHeader";
import { Sidebar, type AppView } from "./components/Sidebar";
import { StoreInfoModal } from "./components/StoreInfoModal";
import { ApiError, api } from "./lib/api";
import { clearAuthToken, readAuthToken, writeAuthToken } from "./lib/storage";
import type { AuthResponse, AuthUser, SessionSummary, StoreInfo } from "./types/api";

export function App() {
  const [token, setToken] = useState<string | null>(() => readAuthToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState<boolean>(() => Boolean(readAuthToken()));

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<AppView>("chat");
  const [serviceReady, setServiceReady] = useState<boolean>(true);
  const [storeInfo, setStoreInfo] = useState<StoreInfo | null>(null);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [storeModalOpen, setStoreModalOpen] = useState(false);

  const handleLogout = useCallback(() => {
    clearAuthToken();
    setToken(null);
    setUser(null);
    setSessions([]);
    setActiveSessionId(null);
    setActiveView("chat");
    setMobileMenuOpen(false);
    setStoreModalOpen(false);
  }, []);

  useEffect(() => {
    if (!token) {
      setCheckingAuth(false);
      return;
    }

    let cancelled = false;
    setCheckingAuth(true);

    api
      .me(token)
      .then((authenticatedUser) => {
        if (!cancelled) {
          setUser(authenticatedUser);
        }
      })
      .catch(() => {
        if (!cancelled) {
          handleLogout();
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingAuth(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token, handleLogout]);

  const refreshWorkspace = useCallback(
    async (authToken: string) => {
      try {
        const [health, sessionList, store] = await Promise.all([
          api.health(),
          api.listSessions(authToken),
          api.storeInfo(),
        ]);
        setServiceReady(health.ready);
        setSessions(sessionList);
        setStoreInfo(store);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          handleLogout();
        }
      }
    },
    [handleLogout],
  );

  useEffect(() => {
    if (!token || !user) {
      return;
    }
    void refreshWorkspace(token);
  }, [token, user, refreshWorkspace]);

  function handleAuthenticated(auth: AuthResponse): void {
    writeAuthToken(auth.token);
    setToken(auth.token);
    setUser(auth.user);
    setActiveView("chat");
    setActiveSessionId(null);
  }

  function handleNewChat(): void {
    setActiveSessionId(null);
    setActiveView("chat");
  }

  function handleSelectSession(sessionId: string): void {
    setActiveSessionId(sessionId);
    setActiveView("chat");
  }

  async function handleDeleteSession(sessionId: string): Promise<void> {
    if (!token) {
      return;
    }
    try {
      await api.deleteSession(token, sessionId);
      setSessions((prev) => prev.filter((item) => item.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleLogout();
      }
    }
  }

  function handleOpenSettings(): void {
    if (user?.role !== "admin") {
      return;
    }
    setActiveView("settings");
  }

  if (checkingAuth) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[var(--color-bg-canvas)] text-[14px] text-[var(--color-ink-secondary)]">
        Carregando...
      </div>
    );
  }

  if (!user || !token) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }

  const activeSession = sessions.find((item) => item.session_id === activeSessionId) ?? null;

  return (
    <div className="flex h-full w-full overflow-hidden bg-[var(--color-bg-canvas)]">
      <Sidebar
        user={user}
        sessions={sessions}
        activeSessionId={activeSessionId}
        activeView={activeView}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileMenuOpen}
        onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
        onCloseMobile={() => setMobileMenuOpen(false)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onOpenStoreInfo={() => setStoreModalOpen(true)}
        onOpenSettings={handleOpenSettings}
        onLogout={handleLogout}
      />

      <div className="flex min-w-0 flex-1 flex-col bg-[var(--color-bg-canvas)]">
        <MobileHeader
          onOpenMenu={() => setMobileMenuOpen(true)}
          onNewChat={handleNewChat}
        />

        <div className="hidden h-14 shrink-0 items-center justify-between px-6 md:flex">
          <div className="flex items-center gap-3">
            {sidebarCollapsed && (
              <button
                type="button"
                onClick={() => setSidebarCollapsed(false)}
                aria-label="Expandir barra lateral"
                className="flex h-8 w-8 items-center justify-center rounded-[8px] border-0 bg-transparent text-[var(--color-ink-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
              >
                <PanelLeft size={16} strokeWidth={1.5} />
              </button>
            )}
            {activeView === "chat" && activeSession && (
              <span className="text-[16px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                {activeSession.title}
              </span>
            )}
          </div>
        </div>

        <main className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 pb-16">
          {activeView === "settings" && user.role === "admin" ? (
            <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-2">
              <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
                Ajustes
              </h1>
              <p className="m-0 text-[14px] leading-[140%] text-[var(--color-ink-secondary)]">
                Gerencie os arquivos da loja e controle quais ferramentas o agente pode consultar
              </p>
            </div>
          ) : user.role === "customer" && !serviceReady ? (
            <div className="flex w-full max-w-[var(--container-chat)] flex-col items-start gap-6">
              <div className="flex flex-col gap-2">
                <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
                  Atendimento indisponível
                </h1>
                <p className="m-0 max-w-[540px] text-[16px] leading-[130%] text-[var(--color-ink-secondary)]">
                  Nosso atendimento virtual não está disponível no momento. Entre em contato com a
                  nossa equipe pelo telefone (67) 3341-4444 ou pelo e-mail
                  contato@emporiodamusica.com.br.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setStoreModalOpen(true)}
                className="flex h-10 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-5 text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)]"
              >
                Sobre a loja
              </button>
            </div>
          ) : (
            <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-2">
              <h1 className="m-0 text-[24px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
                Em que instrumento posso ajudar?
              </h1>
              <p className="m-0 text-[16px] leading-[130%] text-[var(--color-ink-secondary)]">
                Consulte estoque real, condições de PIX e parcelamento, políticas da loja ou seu
                pedido
              </p>
            </div>
          )}
        </main>
      </div>

      <StoreInfoModal
        open={storeModalOpen}
        store={storeInfo}
        onClose={() => setStoreModalOpen(false)}
      />
    </div>
  );
}
