import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  AuditResponse,
  DocumentMeta,
  LoginResponse,
  Source,
  ThreadDetail,
  ThreadSummary,
  UploadResponse,
  User,
  WelcomePayload,
} from "@/types";
import { authHeaders, clearToken } from "@/lib/auth";

const API_BASE = ""; // relative — Vite proxy sends /api to backend

async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = { ...(init.headers || {}), ...authHeaders() } as Record<string, string>;
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    // Give callers a chance to catch; consumer routes handle the redirect.
    throw new Error("401 Unauthorized — please log in again");
  }
  return res;
}

// ── Auth ────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const msg = res.status === 401 ? "Invalid username or password" : `login failed: ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}

export async function fetchMe(): Promise<User> {
  const res = await authFetch(`${API_BASE}/api/auth/me`);
  if (!res.ok) throw new Error(`me failed: ${res.status}`);
  const d = await res.json();
  return { username: d.username, role: d.role, level: d.level, title: d.title || "" };
}

// ── Documents ───────────────────────────────────────────────────────────────

export async function listDocuments(): Promise<DocumentMeta[]> {
  const res = await authFetch(`${API_BASE}/api/documents`);
  if (!res.ok) throw new Error(`list failed: ${res.status}`);
  return res.json();
}

export async function uploadDocuments(
  files: File[],
  classification?: number
): Promise<UploadResponse[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  if (classification) fd.append("classification", String(classification));
  const res = await authFetch(`${API_BASE}/api/documents`, { method: "POST", body: fd });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `upload failed: ${res.status}`);
  }
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/documents/${docId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

export async function updateDocumentVisibility(
  docId: string,
  disabledForRoles: string[]
): Promise<DocumentMeta> {
  const res = await authFetch(`${API_BASE}/api/documents/${docId}/visibility`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disabled_for_roles: disabledForRoles }),
  });
  if (!res.ok) {
    if (res.status === 403) throw new Error("Executive access required");
    throw new Error(`visibility update failed: ${res.status}`);
  }
  return res.json();
}

// ── Threads ─────────────────────────────────────────────────────────────────

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await authFetch(`${API_BASE}/api/threads`);
  if (!res.ok) throw new Error(`threads list failed: ${res.status}`);
  return res.json();
}

export async function getThread(id: string): Promise<ThreadDetail> {
  const res = await authFetch(`${API_BASE}/api/threads/${id}`);
  if (!res.ok) throw new Error(`thread fetch failed: ${res.status}`);
  return res.json();
}

export async function createThread(): Promise<ThreadSummary> {
  const res = await authFetch(`${API_BASE}/api/threads`, { method: "POST" });
  if (!res.ok) throw new Error(`thread create failed: ${res.status}`);
  return res.json();
}

export async function renameThread(id: string, title: string): Promise<ThreadSummary> {
  const res = await authFetch(`${API_BASE}/api/threads/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename failed: ${res.status}`);
  return res.json();
}

