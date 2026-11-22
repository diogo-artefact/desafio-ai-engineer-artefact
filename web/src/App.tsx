import { PanelLeft } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AdminSettingsView } from "./components/AdminSettingsView";
import { AuthScreen } from "./components/AuthScreen";
import { ChatView, type ChatTurnError } from "./components/ChatView";
import { MobileHeader } from "./components/MobileHeader";
import { PersonalizationView } from "./components/PersonalizationView";
import { Sidebar, type AppView } from "./components/Sidebar";
import { StoreInfoModal } from "./components/StoreInfoModal";
import type { DisplayTraceStep } from "./components/TraceSteps";
import { ApiError, api } from "./lib/api";
import { clearAuthToken, readAuthToken, writeAuthToken } from "./lib/storage";
import type {
  AuthResponse,
  AuthUser,
  ChatMessage,
  ChatStreamEvent,
  KnowledgeStatus,
  ModelInfo,
  OrderDraft,
  SessionSummary,
  StoreInfo,
  ToolInfo,
} from "./types/api";

function formatArgsLine(args: Record<string, unknown>): string | null {
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

export function App() {
  const [token, setToken] = useState<string | null>(() => readAuthToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState<boolean>(() => Boolean(readAuthToken()));

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loadingTitleSessionId, setLoadingTitleSessionId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<AppView>("chat");
  const [serviceReady, setServiceReady] = useState<boolean>(true);
  const [storeInfo, setStoreInfo] = useState<StoreInfo | null>(null);

  const [knowledge, setKnowledge] = useState<KnowledgeStatus | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [activeModel, setActiveModel] = useState<string>("google:gemini-4-hydrogen");
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [enabledTools, setEnabledTools] = useState<string[] | null>(null);
  const [loadingAdmin, setLoadingAdmin] = useState(false);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [orderDrafts, setOrderDrafts] = useState<OrderDraft[]>([]);
  const [draftBusyId, setDraftBusyId] = useState<string | null>(null);
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});
  const [loadingSession, setLoadingSession] = useState(false);
  const [draft, setDraft] = useState("");
  const [focusSignal, setFocusSignal] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [liveSteps, setLiveSteps] = useState<DisplayTraceStep[]>([]);
  const [chatError, setChatError] = useState<ChatTurnError | null>(null);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [storeModalOpen, setStoreModalOpen] = useState(false);

  const streamAbortRef = useRef<AbortController | null>(null);
  const skipNextFetchRef = useRef<string | null>(null);

  const stopActiveStream = useCallback(() => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setStreaming(false);
    setStreamingText("");
    setLiveSteps([]);
  }, []);

  const handleLogout = useCallback(() => {
    stopActiveStream();
    clearAuthToken();
    setToken(null);
    setUser(null);
    setSessions([]);
    setActiveSessionId(null);
    setLoadingTitleSessionId(null);
    setMessages([]);
    setOrderDrafts([]);
    setDraftBusyId(null);
    setDraftErrors({});
    setDraft("");
    setChatError(null);
    setKnowledge(null);
    setModels([]);
    setTools([]);
    setEnabledTools(null);
    setActiveView("chat");
    setMobileMenuOpen(false);
    setStoreModalOpen(false);
  }, [stopActiveStream]);

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
    async (authToken: string, currentUser: AuthUser) => {
      try {
        const [health, sessionList, store] = await Promise.all([
          api.health(),
          api.listSessions(authToken),
          api.storeInfo(),
        ]);
        setServiceReady(health.ready);
        setSessions(sessionList);
        setStoreInfo(store);

        if (currentUser.role === "admin") {
          setLoadingAdmin(true);
          try {
            const [knowledgeStatus, modelsRes, toolsList] = await Promise.all([
              api.getKnowledge(authToken),
              api.listModels(authToken),
              api.listTools(authToken),
            ]);
            setKnowledge(knowledgeStatus);
            setServiceReady(knowledgeStatus.ready);
            setModels(modelsRes.models);
            setActiveModel(modelsRes.active_model);
            setTools(toolsList);
            setEnabledTools((prev) =>
              prev === null ? toolsList.map((item) => item.tool_id) : prev,
            );
          } finally {
            setLoadingAdmin(false);
          }
        }
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
    void refreshWorkspace(token, user);
  }, [token, user, refreshWorkspace]);

  useEffect(() => {
    if (!token || !user || !activeSessionId) {
      if (!activeSessionId) {
        setMessages([]);
        setOrderDrafts([]);
        setDraftErrors({});
        setLoadingSession(false);
      }
      return;
    }

    if (skipNextFetchRef.current === activeSessionId) {
      skipNextFetchRef.current = null;
      return;
    }

    let cancelled = false;
    setLoadingSession(true);
    setChatError(null);
    setDraftErrors({});

    api
      .getSession(token, activeSessionId)
      .then((detail) => {
        if (!cancelled) {
          setMessages(detail.messages);
          setOrderDrafts(detail.order_drafts ?? []);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          if (err instanceof ApiError && err.status === 401) {
            handleLogout();
          } else {
            setMessages([]);
            setOrderDrafts([]);
          }
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingSession(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token, user, activeSessionId, handleLogout]);

  const refreshActiveSession = useCallback(async () => {
    if (!token || !activeSessionId || streaming) {
      return;
    }
    try {
      const detail = await api.getSession(token, activeSessionId);
      setMessages(detail.messages);
      setOrderDrafts(detail.order_drafts ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleLogout();
      }
    }
  }, [token, activeSessionId, streaming, handleLogout]);

  const hasPendingDelivery = orderDrafts.some((item) => item.status === "confirmed");

  useEffect(() => {
    if (!hasPendingDelivery || !token || !activeSessionId || streaming) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshActiveSession();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [hasPendingDelivery, token, activeSessionId, streaming, refreshActiveSession]);

  function handleAuthenticated(auth: AuthResponse): void {
    writeAuthToken(auth.token);
    setToken(auth.token);
    setUser(auth.user);
    setActiveView("chat");
    setActiveSessionId(null);
    setMessages([]);
    setOrderDrafts([]);
    setDraftErrors({});
    setChatError(null);
  }

  function handleNewChat(): void {
    stopActiveStream();
    setActiveSessionId(null);
    setMessages([]);
    setOrderDrafts([]);
    setDraftErrors({});
    setChatError(null);
    setActiveView("chat");
    setFocusSignal((prev) => prev + 1);
  }

  function handleSelectSession(sessionId: string): void {
    if (sessionId === activeSessionId && activeView === "chat") {
      return;
    }
    stopActiveStream();
    setChatError(null);
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
        stopActiveStream();
        setActiveSessionId(null);
        setMessages([]);
        setOrderDrafts([]);
        setDraftErrors({});
        setChatError(null);
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

  function handleKnowledgeUpdated(nextKnowledge: KnowledgeStatus): void {
    setKnowledge(nextKnowledge);
    setServiceReady(nextKnowledge.ready);
  }

  function handleModelUpdated(nextActiveModel: string, nextModels: ModelInfo[]): void {
    setActiveModel(nextActiveModel);
    setModels(nextModels);
  }

  async function sendPrompt(rawText: string, replaceLastErrorBubble = false): Promise<void> {
    const cleanText = rawText.trim();
    if (!cleanText || !token || !user || streaming) {
      return;
    }

    setChatError(null);
    setDraft("");
    setStreaming(true);
    setStreamingText("");
    setLiveSteps([]);

    const optimisticUser: ChatMessage = {
      id: -Date.now(),
      role: "user",
      content: cleanText,
      trace: [],
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => {
      const base =
        replaceLastErrorBubble && prev.length > 0 && prev[prev.length - 1].role === "user"
          ? prev.slice(0, -1)
          : prev;
      return [...base, optimisticUser];
    });

    const controller = new AbortController();
    streamAbortRef.current = controller;

    let thinkingCounter = 0;
    let streamSessionId = activeSessionId;

    const handleStreamEvent = (event: ChatStreamEvent): void => {
      if (event.type === "session") {
        const isNewSession = activeSessionId === null;
        streamSessionId = event.session_id;
        if (event.session_id !== activeSessionId) {
          skipNextFetchRef.current = event.session_id;
          setActiveSessionId(event.session_id);
        }
        if (isNewSession) {
          setLoadingTitleSessionId(event.session_id);
        }
        const nowIso = new Date().toISOString();
        setSessions((prev) => {
          if (prev.some((item) => item.session_id === event.session_id)) {
            return prev;
          }
          return [
            {
              session_id: event.session_id,
              title: "",
              created_at: nowIso,
              updated_at: nowIso,
            },
            ...prev,
          ];
        });
        return;
      }

      if (event.type === "session_title") {
        setLoadingTitleSessionId((prev) => (prev === event.session_id ? null : prev));
        setSessions((prev) =>
          prev.map((item) =>
            item.session_id === event.session_id ? { ...item, title: event.title } : item,
          ),
        );
        return;
      }

      if (event.type === "order_draft") {
        setOrderDrafts((prev) => {
          const exists = prev.some((item) => item.draft_id === event.draft.draft_id);
          if (exists) {
            return prev.map((item) =>
              item.draft_id === event.draft.draft_id ? event.draft : item,
            );
          }
          return [...prev, event.draft];
        });
        return;
      }

      if (event.type === "thinking_start") {
        thinkingCounter += 1;
        const stepId = `live-think-${thinkingCounter}`;
        setLiveSteps((prev) => [
          ...prev,
          {
            id: stepId,
            type: "thinking",
            label: "Pensando",
            status: "running",
            detailLines: [],
            startedAt: Date.now(),
          },
        ]);
        return;
      }

      if (event.type === "thinking_delta") {
        setLiveSteps((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i -= 1) {
            if (next[i].type === "thinking" && next[i].status === "running") {
              const current = next[i].detailLines[0] ?? "";
              next[i] = { ...next[i], detailLines: [current + event.delta] };
              break;
            }
          }
          return next;
        });
        return;
      }

      if (event.type === "thinking_end") {
        setLiveSteps((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i -= 1) {
            if (next[i].type === "thinking" && next[i].status === "running") {
              const content = event.content.trim();
              next[i] = {
                ...next[i],
                label: "Pensou",
                status: "done",
                durationMs: event.duration_ms,
                detailLines: content ? [content] : next[i].detailLines,
              };
              break;
            }
          }
          return next;
        });
        return;
      }

      if (event.type === "tool_start") {
        const argsLine = formatArgsLine(event.args);
        setLiveSteps((prev) => [
          ...prev,
          {
            id: event.tool_call_id,
            type: "tool",
            label: event.label,
            status: "running",
            detailLines: argsLine ? [`Consulta: ${argsLine}`] : [],
            startedAt: Date.now(),
          },
        ]);
        return;
      }

      if (event.type === "tool_end") {
        setLiveSteps((prev) =>
          prev.map((step) => {
            if (step.id !== event.tool_call_id) {
              return step;
            }
            const lines = [...step.detailLines];
            if (event.summary) {
              lines.push(`Retorno: ${event.summary}`);
            }
            return {
              ...step,
              label: event.label,
              status: "done",
              durationMs: event.duration_ms,
              detailLines: lines,
            };
          }),
        );
        return;
      }

      if (event.type === "text_delta") {
        setStreamingText((prev) => prev + event.delta);
        return;
      }

      if (event.type === "done") {
        const assistantMessage: ChatMessage = {
          id: Date.now(),
          session_id: streamSessionId ?? undefined,
          role: "assistant",
          content: event.text,
          trace: event.trace,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
        setStreaming(false);
        setStreamingText("");
        setLiveSteps([]);
        return;
      }

      if (event.type === "error") {
        setChatError({
          statusCode: event.status_code,
          message: event.message,
          failedPrompt: cleanText,
        });
        setStreamingText("");
        setLiveSteps([]);
      }
    };

    try {
      await api.streamChat(
        token,
        {
          session_id: activeSessionId,
          message: cleanText,
          enabled_tools: user.role === "admin" ? enabledTools : undefined,
        },
        handleStreamEvent,
        controller.signal,
      );
      const updatedSessions = await api.listSessions(token);
      setSessions(updatedSessions);
    } catch (err) {
      if (controller.signal.aborted) {
        return;
      }
      if (err instanceof ApiError) {
        if (err.status === 401) {
          handleLogout();
          return;
        }
        if (err.status === 503 && user.role === "customer") {
          setServiceReady(false);
          setMessages((prev) => prev.slice(0, -1));
          return;
        }
        setChatError({
          statusCode: err.status,
          message: err.detail,
          failedPrompt: cleanText,
        });
      } else {
        setChatError({
          statusCode: 0,
          message: "Não foi possível conectar ao servidor agora. Tente novamente em instantes.",
          failedPrompt: cleanText,
        });
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      setLoadingTitleSessionId((prev) => (prev === streamSessionId ? null : prev));
      setStreaming(false);
      setStreamingText("");
      setLiveSteps([]);
    }
  }

  function handleRetryError(): void {
    if (!chatError) {
      return;
    }
    void sendPrompt(chatError.failedPrompt, true);
  }

  function handleEditError(): void {
    if (!chatError) {
      return;
    }
    const prompt = chatError.failedPrompt;
    setChatError(null);
    setMessages((prev) =>
      prev.length > 0 && prev[prev.length - 1].role === "user" ? prev.slice(0, -1) : prev,
    );
    setDraft(prompt);
    setFocusSignal((prev) => prev + 1);
  }

  async function handleConfirmOrderDraft(draftId: string): Promise<void> {
    if (!token || draftBusyId !== null) {
      return;
    }
    setDraftBusyId(draftId);
    setDraftErrors((prev) => {
      const next = { ...prev };
      delete next[draftId];
      return next;
    });
    try {
      const res = await api.confirmOrderDraft(token, draftId);
      setOrderDrafts((prev) =>
        prev.map((item) => (item.draft_id === draftId ? res.draft : item)),
      );
      setMessages((prev) => [...prev, res.message]);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          handleLogout();
          return;
        }
        setDraftErrors((prev) => ({ ...prev, [draftId]: err.detail }));
      } else {
        setDraftErrors((prev) => ({
          ...prev,
          [draftId]: "Não foi possível confirmar este pedido agora.",
        }));
      }
    } finally {
      setDraftBusyId(null);
    }
  }

  async function handleCancelOrderDraft(draftId: string): Promise<void> {
    if (!token || draftBusyId !== null) {
      return;
    }
    setDraftBusyId(draftId);
    setDraftErrors((prev) => {
      const next = { ...prev };
      delete next[draftId];
      return next;
    });
    try {
      const updated = await api.cancelOrderDraft(token, draftId);
      setOrderDrafts((prev) =>
        prev.map((item) => (item.draft_id === draftId ? updated : item)),
      );
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          handleLogout();
          return;
        }
        setDraftErrors((prev) => ({ ...prev, [draftId]: err.detail }));
      } else {
        setDraftErrors((prev) => ({
          ...prev,
          [draftId]: "Não foi possível cancelar este pedido agora.",
        }));
      }
    } finally {
      setDraftBusyId(null);
    }
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
  const showHeaderBorder =
    activeView === "chat" && (messages.length > 0 || streaming || Boolean(chatError));

  return (
    <div className="flex h-full w-full overflow-hidden bg-[var(--color-bg-canvas)]">
      <Sidebar
        user={user}
        sessions={sessions}
        activeSessionId={activeSessionId}
        loadingTitleSessionId={loadingTitleSessionId}
        activeView={activeView}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileMenuOpen}
        onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
        onCloseMobile={() => setMobileMenuOpen(false)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onOpenPersonalization={() => setActiveView("personalization")}
        onOpenStoreInfo={() => setStoreModalOpen(true)}
        onOpenSettings={handleOpenSettings}
        onLogout={handleLogout}
      />

      <div className="flex min-w-0 flex-1 flex-col bg-[var(--color-bg-canvas)]">
        <MobileHeader
          onOpenMenu={() => setMobileMenuOpen(true)}
          onNewChat={handleNewChat}
        />

        <div
          className={`hidden h-14 shrink-0 items-center justify-between px-6 md:flex ${
            showHeaderBorder ? "border-b border-[var(--color-border-default)]" : ""
          }`}
        >
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
            {showHeaderBorder && activeSession && (
              loadingTitleSessionId === activeSession.session_id ? (
                <span
                  aria-label="Gerando título da conversa"
                  className="block h-3.5 w-40 animate-pulse rounded-[6px] bg-[var(--color-bg-hover)]"
                />
              ) : (
                <span className="text-[16px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                  {activeSession.title || "Nova conversa"}
                </span>
              )
            )}
          </div>
        </div>

        {activeView === "personalization" ? (
          <PersonalizationView token={token} onUnauthorized={handleLogout} />
        ) : activeView === "settings" && user.role === "admin" ? (
          <AdminSettingsView
            token={token}
            knowledge={knowledge}
            models={models}
            activeModel={activeModel}
            tools={tools}
            enabledTools={enabledTools ?? tools.map((item) => item.tool_id)}
            loading={loadingAdmin}
            onKnowledgeUpdated={handleKnowledgeUpdated}
            onModelUpdated={handleModelUpdated}
            onEnabledToolsChange={(nextTools) => setEnabledTools(nextTools)}
            onUnauthorized={handleLogout}
          />
        ) : (
          <ChatView
            user={user}
            serviceReady={serviceReady}
            messages={messages}
            orderDrafts={orderDrafts}
            draftBusyId={draftBusyId}
            draftErrors={draftErrors}
            loadingSession={loadingSession}
            streaming={streaming}
            streamingText={streamingText}
            liveSteps={liveSteps}
            chatError={chatError}
            draft={draft}
            focusSignal={focusSignal}
            onDraftChange={setDraft}
            onSend={(text) => void sendPrompt(text)}
            onStop={stopActiveStream}
            onRetryError={handleRetryError}
            onEditError={handleEditError}
            onRetryMessage={(prompt) => void sendPrompt(prompt)}
            onConfirmOrderDraft={(draftId) => void handleConfirmOrderDraft(draftId)}
            onCancelOrderDraft={(draftId) => void handleCancelOrderDraft(draftId)}
            onDeliveryDue={() => void refreshActiveSession()}
            onOpenStoreInfo={() => setStoreModalOpen(true)}
            onOpenSettings={handleOpenSettings}
          />
        )}
      </div>

      <StoreInfoModal
        open={storeModalOpen}
        store={storeInfo}
        onClose={() => setStoreModalOpen(false)}
      />
    </div>
  );
}
