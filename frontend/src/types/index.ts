export type Classification = "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED";

export type TogglableRole = "guest" | "employee" | "manager";

export interface DocumentMeta {
  doc_id: string;
  filename: string;
  mime: string;
  pages: number;
  chunks: number;
  sections: string[];
  doc_level: number; // 1..4
  classification: Classification;
  created_at: string;
  uploaded_by_username: string;
  uploaded_by_role: string;
  disabled_for_roles: TogglableRole[];
}

export interface Source {
  index: number;
  doc_id: string;
  filename: string;
  page: number;
  section: string;
  text: string;
  rrf_score: number;
  rerank_score: number | null;
  chunk_index?: number;
}

export interface DisambigCandidate {
  doc_id: string;
  filename: string;
  label: string;
  hint: string;
  top_score: number;
  chunk_count: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  streaming?: boolean;
  refused?: boolean;
  answerMode?: AnswerMode;
  // Observability payload from the `done` event
  latency_ms?: {
    retrieve: number;
    rerank: number;
    generate: number;
    total: number;
  };
  tokens?: { prompt: number; completion: number };
  cached?: boolean;
  corrective_retries?: number;
  faithfulness?: number;
  // Agent: composite 0..100 confidence chip. Null when not grounded.
  confidence?: number | null;
  // Agent: true when unknown/refused was triggered by RBAC (a higher-
  // clearance doc matched). Swaps the bland "no answer" card for the
  // richer "request access" card on the frontend.
  rbacBlocked?: boolean;
  // Tier 1.1: post-generation citation verification result. Populated
  // for grounded answers. Counts fabricated/weak [Source N] tags.
  citationCheck?: {
    total: number;
    valid: number;
    fabricated: number[];
    weak: number[];
    score: number;
  } | null;
  // Tier 2.2: cross-doc comparison columns. One entry per doc the user
  // asked to compare. Renders as side-by-side ComparisonCard.
  comparison?: {
    query: string;
    columns: ComparisonColumn[];
  };
  // Tier 3.3: true when retrieval applied a recency boost (query had
  // "latest", "Q4 2024", etc.). Renders a small "newer-first" chip.
  recencyBoostApplied?: boolean;
  corrective_rewrite?: string;
  contextualized_query?: string;
  welcome?: WelcomePayload;
  // Agent — disambiguation card state (renders when answerMode="disambiguate")
  disambiguation?: {
    query: string;
    candidates: DisambigCandidate[];
    // Set after the user clicks a candidate — we flip the card to a
    // "Scoped to X" confirmation so the history is readable on replay.
    chosen_doc_id?: string;
  };
  // Agent — intent restatement shown above the streamed answer.
  // `edited: true` means the user edited the pill and the answer used
  // their override as the search query.
  intent?: {
    text: string;
    edited: boolean;
  };
}

export interface ChatSettings {
  useHyde: boolean;
  useRerank: boolean;
  useMultiQuery: boolean;
  useCorrective: boolean;
  useFaithfulness: boolean;
  topK: number;
  sectionFilter: string[];
}

export interface UploadResponse {
  doc_id: string;
  filename: string;
  status: string;
  chunks?: number;
  pages?: number;
  error?: string;
}

export interface User {
  username: string;
  role: "guest" | "employee" | "manager" | "executive";
  level: number; // 1..4
  title: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: User["role"];
  level: number;
  title: string;
}

export interface AuditRow {
  id: number;
  ts: string;
  username: string;
  user_level: number;
  query: string;
  refused: boolean;
  returned_chunks: number;
  allowed_doc_ids: string[];
  answer_mode?: AnswerMode;
  latency_total_ms?: number;
  latency_retrieve_ms?: number;
  latency_rerank_ms?: number;
  latency_generate_ms?: number;
  tokens_prompt?: number;
  tokens_completion?: number;
  cached?: boolean;
  corrective_retries?: number;
  faithfulness?: number;
}

export interface AuditResponse {
  total: number;
  rows: AuditRow[];
}

export type AnswerMode =
  | "grounded"
  | "refused"
  | "general"
  | "unknown"
  | "social"
  | "meta"
  | "system"
  | "disambiguate"
  | "comparison";

export interface ComparisonColumn {
  doc_id: string;
  filename: string;
  label: string;
  answer: string;
  sources: Source[];
  ok: boolean;
  error: string;
}

export interface WelcomeTier {
  level: number;
  label: Classification;
  description: string;
  count: number;
  accessible: boolean;
}

export interface GraphNode {
  id: string;
  type: "doc" | "chunk";
  label: string;
  doc_id: string | null;
  classification: Classification | null;
  doc_level: number | null;
  disabled_for_roles: string[];
  uploaded_by_username: string | null;
  uploaded_by_role: string | null;
  page: number | null;
  section: string | null;
  chunk_index: number | null;
  text_preview: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: {
    docs: number;
    chunks: number;
    by_classification: Record<string, number>;
  };
}

export interface GraphHeatResponse {
  docs: Record<string, { retrieved: number }>;
  chunks: Record<string, { cited: number }>;
  total_queries: number;
  total_citations: number;
}

export interface TraceStageHit {
  chunk_id: string;
  doc_id: string;
  score: number;
}

export interface GraphTraceResponse {
  query: string;
  role: string;
  level: number;
  dense: TraceStageHit[];
  bm25: TraceStageHit[];
  rrf: TraceStageHit[];
  rerank: TraceStageHit[];
  latency_ms: number;
}

export interface WelcomePayload {
  user: {
    username: string;
    role: User["role"];
    role_title: string;
    level: number;
    clearance_label: Classification;
  };
  accessible_count: number;
  tiers: WelcomeTier[];
  suggestions: string[];
  upload_hint: string;
  greeting: string;
}

export interface ThreadSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ThreadTurn {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  refused: boolean;
  answer_mode: AnswerMode;
  faithfulness: number; // -1 = not scored, 0..1 otherwise
  created_at: string;
  // Only populated when answer_mode === "disambiguate".
  disambiguation?: {
    candidates: DisambigCandidate[];
    query?: string;
    chosen_doc_id?: string;
  } | null;
  // Only populated when answer_mode === "comparison".
  comparison?: {
    columns: ComparisonColumn[];
  } | null;
}

export interface ThreadDetail extends ThreadSummary {
  turns: ThreadTurn[];
}
