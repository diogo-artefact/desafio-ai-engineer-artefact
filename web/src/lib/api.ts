import type {
  AuthResponse,
  AuthUser,
  ChatRequestPayload,
  ChatStreamEvent,
  HealthResponse,
  KnowledgeStatus,
  KnowledgeUploadResponse,
  ModelsResponse,
  SessionDetailResponse,
  SessionSummary,
  StoreInfo,
  ToolInfo,
  UserMemory,
  UserPersonalization,
} from "../types/api";

const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function extractErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") {
    return fallback;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first) {
      const msg = (first as { msg?: unknown }).msg;
      if (typeof msg === "string" && msg.trim()) {
        return msg;
      }
    }
  }
  return fallback;
}

async function parseErrorResponse(response: Response): Promise<ApiError> {
  const fallback = `Erro na comunicação com o servidor (HTTP ${response.status}).`;
  try {
    const data: unknown = await response.json();
    return new ApiError(response.status, extractErrorDetail(data, fallback));
  } catch {
    return new ApiError(response.status, fallback);
  }
}

function authHeaders(token?: string | null): Record<string, string> {
  if (!token) {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

async function requestJson<T>(
  path: string,
  options: {
    method?: string;
    token?: string | null;
    body?: unknown;
    formData?: FormData;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = authHeaders(options.token);
  let requestBody: BodyInit | undefined;

  if (options.formData) {
    requestBody = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: requestBody,
    signal: options.signal,
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

function parseSseChunk(rawBlock: string): ChatStreamEvent | null {
  const dataLines: string[] = [];
  for (const line of rawBlock.split(/\r?\n/)) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) {
    return null;
  }
  const rawJson = dataLines.join("\n").trim();
  if (!rawJson) {
    return null;
  }
  return JSON.parse(rawJson) as ChatStreamEvent;
}

export const api = {
  login(email: string, password: string): Promise<AuthResponse> {
    return requestJson<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: { email, password },
    });
  },

  register(name: string, email: string, password: string): Promise<AuthResponse> {
    return requestJson<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: { name, email, password },
    });
  },

  async me(token: string): Promise<AuthUser> {
    const data = await requestJson<{ user: AuthUser }>("/api/auth/me", { token });
    return data.user;
  },

  health(): Promise<HealthResponse> {
    return requestJson<HealthResponse>("/api/health");
  },

  storeInfo(): Promise<StoreInfo> {
    return requestJson<StoreInfo>("/api/store");
  },

  async listSessions(token: string): Promise<SessionSummary[]> {
    const data = await requestJson<{ sessions: SessionSummary[] }>("/api/sessions", { token });
    return data.sessions;
  },

  createSession(token: string, title = "Nova conversa"): Promise<SessionSummary> {
    return requestJson<SessionSummary>("/api/sessions", {
      method: "POST",
      token,
      body: { title },
    });
  },

  getSession(token: string, sessionId: string): Promise<SessionDetailResponse> {
    return requestJson<SessionDetailResponse>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      token,
    });
  },

  deleteSession(token: string, sessionId: string): Promise<void> {
    return requestJson<void>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      token,
    });
  },

  async listMemories(token: string): Promise<UserMemory[]> {
    const data = await requestJson<{ memories: UserMemory[] }>("/api/memories", { token });
    return data.memories;
  },

  deleteMemory(token: string, factKey: string): Promise<void> {
    return requestJson<void>(`/api/memories/${encodeURIComponent(factKey)}`, {
      method: "DELETE",
      token,
    });
  },

  clearMemories(token: string): Promise<void> {
    return requestJson<void>("/api/memories", {
      method: "DELETE",
      token,
    });
  },

  getPersonalization(token: string): Promise<UserPersonalization> {
    return requestJson<UserPersonalization>("/api/personalization", { token });
  },

  updatePersonalization(token: string, customInstructions: string): Promise<UserPersonalization> {
    return requestJson<UserPersonalization>("/api/personalization", {
      method: "PUT",
      token,
      body: { custom_instructions: customInstructions },
    });
  },

  getKnowledge(token: string): Promise<KnowledgeStatus> {
    return requestJson<KnowledgeStatus>("/api/knowledge", { token });
  },

  uploadCsvs(token: string, files: File[]): Promise<KnowledgeUploadResponse> {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    return requestJson<KnowledgeUploadResponse>("/api/knowledge/csvs", {
      method: "POST",
      token,
      formData,
    });
  },

  uploadPdf(token: string, file: File): Promise<KnowledgeUploadResponse> {
    const formData = new FormData();
    formData.append("file", file);
    return requestJson<KnowledgeUploadResponse>("/api/knowledge/pdf", {
      method: "POST",
      token,
      formData,
    });
  },

  async listTools(token: string): Promise<ToolInfo[]> {
    const data = await requestJson<{ tools: ToolInfo[] }>("/api/tools", { token });
    return data.tools;
  },

  listModels(token: string): Promise<ModelsResponse> {
    return requestJson<ModelsResponse>("/api/models", { token });
  },

  updateModel(token: string, modelId: string): Promise<ModelsResponse> {
    return requestJson<ModelsResponse>("/api/models", {
      method: "PUT",
      token,
      body: { model_id: modelId },
    });
  },

  async streamChat(
    token: string,
    payload: ChatRequestPayload,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal,
    });

    if (!response.ok) {
      throw await parseErrorResponse(response);
    }

    if (!response.body) {
      throw new ApiError(500, "Resposta de streaming indisponível.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: !done });
      }

      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const event = parseSseChunk(block);
        if (event) {
          onEvent(event);
        }
      }

      if (done) {
        const trailing = parseSseChunk(buffer);
        if (trailing) {
          onEvent(trailing);
        }
        break;
      }
    }
  },
};