export async function deleteThread(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/threads/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

// ── Audit ───────────────────────────────────────────────────────────────────

export async function fetchAudit(limit = 500): Promise<AuditResponse> {
  const res = await authFetch(`${API_BASE}/api/audit?limit=${limit}`);
  if (res.status === 403) throw new Error("403 Forbidden — executive access required");
  if (!res.ok) throw new Error(`audit failed: ${res.status}`);
  return res.json();
}

// ── Public playground (no auth) ─────────────────────────────────────────────

export interface PlaygroundHit {
  rank: number;
  score: number;
  doc_id: string;
  filename: string;
  page: number;
  section: string;
  text: string;
}

export interface PlaygroundStage {
  stage: "dense" | "bm25" | "rrf" | "rerank";
  hits: PlaygroundHit[];
  duration_ms: number;
}

export interface PlaygroundResponse {
  query: string;
  public_doc_count: number;
  stages: PlaygroundStage[];
  fused_top_filenames: string[];
}

export async function playgroundRetrieve(
  query: string,
  top_k = 5
): Promise<PlaygroundResponse> {
  const res = await fetch(`${API_BASE}/api/playground/retrieve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* empty */
    }
    throw new Error(detail);
  }
  return res.json();
}

// ── Meta ────────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/health`);
  return res.json();
}

export async function fetchWelcome(): Promise<WelcomePayload> {
  const res = await authFetch(`${API_BASE}/api/welcome`);
  if (!res.ok) throw new Error(`welcome failed: ${res.status}`);
  return res.json();
}

export async function fetchSuggestedQuestions(docId: string): Promise<string[]> {
  const res = await authFetch(
    `${API_BASE}/api/suggested-questions?doc_id=${encodeURIComponent(docId)}`
  );
  if (!res.ok) return [];
  const data = await res.json();
  return data.questions || [];
}

// ── Streaming chat ──────────────────────────────────────────────────────────

export interface ChatStreamRequest {
  query: string;
  doc_ids: string[];
  use_hyde: boolean;
  use_rerank: boolean;
  use_multi_query?: boolean;
  use_corrective?: boolean;
  use_faithfulness?: boolean;
  section_filter?: string[];
  top_k: number;
  history: { role: "user" | "assistant"; content: string }[];
  thread_id?: string | null;
}

export interface DoneMeta {
  latency_ms?: { retrieve: number; rerank: number; generate: number; total: number };
  tokens?: { prompt: number; completion: number };
  cached?: boolean;
  corrective_retries?: number;
  faithfulness?: number;
}

export interface ChatStreamCallbacks {
  onThread: (thread_id: string, title: string, isNew: boolean) => void;
  onSources: (sources: Source[]) => void;
  onToken: (delta: string) => void;
  onRefused: (message: string) => void;
  onGeneral: (message: string) => void;
  onUnknown: (message: string) => void;
  onCached: () => void;
  onCorrective: (rewritten: string, original: string) => void;
  onContextualized: (rewritten: string, original: string) => void;
  onWelcome: (payload: WelcomePayload) => void;
  onDone: (answerMode: string, thread_id: string, meta: DoneMeta) => void;
  onError: (message: string) => void;
}

export async function streamChat(
  req: ChatStreamRequest,
  callbacks: ChatStreamCallbacks,
  signal: AbortSignal
): Promise<void> {
  await fetchEventSource(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...authHeaders(),
    },
    body: JSON.stringify(req),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      const data = ev.data ? JSON.parse(ev.data) : {};
      switch (ev.event) {
        case "thread":
          callbacks.onThread(data.thread_id, data.title || "", !!data.is_new);
          break;
        case "sources":
          callbacks.onSources(data.sources || []);
          break;
        case "token":
          if (data.delta) callbacks.onToken(data.delta);
          break;
        case "refused":
          callbacks.onRefused(data.message || "Access refused.");
          break;
        case "general_mode":
          callbacks.onGeneral(data.message || "General knowledge.");
          break;
        case "unknown":
          callbacks.onUnknown(data.message || "I don't have a confident answer.");
          break;
        case "cached":
          callbacks.onCached();
          break;
        case "corrective":
          callbacks.onCorrective(data.rewritten || "", data.original || "");
          break;
        case "contextualized":
          callbacks.onContextualized(data.rewritten || "", data.original || "");
          break;
        case "welcome":
          callbacks.onWelcome(data as WelcomePayload);
          break;
        case "done":
          callbacks.onDone(data.answer_mode || "grounded", data.thread_id || "", {
            latency_ms: data.latency_ms,
            tokens: data.tokens,
            cached: data.cached,
            corrective_retries: data.corrective_retries,
            faithfulness: data.faithfulness,
          });
          break;
        case "error":
          callbacks.onError(data.message || "unknown error");
          break;
      }
    },
    onerror(err) {
      callbacks.onError(String(err));
      throw err;
    },
  });
}
