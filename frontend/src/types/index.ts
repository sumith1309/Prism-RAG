export type Classification = "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED";

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
  corrective_rewrite?: string;
  contextualized_query?: string;
  welcome?: WelcomePayload;
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

export type AnswerMode = "grounded" | "refused" | "general" | "unknown" | "social";

export interface WelcomeTier {
  level: number;
  label: Classification;
  description: string;
  count: number;
  accessible: boolean;
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
  created_at: string;
}

export interface ThreadDetail extends ThreadSummary {
  turns: ThreadTurn[];
}
