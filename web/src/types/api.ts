export type UserRole = "customer" | "admin";

export interface AuthUser {
  user_id: string;
  name: string;
  email: string;
  role: UserRole;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface HealthResponse {
  status: string;
  ready: boolean;
}

export interface StoreHours {
  is_open: boolean;
  current_time_local: string;
  weekday_pt: string;
  schedule_summary: string;
  next_opening: string | null;
}

export interface PolicyHighlight {
  title: string;
  detail: string;
}

export interface StoreInfo {
  name: string;
  legal_name: string;
  cnpj: string;
  founded: number;
  address: string;
  phone_primary: string;
  phone_whatsapp_manual: string;
  email: string;
  scope_note: string;
  policies_highlights: PolicyHighlight[];
  hours: StoreHours;
}

export interface KnowledgeSourceStatus {
  source_key: "store_csvs" | "policy_pdf";
  loaded: boolean;
  file_names: string[];
  record_count: number;
  audit_count: number;
  uploaded_at: string | null;
}

export interface KnowledgeStatus {
  csvs: KnowledgeSourceStatus;
  pdf: KnowledgeSourceStatus;
  ready: boolean;
  required_csv_tables?: string[];
}

export interface KnowledgeUploadResponse {
  report: Record<string, unknown>;
  knowledge: KnowledgeStatus;
}

export interface SessionSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ThinkingTraceEntry {
  type: "thinking";
  label: string;
  duration_ms: number;
  content: string;
}

export interface ToolTraceEntry {
  type: "tool";
  tool_name: string;
  label: string;
  summary: string;
  args: Record<string, unknown>;
  duration_ms: number;
}

export type TraceEntry = ThinkingTraceEntry | ToolTraceEntry;

export interface ChatMessage {
  id: number;
  session_id?: string;
  role: "user" | "assistant";
  content: string;
  trace: TraceEntry[];
  created_at: string;
}

export interface SessionDetailResponse {
  session: SessionSummary;
  messages: ChatMessage[];
}

export interface ToolInfo {
  tool_id: string;
  label: string;
  description: string;
}

export interface ModelInfo {
  model_id: string;
  label: string;
  description: string;
}

export interface ModelsResponse {
  active_model: string;
  models: ModelInfo[];
}

export interface ChatRequestPayload {
  session_id?: string | null;
  message: string;
  enabled_tools?: string[] | null;
}

export type ChatStreamEvent =
  | { type: "session"; session_id: string }
  | { type: "thinking_start" }
  | { type: "thinking_delta"; delta: string }
  | { type: "thinking_end"; duration_ms: number; content: string }
  | {
      type: "tool_start";
      tool_call_id: string;
      tool_name: string;
      label: string;
      args: Record<string, unknown>;
    }
  | {
      type: "tool_end";
      tool_call_id: string;
      tool_name: string;
      label: string;
      summary: string;
      duration_ms: number;
    }
  | { type: "text_delta"; delta: string }
  | { type: "done"; text: string; trace: TraceEntry[] }
  | { type: "error"; status_code: number; message: string; detail: string };
