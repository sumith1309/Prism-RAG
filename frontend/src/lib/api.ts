import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  AuditResponse,
  DocumentMeta,
  GraphHeatResponse,
  GraphResponse,
  GraphTraceResponse,
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
  classification?: number,
  disabledForRoles?: string[]
): Promise<UploadResponse[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  if (classification) fd.append("classification", String(classification));
  if (disabledForRoles && disabledForRoles.length > 0) {
    fd.append("disabled_for_roles", disabledForRoles.join(","));
  }
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
  patch: { disabled_for_roles?: string[]; doc_level?: number }
): Promise<DocumentMeta> {
  const res = await authFetch(`${API_BASE}/api/documents/${docId}/visibility`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
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

// ── Knowledge graph ─────────────────────────────────────────────────────────

export async function fetchGraph(): Promise<GraphResponse> {
  const res = await authFetch(`${API_BASE}/api/graph`);
  if (!res.ok) throw new Error(`graph failed: ${res.status}`);
  return res.json();
}

export async function fetchGraphHeat(): Promise<GraphHeatResponse> {
  const res = await authFetch(`${API_BASE}/api/graph/heat`);
  if (!res.ok) throw new Error(`graph heat failed: ${res.status}`);
  return res.json();
}

export async function traceGraphQuery(
  query: string,
  roleOverride?: string,
  topK = 5
): Promise<GraphTraceResponse> {
  const res = await authFetch(`${API_BASE}/api/graph/trace`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      role_override: roleOverride || null,
      top_k: topK,
    }),
  });
  if (!res.ok) throw new Error(`graph trace failed: ${res.status}`);
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

export interface AutoClassifyResult {
  suggested_level: number;
  suggested_label: string;
  reason: string;
  confidence: number;
  capped_to_user_level: boolean;
}

export async function autoClassifyDocument(
  file: File
): Promise<AutoClassifyResult | null> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/api/documents/auto-classify`, {
    method: "POST",
    body: fd,
    headers: { ...authHeaders() },
  });
  if (!res.ok) return null;
  return await res.json();
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
  // Agent controls (added 2026-04-16):
  //   preferred_doc_id — set when user picked a doc from the
  //     DisambiguationCard; hard-scopes retrieval to that single doc.
  //   override_intent — user-edited query from the Intent Mirror pill.
  //   skip_disambiguation — bypass the ambiguity detector on this call.
  preferred_doc_id?: string | null;
  override_intent?: string | null;
  skip_disambiguation?: boolean;
}

export interface DisambigCandidate {
  doc_id: string;
  filename: string;
  label: string;
  hint: string;
  top_score: number;
  chunk_count: number;
}

export interface DoneMeta {
  latency_ms?: { retrieve: number; rerank: number; generate: number; total: number };
  tokens?: { prompt: number; completion: number };
  cached?: boolean;
  corrective_retries?: number;
  faithfulness?: number;
  confidence?: number | null; // 0..100 composite, null on non-grounded modes
  rbac_blocked?: boolean; // true when unknown/refused was RBAC-triggered
  citation_check?: CitationCheck | null;
}

export interface CitationCheck {
  total: number;
  valid: number;
  fabricated: number[]; // [Source N] tags pointing to non-existent chunks
  weak: number[]; // cited but no substantive word overlap with chunk text
  score: number; // valid / total
}

export async function requestAccess(
  query: string,
  reason?: string
): Promise<{ ok: boolean; message: string }> {
  const res = await authFetch(`${API_BASE}/api/access-request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, reason }),
  });
  if (!res.ok) {
    return { ok: false, message: `Request failed: ${res.status}` };
  }
  return await res.json();
}

export interface ChatStreamCallbacks {
  onThread: (thread_id: string, title: string, isNew: boolean) => void;
  onSources: (sources: Source[]) => void;
  onToken: (delta: string) => void;
  onRefused: (message: string, rbacBlocked: boolean) => void;
  onGeneral: (message: string) => void;
  onUnknown: (message: string, rbacBlocked: boolean) => void;
  onCached: () => void;
  onCorrective: (rewritten: string, original: string) => void;
  onContextualized: (rewritten: string, original: string) => void;
  onAnswerReset: () => void;
  onWelcome: (payload: WelcomePayload) => void;
  // Agent events:
  onDisambiguate?: (query: string, candidates: DisambigCandidate[], message: string) => void;
  onIntent?: (intent: string, original: string, edited: boolean) => void;
  onCitationCheck?: (check: CitationCheck) => void;
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
          callbacks.onRefused(data.message || "Access refused.", !!data.rbac_blocked);
          break;
        case "general_mode":
          callbacks.onGeneral(data.message || "General knowledge.");
          break;
        case "unknown":
          callbacks.onUnknown(
            data.message || "I don't have a confident answer.",
            !!data.rbac_blocked
          );
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
        case "answer_reset":
          callbacks.onAnswerReset();
          break;
        case "welcome":
          callbacks.onWelcome(data as WelcomePayload);
          break;
        case "disambiguate":
          callbacks.onDisambiguate?.(
            data.query || "",
            data.candidates || [],
            data.message || ""
          );
          break;
        case "intent":
          callbacks.onIntent?.(
            data.intent || "",
            data.original || "",
            !!data.edited
          );
          break;
        case "citation_check":
          callbacks.onCitationCheck?.(data as CitationCheck);
          break;
        case "done":
          callbacks.onDone(data.answer_mode || "grounded", data.thread_id || "", {
            latency_ms: data.latency_ms,
            tokens: data.tokens,
            cached: data.cached,
            corrective_retries: data.corrective_retries,
            faithfulness: data.faithfulness,
            confidence: data.confidence ?? null,
            rbac_blocked: !!data.rbac_blocked,
            citation_check: data.citation_check ?? null,
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
