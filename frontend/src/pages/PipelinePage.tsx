import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import ReactECharts from "echarts-for-react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import {
  Activity,
  ArrowRight,
  Binary,
  BookOpen,
  ChevronLeft,
  Cpu,
  Database,
  Gauge,
  HelpCircle,
  Layers,
  LogIn,
  Search,
  Shield,
  Sparkles,
  Wand2,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { gsap } from "@/lib/gsap";
import {
  CountUp,
  PipelineProgressBar,
  StageReveal,
  TextReveal,
  usePipelineTimeline,
  type PipelineStage,
} from "@/components/pipeline";

// ============================================================================
// Types
// ============================================================================

interface StageHit {
  rank: number;
  score: number;
  chunk_id: string;
  doc_id: string;
  filename: string;
  page: number;
  section: string;
  text: string;
  doc_level: number;
  chunk_index: number;
}

interface PipelineState {
  query: string;
  embedVec: number[] | null;
  embedModel: string;
  embedMs: number;
  dense: StageHit[];
  denseMs: number;
  bm25: StageHit[];
  bm25Ms: number;
  rrf: StageHit[];
  rrfMs: number;
  rerank: StageHit[];
  rerankMs: number;
  rerankModel: string;
  answer: string;
  generateMs: number;
  generateModel: string;
  faithfulness: number;
  totalMs: number;
  promptTokens: number;
  completionTokens: number;
  step: "idle" | "embed" | "dense" | "bm25" | "rrf" | "rerank" | "generate" | "judge" | "done" | "error";
}

const EMPTY_STATE: PipelineState = {
  query: "",
  embedVec: null,
  embedModel: "",
  embedMs: 0,
  dense: [],
  denseMs: 0,
  bm25: [],
  bm25Ms: 0,
  rrf: [],
  rrfMs: 0,
  rerank: [],
  rerankMs: 0,
  rerankModel: "",
  answer: "",
  generateMs: 0,
  generateModel: "",
  faithfulness: -1,
  totalMs: 0,
  promptTokens: 0,
  completionTokens: 0,
  step: "idle",
};

// ============================================================================
// Stage metadata — used by both the flow diagram and the stage cards
// ============================================================================

const STAGES = [
  {
    key: "embed",
    n: 1,
    title: "Query Embedding",
    tagline: "Sentence-transformer encoder",
    icon: Binary,
    color: "#6366f1",
    explainer:
      "Encodes the query into a dense vector (typically 384–768 dimensions, model-dependent) that captures meaning rather than keywords. Sentences with similar meaning land close together in this vector space.",
    why: "Why it matters — semantic search beats keyword search when users phrase questions differently from how the corpus phrases the answers.",
    theory: {
      heading: "How does an embedding model work?",
      body: [
        "A sentence transformer reads each token, builds contextual representations through several attention layers, then mean-pools the final hidden states into a single dense vector. The exact dimensionality depends on the model — MiniLM uses 384, BGE-base 768, OpenAI text-embedding-3-large 3072.",
        "Two queries that mean the same thing produce vectors with high cosine similarity (close to 1), even if they share no words. \"on-call rotation\" and \"who handles incidents at night\" both sit near runbook chunks discussing operational coverage.",
        "Cosine similarity = dot(a,b) / (||a|| · ||b||). Range -1 to +1. Most models normalize to unit length so the dot product alone gives cosine.",
      ],
    },
  },
  {
    key: "dense",
    n: 2,
    title: "Dense Retrieval",
    tagline: "Cosine search · Qdrant",
    icon: Database,
    color: "#3b82f6",
    explainer:
      "Qdrant computes cosine similarity between the query vector and every chunk vector, filtered to the user's RBAC clearance. Returns the most semantically similar chunks.",
    why: "Why it matters — dense retrieval finds chunks that mean the same thing as the query, even with no shared words.",
    theory: {
      heading: "Why a vector database?",
      body: [
        "A naive cosine search across 145 chunks is fine. Across 145 million it would take seconds. Vector databases like Qdrant build HNSW (Hierarchical Navigable Small World) graphs that find approximate nearest neighbours in O(log n) instead of O(n).",
        "Qdrant also supports payload filters (used here for RBAC: doc_level ≤ user.level) applied before similarity ranking — wrong-clearance chunks are physically unreachable, not just hidden.",
      ],
    },
  },
  {
    key: "bm25",
    n: 3,
    title: "BM25 Retrieval",
    tagline: "Lexical · TF-IDF",
    icon: Search,
    color: "#f97316",
    explainer:
      "Ranks chunks by exact term overlap with the query, normalised by document length and term rarity. Strong on proper nouns, acronyms, and codes the embedding model might smooth over.",
    why: "Why it matters — dense vectors miss exact-match cues like product codes, person names, or rare jargon. BM25 doesn't.",
    theory: {
      heading: "BM25 in one formula",
      body: [
        "score(q, d) = Σ_t IDF(t) · (tf(t,d) · (k₁+1)) / (tf(t,d) + k₁ · (1 − b + b · |d|/avgdl))",
        "tf = how often the term appears in the chunk. IDF = how rare the term is across all chunks (rare words count more). The k₁ and b constants tame term saturation and length normalisation.",
        "BM25 has been the boring-but-undefeated baseline for keyword search since 1994. Combining it with embeddings gives much higher recall than either alone — different failure modes.",
      ],
    },
  },
  {
    key: "rrf",
    n: 4,
    title: "RRF Fusion",
    tagline: "Reciprocal Rank Fusion",
    icon: Layers,
    color: "#a855f7",
    explainer:
      "Two ranked lists are fused with score = Σ 1 / (k + rank). Chunks ranked highly by either retriever rise to the top — no need to calibrate scores between systems.",
    why: "Why it matters — combining retrievers with different failure modes gives much higher recall than either alone, and rank-based fusion is robust to score-distribution mismatches.",
    theory: {
      heading: "Why rank fusion, not score fusion?",
      body: [
        "BM25 scores are unbounded positives. Cosine similarity is in [-1,1]. Adding them directly is meaningless because they live on different scales.",
        "RRF sidesteps this by using only ranks. score = Σ 1/(60+rank). The constant 60 (a Microsoft default) dampens the contribution from low ranks — being #1 in BM25 contributes much more than being #20 in dense.",
        "Cormack & Clarke showed in 2009 that RRF beats fancier supervised fusion methods on TREC benchmarks. Simple, parameter-light, robust.",
      ],
    },
  },
  {
    key: "rerank",
    n: 5,
    title: "Cross-Encoder Rerank",
    tagline: "BAAI/bge-reranker-base",
    icon: Wand2,
    color: "#f59e0b",
    explainer:
      "Reads (query, chunk) pairs jointly through a transformer and outputs a precise relevance score. Slower than embedding (one forward pass per pair), so we only run it on the fused top-10.",
    why: "Why it matters — cross-encoders see the full interaction between query and chunk; far more accurate than independent embeddings, especially for the tie-break at the top of the list.",
    theory: {
      heading: "Bi-encoder vs cross-encoder",
      body: [
        "A bi-encoder (like the embedding model in stage 1) embeds query and chunk independently — fast, indexable, but loses query-aware context.",
        "A cross-encoder feeds the model [CLS] query [SEP] chunk [SEP] together. Every token attends to every other token. The result is a single relevance score that captures fine-grained interactions — but you can't pre-index because the score depends on the query.",
        "Standard pattern: bi-encoder for the first-stage \"recall\" pass (fast over millions), cross-encoder for the small top-N \"precision\" pass. Prism RAG uses BAAI/bge-reranker-base — a 278M-param model trained on web-scale relevance pairs.",
      ],
    },
  },
  {
    key: "generate",
    n: 6,
    title: "Grounded Generation",
    tagline: "gpt-4o-mini · cited",
    icon: BookOpen,
    color: "#22c55e",
    explainer:
      "The reranked top-k chunks are stitched into the prompt with a strict instruction: answer ONLY from the provided context, cite as [Source N], and refuse if the chunks don't support an answer.",
    why: "Why it matters — this is what makes RAG safe. The model becomes a reader of your docs instead of a free-associating storyteller.",
    theory: {
      heading: "Why \"grounded\" generation?",
      body: [
        "Vanilla LLM generation hallucinates confidently. RAG grounds the answer in retrieved context: the model is shown the actual source chunks and constrained to draw only from them.",
        "Our prompt enforces three rules: (1) every claim must be traceable to a numbered source, (2) cite as [Source N], (3) say \"I could not find this in the provided documents\" if retrieval was thin.",
        "Even with these guardrails, models drift. That's why the next stage (Faithfulness) acts as a safety net.",
      ],
    },
  },
  {
    key: "judge",
    n: 7,
    title: "Faithfulness Judge",
    tagline: "LLM-scored 0..1",
    icon: Gauge,
    color: "#ef4444",
    explainer:
      "A second LLM call asks: is every claim in the answer supported by the cited sources? Returns a 0..1 score. Low scores trigger our post-hoc demotion: the answer is reclassified as \"No confident answer\" even though chunks were retrieved.",
    why: "Why it matters — this is the safety net that catches the rare case where retrieval looked fine but the generation drifted.",
    theory: {
      heading: "LLM-as-judge",
      body: [
        "Faithfulness is a known-hard metric: defining \"supported\" is nuanced. We use an LLM judge prompted with the answer + the cited sources, asking for a 0..1 score with a short rationale.",
        "Scores ≥ 0.8 = strongly grounded. 0.5–0.8 = mostly grounded with minor drift. < 0.5 = clear hallucination — we demote the answer to \"No confident answer\" and hide the sources panel so the user isn't misled.",
        "The judge isn't perfect (LLM scoring noise), but it catches >90% of confidently-wrong responses in our internal tests.",
      ],
    },
  },
] as const;

type StageKey = (typeof STAGES)[number]["key"];

// ============================================================================
// Main Page
// ============================================================================

export function PipelinePage() {
  const [state, setState] = useState<PipelineState>(EMPTY_STATE);
  const [query, setQuery] = useState("");
  const [useRerank, setUseRerank] = useState(true);
  const [compareMode, setCompareMode] = useState(false);
  const [compareNoRerank, setCompareNoRerank] = useState<PipelineState | null>(null);
  const [theoryStage, setTheoryStage] = useState<StageKey | null>(null);
  const [hoverChunk, setHoverChunk] = useState<{ chunk: StageHit; x: number; y: number } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { triggerStage, reset: resetTimeline } = usePipelineTimeline();

  // Trigger GSAP stage animations whenever the pipeline step changes.
  useEffect(() => {
    const step = state.step;
    if (step !== "idle" && step !== "error") {
      triggerStage(step as PipelineStage);
    }
  }, [state.step, triggerStage]);

  const examples = useMemo(
    () => [
      "What is the on-call rotation at TechNova?",
      "What training is mandatory every year?",
      "Summarize Q4 revenue.",
      "What was the November security incident?",
      "What are the salary bands at TechNova?",
    ],
    []
  );

  const inspect = async (q?: string) => {
    const text = (q ?? query).trim();
    if (!text) return;
    setQuery(text);
    setState({ ...EMPTY_STATE, query: text, step: "embed" });
    setCompareNoRerank(null);

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await runInspection(text, useRerank, setState, ctrl.signal);
      // If compare is on, also run with rerank OFF.
      if (compareMode && useRerank) {
        const compareState: PipelineState = { ...EMPTY_STATE, query: text, step: "embed" };
        const setCmp = (updater: (s: PipelineState) => PipelineState) => {
          const next = updater(compareState);
          Object.assign(compareState, next);
          setCompareNoRerank({ ...next });
        };
        await runInspection(text, false, setCmp as any, ctrl.signal);
      }
    } catch (e) {
      if ((e as any).name !== "AbortError") {
        toast.error(`Inspection failed: ${(e as Error).message}`);
        setState((s) => ({ ...s, step: "error" }));
      }
    }
  };

  const reset = () => {
    abortRef.current?.abort();
    setState(EMPTY_STATE);
    setCompareNoRerank(null);
    setQuery("");
    resetTimeline();
  };

  return (
    <div className="min-h-screen w-full bg-bg text-fg overflow-x-hidden">
      <PublicHeader />

      <main className="max-w-6xl mx-auto px-5 py-8">
        <Hero />

        <SystemFlow step={state.step} />

        <QueryBar
          query={query}
          setQuery={setQuery}
          onInspect={() => inspect()}
          onReset={reset}
          step={state.step}
          examples={examples}
          onPickExample={(q) => inspect(q)}
          useRerank={useRerank}
          setUseRerank={setUseRerank}
          compareMode={compareMode}
          setCompareMode={setCompareMode}
        />

        <FlowDiagram step={state.step} />

        {state.step === "idle" ? (
          <IntroPanel onTheoryOpen={(k) => setTheoryStage(k)} />
        ) : (
          <div className={cn("mt-6", compareMode && compareNoRerank ? "grid grid-cols-1 lg:grid-cols-2 gap-4" : "")}>
            <RunBlock
              state={state}
              label={compareMode ? "WITH RERANK" : null}
              onTheoryOpen={(k) => setTheoryStage(k)}
              onChunkHover={setHoverChunk}
            />
            {compareMode && compareNoRerank && (
              <RunBlock
                state={compareNoRerank}
                label="WITHOUT RERANK"
                onTheoryOpen={(k) => setTheoryStage(k)}
                onChunkHover={setHoverChunk}
              />
            )}
          </div>
        )}
      </main>

      <AnimatePresence>
        {theoryStage && (
          <TheoryModal stageKey={theoryStage} onClose={() => setTheoryStage(null)} />
        )}
      </AnimatePresence>

      {hoverChunk && (
        <ChunkPopover
          chunk={hoverChunk.chunk}
          query={state.query}
          x={hoverChunk.x}
          y={hoverChunk.y}
          onClose={() => setHoverChunk(null)}
        />
      )}
    </div>
  );
}

// ============================================================================
// Public Header (mini, since this page is pre-auth)
// ============================================================================

function PublicHeader() {
  return (
    <header className="border-b border-border bg-white/85 backdrop-blur sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-5 py-3 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5 group">
          <ChevronLeft className="w-4 h-4 text-fg-subtle group-hover:text-fg transition-colors" />
          <div className="w-7 h-7 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center">
            <Shield className="w-3.5 h-3.5 text-accent" strokeWidth={1.75} />
          </div>
          <span className="text-[14px] font-semibold tracking-tight">Prism RAG</span>
        </Link>
        <Link
          to="/signin"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-accent text-white text-[12px] font-semibold hover:bg-accent/90 transition-colors"
        >
          <LogIn className="w-3.5 h-3.5" strokeWidth={2.25} />
          Sign in
        </Link>
      </div>
    </header>
  );
}

// ============================================================================
// Hero
// ============================================================================

function Hero() {
  return (
    <div className="text-center mb-7">
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-soft border border-accent/20 text-[10.5px] font-semibold uppercase tracking-wider text-accent mb-3">
        <Cpu className="w-3 h-3" strokeWidth={2.25} />
        Pipeline Lab · Public Showcase
      </div>
      <h1 className="text-[34px] sm:text-[42px] font-semibold tracking-tight leading-[1.1]">
        See the entire RAG pipeline,{" "}
        <span className="bg-gradient-to-br from-accent to-[#9387ff] bg-clip-text text-transparent">
          live
        </span>
        .
      </h1>
      <p className="text-[14.5px] text-fg-muted mt-3 max-w-2xl mx-auto leading-relaxed">
        Type any question. Watch the query flow through 7 real stages —
        embedding, dense retrieval, BM25, RRF fusion, cross-encoder rerank,
        grounded generation, and the faithfulness judge. Every chart is real
        data from the running system, no auth required.
      </p>
    </div>
  );
}

// ============================================================================
// Query Bar
// ============================================================================

function QueryBar({
  query,
  setQuery,
  onInspect,
  onReset,
  step,
  examples,
  onPickExample,
  useRerank,
  setUseRerank,
  compareMode,
  setCompareMode,
}: {
  query: string;
  setQuery: (s: string) => void;
  onInspect: () => void;
  onReset: () => void;
  step: PipelineState["step"];
  examples: string[];
  onPickExample: (q: string) => void;
  useRerank: boolean;
  setUseRerank: (v: boolean) => void;
  compareMode: boolean;
  setCompareMode: (v: boolean) => void;
}) {
  const running = step !== "idle" && step !== "done" && step !== "error";
  return (
    <div className="rounded-xl border border-border bg-white shadow-sm p-4">
      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onInspect();
          }}
          placeholder="Ask a question to inspect the pipeline…"
          className="flex-1 px-3.5 py-2.5 text-[14px] rounded-md border border-border bg-bg-elevated focus:outline-none focus:border-accent/60"
        />
        <button
          onClick={onInspect}
          disabled={running || !query.trim()}
          className="px-4 py-2.5 rounded-md bg-accent text-white text-[13px] font-semibold hover:bg-accent/90 disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          <Zap className="w-3.5 h-3.5" strokeWidth={2.5} />
          {running ? "Running…" : "Inspect"}
        </button>
        {(step === "done" || step === "error") && (
          <button
            onClick={onReset}
            className="px-3 py-2.5 rounded-md border border-border text-[13px] text-fg-muted hover:text-fg hover:bg-bg-subtle"
          >
            Reset
          </button>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-2 flex-wrap text-[11px] text-fg-subtle">
        <span>Try:</span>
        {examples.map((q) => (
          <button
            key={q}
            onClick={() => onPickExample(q)}
            disabled={running}
            className="px-2 py-0.5 rounded-full border border-border bg-white hover:border-accent/50 hover:text-accent transition-colors disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-border flex items-center gap-4 flex-wrap text-[11.5px] text-fg-muted">
        <Toggle
          on={useRerank}
          onChange={setUseRerank}
          label="Cross-encoder rerank"
          disabled={running}
        />
        <Toggle
          on={compareMode}
          onChange={setCompareMode}
          label="Compare mode (rerank ON vs OFF, side by side)"
          disabled={running}
          accent
        />
      </div>
    </div>
  );
}

function Toggle({
  on,
  onChange,
  label,
  disabled,
  accent,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  accent?: boolean;
}) {
  return (
    <label className={cn("inline-flex items-center gap-2 cursor-pointer", disabled && "opacity-50 cursor-not-allowed")}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange(!on)}
        className={cn(
          "w-7 h-4 rounded-full transition-colors relative",
          on ? (accent ? "bg-accent" : "bg-emerald-500") : "bg-bg-subtle border border-border"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-all",
            on ? "left-3.5" : "left-0.5"
          )}
        />
      </button>
      <span className="text-fg">{label}</span>
    </label>
  );
}

// ============================================================================
// System Flow — full architectural diagram of the whole RAG system
// ============================================================================
// This is the "what's actually running" picture: every component, the
// data flow between them, the parallel retrieval branch, the RBAC layer,
// post-hoc verification — all on one canvas. Hover any node for an
// in-context explanation; the active stage of an in-flight query pulses.

interface FlowNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  subtitle?: string;
  layer: "input" | "preprocess" | "embed" | "retrieve" | "fuse" | "rerank" | "generate" | "judge" | "output";
  stageKey?: PipelineState["step"];
  detail: string;
}

const LAYER_COLOR: Record<FlowNode["layer"], { fill: string; stroke: string; text: string }> = {
  input:      { fill: "#eef2ff", stroke: "#6366f1", text: "#3730a3" },
  preprocess: { fill: "#fdf4ff", stroke: "#a855f7", text: "#7e22ce" },
  embed:      { fill: "#eff6ff", stroke: "#3b82f6", text: "#1d4ed8" },
  retrieve:   { fill: "#fff7ed", stroke: "#f97316", text: "#c2410c" },
  fuse:       { fill: "#faf5ff", stroke: "#a855f7", text: "#7e22ce" },
  rerank:     { fill: "#fffbeb", stroke: "#f59e0b", text: "#b45309" },
  generate:   { fill: "#ecfdf5", stroke: "#22c55e", text: "#15803d" },
  judge:      { fill: "#fef2f2", stroke: "#ef4444", text: "#b91c1c" },
  output:     { fill: "#f0fdfa", stroke: "#14b8a6", text: "#0f766e" },
};

const FLOW_NODES: FlowNode[] = [
  { id: "user", layer: "input", x: 20, y: 200, w: 88, h: 50, title: "User", subtitle: "asks a question",
    detail: "Any signed-in user — guest, employee, manager, or executive. Their JWT carries a clearance level (L1–L4) that gates every retrieval downstream." },
  { id: "query", layer: "input", x: 145, y: 200, w: 110, h: 50, title: "Query", subtitle: "+ chat history",
    detail: "Raw text plus the full chat history of the current thread. History is what makes the next step possible — without it, follow-ups like 'tell me more' cannot be expanded." },
  { id: "ctx", layer: "preprocess", x: 290, y: 110, w: 120, h: 50, title: "Contextualize", subtitle: "LLM rewrite",
    detail: "If the query is a follow-up (\"tell me more\", pronouns), an LLM call rewrites it into a self-contained question using chat history. Skipped for substantive standalone queries." },
  { id: "mq", layer: "preprocess", x: 290, y: 200, w: 120, h: 50, title: "Multi-query", subtitle: "1 → 3 variants (opt-in)",
    detail: "Optional fan-out: a single query is rewritten into 3 alternative phrasings with synonym, keyword, and HyDE-style variations. Each gets its own retrieval pass; results are RRF-fused." },
  { id: "embed", layer: "embed", x: 290, y: 290, w: 120, h: 50, title: "Embed", subtitle: "BGE / MiniLM",
    detail: "Sentence transformer encodes the query into a dense vector (384 or 768 dims depending on model). This is the geometry the dense retriever searches." },
  { id: "rbac", layer: "retrieve", x: 450, y: 200, w: 110, h: 50, title: "RBAC Filter", subtitle: "doc_level ≤ user.level",
    detail: "Hard pre-filter applied to every retrieval call. Chunks above the caller's clearance, plus any doc the exec has explicitly hidden for this role, are physically unreachable — not just hidden in the UI." },
  { id: "qdrant", layer: "retrieve", x: 600, y: 110, w: 130, h: 56, title: "Qdrant", subtitle: "dense cosine search",
    detail: "Vector database. Computes cosine similarity between the query vector and every chunk vector, RBAC pre-filter applied. Returns top-N most-semantically-similar chunks." },
  { id: "bm25", layer: "retrieve", x: 600, y: 290, w: 130, h: 56, title: "BM25", subtitle: "lexical / TF-IDF",
    detail: "Inverted-index keyword search. Scores chunks by term overlap with the query, normalised by chunk length and term rarity. Strong on proper nouns, codes, and rare jargon dense vectors smooth over." },
  { id: "rrf", layer: "fuse", x: 770, y: 200, w: 120, h: 56, title: "RRF Fusion", subtitle: "rank-based merge",
    detail: "Reciprocal Rank Fusion combines the two ranked lists: score = Σ 1 / (60 + rank). No score calibration needed — chunks ranked high by either retriever rise to the top." },
  { id: "rerank", layer: "rerank", x: 920, y: 200, w: 130, h: 56, title: "Cross-Encoder", subtitle: "BGE-reranker",
    detail: "Reads (query, chunk) pairs jointly through a transformer. Far more accurate than independent embeddings — but one forward pass per pair, so we only run it on the fused top-10." },
  { id: "prompt", layer: "generate", x: 770, y: 320, w: 280, h: 50, title: "Prompt Assembly", subtitle: "system + history + chunks + query",
    detail: "Top-K reranked chunks are stitched into a strict system prompt: answer ONLY from the provided context, cite as [Source N], refuse if the chunks don't support an answer." },
  { id: "llm", layer: "generate", x: 600, y: 410, w: 200, h: 56, title: "Generation LLM", subtitle: "gpt-4o-mini · streamed",
    detail: "OpenAI gpt-4o-mini generates the grounded answer, streamed token-by-token to the user. Bound by the prompt to use only the cited chunks." },
  { id: "judge", layer: "judge", x: 320, y: 410, w: 200, h: 56, title: "Faithfulness Judge", subtitle: "second LLM call · 0..1",
    detail: "A second LLM call asks: is every claim in the answer supported by the cited chunks? Returns a 0..1 score. Low scores trigger our post-hoc demotion — answer reclassified as 'No confident answer'." },
  { id: "answer", layer: "output", x: 40, y: 410, w: 200, h: 56, title: "Final Answer", subtitle: "+ sources · + faithfulness",
    detail: "Streamed answer with inline [Source N] citations, plus a faithfulness score and the sources panel. If demoted, the sources are hidden and the answer becomes a 'No confident answer' card." },
];

const FLOW_EDGES: { from: string; to: string; label?: string; bend?: number }[] = [
  { from: "user", to: "query" },
  { from: "query", to: "ctx", bend: -25 },
  { from: "query", to: "mq" },
  { from: "query", to: "embed", bend: 25 },
  { from: "ctx", to: "rbac", bend: 25 },
  { from: "mq", to: "rbac" },
  { from: "embed", to: "rbac", bend: -25 },
  { from: "rbac", to: "qdrant", bend: -20 },
  { from: "rbac", to: "bm25", bend: 20 },
  { from: "qdrant", to: "rrf", bend: 20 },
  { from: "bm25", to: "rrf", bend: -20 },
  { from: "rrf", to: "rerank" },
  { from: "rerank", to: "prompt", bend: -10 },
  { from: "prompt", to: "llm", bend: -10 },
  { from: "llm", to: "judge" },
  { from: "judge", to: "answer" },
  { from: "answer", to: "user", bend: 30, label: "renders to" },
];

function SystemFlow({ step }: { step: PipelineState["step"] }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const stageToFlowNode: Partial<Record<PipelineState["step"], string>> = {
    embed: "embed",
    dense: "qdrant",
    bm25: "bm25",
    rrf: "rrf",
    rerank: "rerank",
    generate: "llm",
    judge: "judge",
  };
  const activeNodeId = stageToFlowNode[step];
  const nodeMap = useMemo(
    () => Object.fromEntries(FLOW_NODES.map((n) => [n.id, n])),
    []
  );

  const edgePath = (
    fromN: FlowNode,
    toN: FlowNode,
    bend: number
  ): { d: string; mid: { x: number; y: number } } => {
    const fx = fromN.x + fromN.w;
    const fy = fromN.y + fromN.h / 2;
    const tx = toN.x;
    const ty = toN.y + toN.h / 2;
    // For nodes laid out vertically (e.g., output → user wraparound),
    // route as a curve underneath the canvas.
    if (toN.x < fromN.x) {
      // wrap-around (answer → user): curve down then back left
      const my = Math.max(fy, ty) + 80;
      const d = `M ${fx - 4} ${fy} C ${fx + 80} ${my}, ${tx - 80} ${my}, ${tx + toN.w + 4} ${ty}`;
      return { d, mid: { x: (fx + tx) / 2, y: my } };
    }
    const cx1 = (fx + tx) / 2;
    const cx2 = (fx + tx) / 2;
    const my = (fy + ty) / 2 + bend;
    const d = `M ${fx} ${fy} C ${cx1} ${fy + bend}, ${cx2} ${ty + bend}, ${tx} ${ty}`;
    return { d, mid: { x: cx1, y: my } };
  };

  return (
    <div className="rounded-xl border border-border bg-white shadow-sm overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-border bg-gradient-to-r from-indigo-50 via-white to-emerald-50">
        <div className="text-[10px] uppercase tracking-wider font-bold text-indigo-700">
          System Flow
        </div>
        <div className="text-[14.5px] font-semibold text-fg mt-0.5">
          The complete Prism RAG architecture, end-to-end
        </div>
        <div className="text-[12px] text-fg-muted mt-1 leading-relaxed">
          Hover any component to see what it does. When you press <b>Inspect</b>,
          the node currently processing the query lights up — so you can watch the
          query physically move through the system in real time.
        </div>
      </div>
      <div className="relative">
        <svg
          viewBox="0 0 1100 510"
          className="w-full h-auto block"
          style={{ background: "linear-gradient(180deg, #fcfdff 0%, #f5f7fb 100%)" }}
        >
          <defs>
            <marker
              id="arrowhead"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
            </marker>
            <marker
              id="arrowhead-active"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#7c6cff" />
            </marker>
            {/* Subtle dotted pattern background */}
            <pattern id="dotgrid" width="14" height="14" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="0.7" fill="rgba(100,110,140,0.13)" />
            </pattern>
          </defs>
          <rect width="1100" height="510" fill="url(#dotgrid)" opacity="0.5" />

          {/* Edges drawn first (under nodes) */}
          {FLOW_EDGES.map((edge, i) => {
            const fromN = nodeMap[edge.from];
            const toN = nodeMap[edge.to];
            if (!fromN || !toN) return null;
            const isActive =
              activeNodeId === edge.to ||
              (activeNodeId === edge.from && step !== "done");
            const { d, mid } = edgePath(fromN, toN, edge.bend ?? 0);
            return (
              <g key={i}>
                <path
                  d={d}
                  fill="none"
                  stroke={isActive ? "#7c6cff" : "#cbd5e1"}
                  strokeWidth={isActive ? 2 : 1.4}
                  markerEnd={isActive ? "url(#arrowhead-active)" : "url(#arrowhead)"}
                  opacity={isActive ? 1 : 0.85}
                />
                {edge.label && (
                  <text
                    x={mid.x}
                    y={mid.y - 4}
                    textAnchor="middle"
                    fontSize="9.5"
                    fill="#64748b"
                    fontStyle="italic"
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {FLOW_NODES.map((n) => {
            const c = LAYER_COLOR[n.layer];
            const isActive = activeNodeId === n.id && step !== "done";
            const isHovered = hovered === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x}, ${n.y})`}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "pointer" }}
              >
                {isActive && (
                  <rect
                    x={-5}
                    y={-5}
                    width={n.w + 10}
                    height={n.h + 10}
                    rx={11}
                    fill="none"
                    stroke={c.stroke}
                    strokeWidth={2.5}
                    opacity={0.55}
                  >
                    <animate
                      attributeName="opacity"
                      values="0.2;0.7;0.2"
                      dur="1.4s"
                      repeatCount="indefinite"
                    />
                  </rect>
                )}
                <rect
                  width={n.w}
                  height={n.h}
                  rx={8}
                  fill={c.fill}
                  stroke={c.stroke}
                  strokeWidth={isHovered ? 2 : 1.4}
                  filter={isHovered ? "drop-shadow(0 4px 10px rgba(40,50,90,0.10))" : "drop-shadow(0 1px 3px rgba(40,50,90,0.05))"}
                />
                <text
                  x={n.w / 2}
                  y={n.subtitle ? n.h / 2 - 4 : n.h / 2 + 4}
                  textAnchor="middle"
                  fontSize="12.5"
                  fontWeight="700"
                  fill={c.text}
                >
                  {n.title}
                </text>
                {n.subtitle && (
                  <text
                    x={n.w / 2}
                    y={n.h / 2 + 12}
                    textAnchor="middle"
                    fontSize="9.5"
                    fontWeight="500"
                    fill={c.text}
                    opacity="0.7"
                  >
                    {n.subtitle}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {/* Hover tooltip — positioned via percentages of the SVG viewBox */}
        {hovered && nodeMap[hovered] && (
          <div
            className="absolute pointer-events-none rounded-md bg-slate-900 text-white text-[11.5px] leading-relaxed px-3 py-2 shadow-xl w-72 z-10"
            style={{
              left: `${
                Math.max(
                  4,
                  Math.min(
                    96,
                    ((nodeMap[hovered].x + nodeMap[hovered].w / 2) / 1100) * 100
                  )
                )
              }%`,
              top: `${((nodeMap[hovered].y + nodeMap[hovered].h + 14) / 510) * 100}%`,
              transform: "translateX(-50%)",
            }}
          >
            <div className="font-semibold text-[12px] mb-0.5">{nodeMap[hovered].title}</div>
            <div className="text-white/85">{nodeMap[hovered].detail}</div>
          </div>
        )}
      </div>
      <div className="px-4 py-2.5 border-t border-border bg-bg-subtle/50 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[10.5px] text-fg-muted">
        <div className="font-semibold text-fg-subtle uppercase tracking-wider text-[9.5px]">Layers:</div>
        {[
          { l: "input", t: "Input" },
          { l: "preprocess", t: "Preprocess" },
          { l: "embed", t: "Embed" },
          { l: "retrieve", t: "Retrieve + RBAC" },
          { l: "fuse", t: "Fusion" },
          { l: "rerank", t: "Rerank" },
          { l: "generate", t: "Generate" },
          { l: "judge", t: "Verify" },
          { l: "output", t: "Output" },
        ].map(({ l, t }) => (
          <span key={l} className="inline-flex items-center gap-1">
            <span
              className="w-2.5 h-2.5 rounded-sm"
              style={{
                background: LAYER_COLOR[l as FlowNode["layer"]].fill,
                border: `1.5px solid ${LAYER_COLOR[l as FlowNode["layer"]].stroke}`,
              }}
            />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// Animated Flow Diagram (top — particles flow on edges)
// ============================================================================

function FlowDiagram({ step }: { step: PipelineState["step"] }) {
  const stageOrder: StageKey[] = ["embed", "dense", "bm25", "rrf", "rerank", "generate", "judge"];
  const stepRank: Record<PipelineState["step"], number> = {
    idle: -1,
    embed: 0,
    dense: 1,
    bm25: 2,
    rrf: 3,
    rerank: 4,
    generate: 5,
    judge: 6,
    done: 7,
    error: -1,
  };
  const reached = stepRank[step];

  return (
    <div className="my-6 rounded-xl border border-border bg-white shadow-sm p-4 overflow-x-auto">
      <div className="flex items-center justify-between gap-1 min-w-[860px]">
        {stageOrder.map((k, i) => {
          const stage = STAGES.find((s) => s.key === k)!;
          const Icon = stage.icon;
          const isActive = i === reached;
          const isReached = i <= reached;
          return (
            <div key={k} className="flex items-center" style={{ flex: i === stageOrder.length - 1 ? "0 0 auto" : "1 1 0" }}>
              <motion.div
                animate={
                  isActive
                    ? { scale: [1, 1.08, 1], boxShadow: ["0 0 0 0 rgba(124,108,255,0)", "0 0 0 8px rgba(124,108,255,0.18)", "0 0 0 0 rgba(124,108,255,0)"] }
                    : { scale: 1 }
                }
                transition={{ duration: 1.2, repeat: isActive ? Infinity : 0 }}
                className={cn(
                  "flex flex-col items-center text-center relative shrink-0",
                  isReached ? "" : "opacity-40"
                )}
              >
                <div
                  className="w-11 h-11 rounded-full border-[2.5px] flex items-center justify-center"
                  style={{
                    borderColor: isReached ? stage.color : "#d8dde9",
                    background: isReached ? stage.color + "15" : "#fff",
                  }}
                >
                  <Icon
                    className="w-5 h-5"
                    strokeWidth={2}
                    style={{ color: isReached ? stage.color : "#9aa1b3" }}
                  />
                </div>
                <div
                  className="text-[10px] font-semibold mt-1.5 uppercase tracking-wider"
                  style={{ color: isReached ? stage.color : "#9aa1b3" }}
                >
                  {stage.title.split(" ")[0]}
                </div>
              </motion.div>
              {i < stageOrder.length - 1 && (
                <div className="relative h-1 mx-2 flex-1 rounded-full bg-bg-subtle overflow-hidden">
                  <motion.div
                    initial={{ width: "0%" }}
                    animate={{ width: i < reached ? "100%" : i === reached ? "60%" : "0%" }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                    className="absolute inset-y-0 left-0"
                    style={{
                      background: `linear-gradient(90deg, ${STAGES[i].color}, ${STAGES[i + 1].color})`,
                    }}
                  />
                  {i === reached && (
                    <motion.span
                      className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full"
                      style={{ background: STAGES[i + 1].color, boxShadow: `0 0 8px ${STAGES[i + 1].color}` }}
                      initial={{ left: "-5%", opacity: 0 }}
                      animate={{ left: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
                      transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================================
// Intro Panel (when idle)
// ============================================================================

function IntroPanel({ onTheoryOpen }: { onTheoryOpen: (k: StageKey) => void }) {
  return (
    <div className="mt-2">
      <div className="text-center max-w-2xl mx-auto py-6">
        <div className="text-[13px] text-fg-muted leading-relaxed">
          Each stage card below will fill in with the live data once you press
          <b className="text-fg"> Inspect</b>. Click the{" "}
          <HelpCircle className="w-3.5 h-3.5 inline -mt-0.5 text-accent" />{" "}
          icon on any card for a deep-dive into the algorithm.
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {STAGES.map((s) => {
          const Icon = s.icon;
          return (
            <button
              key={s.key}
              onClick={() => onTheoryOpen(s.key)}
              className="text-left rounded-xl border border-border bg-white p-3.5 shadow-sm hover:border-accent/40 hover:shadow transition-all group"
            >
              <div className="flex items-center gap-2">
                <div
                  className="w-8 h-8 rounded-md flex items-center justify-center"
                  style={{ background: s.color + "1a" }}
                >
                  <Icon className="w-4 h-4" strokeWidth={2} style={{ color: s.color }} />
                </div>
                <div className="text-[10.5px] uppercase tracking-wider text-fg-subtle font-semibold">
                  Stage {s.n}
                </div>
                <HelpCircle className="w-3 h-3 text-fg-subtle ml-auto group-hover:text-accent transition-colors" strokeWidth={2} />
              </div>
              <div className="font-semibold text-[13.5px] mt-2" style={{ color: s.color }}>
                {s.title}
              </div>
              <div className="text-[11px] text-fg-muted mt-0.5 leading-snug">
                {s.tagline}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================================
// Run Block — the live results column
// ============================================================================

function RunBlock({
  state,
  label,
  onTheoryOpen,
  onChunkHover,
}: {
  state: PipelineState;
  label: string | null;
  onTheoryOpen: (k: StageKey) => void;
  onChunkHover: (h: { chunk: StageHit; x: number; y: number } | null) => void;
}) {
  return (
    <div className="space-y-4">
      {label && (
        <div className="text-center text-[10.5px] uppercase tracking-wider font-bold text-accent bg-accent-soft border border-accent/30 rounded px-2 py-1">
          {label}
        </div>
      )}

      {/* GSAP-animated progress bar — fills segment-by-segment as stages complete */}
      <PipelineProgressBar />

      <RunHeader state={state} />

      <StageCard
        stage={STAGES[0]}
        revealed={state.step !== "idle" && state.step !== "embed"}
        loading={state.step === "embed"}
        latencyMs={state.embedMs}
        onTheoryOpen={onTheoryOpen}
        taglineOverride={state.embedModel || undefined}
      >
        {state.embedVec ? <EmbeddingFingerprint vec={state.embedVec} model={state.embedModel} /> : <Loading />}
      </StageCard>

      <StageCard
        stage={STAGES[1]}
        revealed={state.dense.length > 0 || ["rrf", "rerank", "generate", "judge", "done"].includes(state.step)}
        loading={state.step === "dense"}
        latencyMs={state.denseMs}
        onTheoryOpen={onTheoryOpen}
      >
        <HitList hits={state.dense} color={STAGES[1].color} onHover={onChunkHover} />
      </StageCard>

      <StageCard
        stage={STAGES[2]}
        revealed={state.bm25.length > 0 || ["rrf", "rerank", "generate", "judge", "done"].includes(state.step)}
        loading={state.step === "bm25"}
        latencyMs={state.bm25Ms}
        onTheoryOpen={onTheoryOpen}
      >
        <HitList hits={state.bm25} color={STAGES[2].color} onHover={onChunkHover} />
      </StageCard>

      <StageCard
        stage={STAGES[3]}
        revealed={state.rrf.length > 0 || ["rerank", "generate", "judge", "done"].includes(state.step)}
        loading={state.step === "rrf"}
        latencyMs={state.rrfMs}
        onTheoryOpen={onTheoryOpen}
      >
        <HitList hits={state.rrf} color={STAGES[3].color} onHover={onChunkHover} />
      </StageCard>

      {state.rerank.length > 0 && (
        <>
          <StageCard
            stage={STAGES[4]}
            revealed
            loading={false}
            latencyMs={state.rerankMs}
            onTheoryOpen={onTheoryOpen}
            taglineOverride={state.rerankModel || undefined}
          >
            <HitList hits={state.rerank} color={STAGES[4].color} onHover={onChunkHover} />
          </StageCard>

          <RankJourney dense={state.dense} bm25={state.bm25} rrf={state.rrf} rerank={state.rerank} />
        </>
      )}

      <StageCard
        stage={STAGES[5]}
        revealed={state.step === "generate" || state.step === "judge" || state.step === "done"}
        loading={state.step === "generate"}
        latencyMs={state.generateMs}
        onTheoryOpen={onTheoryOpen}
        taglineOverride={state.generateModel ? `${state.generateModel} · cited` : undefined}
      >
        <div className="rounded-md border border-emerald-200 bg-emerald-50/40 p-3 text-[13px] leading-relaxed text-fg whitespace-pre-wrap min-h-[60px]">
          {state.answer || (state.step === "generate" ? <Loading /> : <span className="text-fg-muted italic">no answer yet</span>)}
          {state.step === "generate" && (
            <span className="inline-block w-1.5 h-3 bg-emerald-500/80 ml-0.5 align-middle animate-pulse" />
          )}
        </div>
      </StageCard>

    </div>
  );
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-[12px] text-fg-muted py-3">
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" style={{ animationDelay: "150ms" }} />
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" style={{ animationDelay: "300ms" }} />
      <span className="ml-1">processing…</span>
    </div>
  );
}

// ============================================================================
// Run Header (status + query)
// ============================================================================

function RunHeader({ state }: { state: PipelineState }) {
  return (
    <div className="rounded-xl border border-border bg-white shadow-sm p-4 flex items-center justify-between">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
          Inspecting
        </div>
        <div className="text-[14px] font-semibold text-fg mt-0.5 break-words">
          "{state.query}"
        </div>
      </div>
      <div className="text-right">
        <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
          Status
        </div>
        <div
          className={cn(
            "text-[12.5px] font-semibold mt-0.5 capitalize",
            state.step === "done"
              ? "text-clearance-public"
              : state.step === "error"
              ? "text-clearance-restricted"
              : "text-accent"
          )}
        >
          {state.step === "done"
            ? `Complete · ${state.totalMs}ms`
            : state.step === "error"
            ? "Failed"
            : `${state.step}…`}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Stage Card
// ============================================================================

function StageCard({
  stage,
  revealed,
  loading,
  latencyMs,
  onTheoryOpen,
  children,
  taglineOverride,
}: {
  stage: (typeof STAGES)[number];
  revealed: boolean;
  loading: boolean;
  latencyMs: number | null;
  onTheoryOpen: (k: StageKey) => void;
  children: React.ReactNode;
  taglineOverride?: string;
}) {
  const Icon = stage.icon;
  const tagline = taglineOverride || stage.tagline;
  const stageIndex = STAGES.findIndex((s) => s.key === stage.key);

  if (!revealed) return null;

  return (
    <StageReveal
      active={loading}
      completed={revealed && !loading}
      index={stageIndex}
      color={stage.color}
    >
      <div
        className="overflow-hidden"
        data-pipeline-node={stage.key}
      >
        <div className="px-4 py-3 border-b border-border flex items-start gap-3">
          <div
            className="w-9 h-9 rounded-md flex items-center justify-center text-[13px] font-bold border shrink-0"
            style={{
              background: stage.color + "16",
              borderColor: stage.color + "40",
              color: stage.color,
            }}
          >
            {stage.n}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Icon className="w-4 h-4" strokeWidth={1.75} style={{ color: stage.color }} />
              <TextReveal
                text={stage.title}
                active={loading || (revealed && !loading)}
                className="font-semibold text-fg text-[14px]"
                stagger={0.025}
              />
              <span className="text-[11px] text-fg-muted truncate" title={tagline}>· {tagline}</span>
              <button
                onClick={() => onTheoryOpen(stage.key)}
                className="ml-auto text-fg-subtle hover:text-accent transition-colors shrink-0"
                title="Theory deep-dive"
              >
                <HelpCircle className="w-4 h-4" strokeWidth={2} />
              </button>
            </div>
            <div className="text-[12px] text-fg-muted mt-1 leading-relaxed">
              {stage.explainer}
            </div>
            <div className="text-[11px] text-fg-subtle mt-1 italic">{stage.why}</div>
          </div>
          {latencyMs !== null && latencyMs > 0 && (
            <div className="text-right shrink-0 ml-2">
              <div className="text-[9.5px] uppercase tracking-wider text-fg-subtle font-semibold">
                Latency
              </div>
              <CountUp
                value={latencyMs}
                suffix="ms"
                duration={0.8}
                className="font-mono text-[12.5px] font-semibold text-fg"
              />
            </div>
          )}
        </div>
        <div className="p-3.5">{loading ? <Loading /> : children}</div>
      </div>
    </StageReveal>
  );
}

// ============================================================================
// Embedding Fingerprint — radial waveform of 768 dims
// ============================================================================

function EmbeddingFingerprint({ vec, model }: { vec: number[]; model: string }) {
  // Render the embedding as a 2D heatmap. Each cell is one dimension of
  // the live vector. Diverging colour scale reveals the sign + magnitude
  // pattern at a glance — and unlike a polar plot it always renders
  // reliably regardless of container size.
  const option = useMemo(() => {
    const N = vec.length;
    const cols = 32;
    const rows = Math.ceil(N / cols);
    const max = Math.max(...vec.map(Math.abs)) || 1;
    const data: [number, number, number][] = [];
    for (let i = 0; i < N; i++) {
      const r = Math.floor(i / cols);
      const c = i % cols;
      data.push([c, rows - 1 - r, vec[i]]);
    }
    return {
      animation: false,
      tooltip: {
        position: "top",
        formatter: (p: any) => {
          const idx = (rows - 1 - p.value[1]) * cols + p.value[0];
          return `dim <b>${idx}</b>: ${p.value[2].toFixed(4)}`;
        },
      },
      grid: { left: 4, right: 4, top: 6, bottom: 6, containLabel: false },
      xAxis: { type: "category", show: false, data: Array.from({ length: cols }, (_, i) => i) },
      yAxis: { type: "category", show: false, data: Array.from({ length: rows }, (_, i) => i) },
      visualMap: {
        show: false,
        min: -max,
        max: max,
        calculable: true,
        inRange: {
          color: [
            "#f97316", // strongly negative
            "#fdba74",
            "#fef3c7",
            "#e0e7ff",
            "#a5b4fc",
            "#7c6cff", // strongly positive
          ],
        },
      },
      series: [
        {
          type: "heatmap",
          data,
          progressive: 0,
          itemStyle: { borderColor: "#fff", borderWidth: 0.5 },
          emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(124,108,255,0.5)" } },
        },
      ],
    };
  }, [vec]);

  const norm = useMemo(
    () => Math.sqrt(vec.reduce((a, b) => a + b * b, 0)),
    [vec]
  );

  return (
    <div>
      <div className="flex items-center gap-3 text-[11px] text-fg-muted mb-2 flex-wrap">
        <span>
          Model: <b className="text-fg font-mono">{model}</b>
        </span>
        <span>
          Dims: <b className="text-fg font-mono">{vec.length}</b>
        </span>
        <span>
          ‖v‖₂: <b className="text-fg font-mono">{norm.toFixed(3)}</b>
        </span>
        <span className="ml-auto inline-flex items-center gap-3 text-[10px]">
          <span className="inline-flex items-center gap-1">
            <span className="w-3 h-2.5 rounded-sm" style={{ background: "#f97316" }} /> negative
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-3 h-2.5 rounded-sm" style={{ background: "#7c6cff" }} /> positive
          </span>
        </span>
      </div>
      <div className="rounded-md border border-border bg-bg-subtle p-2">
        <ReactECharts
          option={option}
          notMerge
          style={{ height: 160, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
      </div>
      <div className="text-[10.5px] text-fg-subtle mt-1.5 leading-relaxed">
        Each cell is one of the {vec.length} dimensions of the live embedding
        for your query. Diverging colour encodes sign &amp; magnitude — purple is
        positive, orange is negative, paler is closer to zero. Two semantically
        similar queries produce similar patterns; this is the geometry the
        retriever searches.
      </div>
    </div>
  );
}

// ============================================================================
// Hit List with hover popover triggers
// ============================================================================

function HitList({
  hits,
  color,
  onHover,
}: {
  hits: StageHit[];
  color: string;
  onHover: (h: { chunk: StageHit; x: number; y: number } | null) => void;
}) {
  if (!hits.length) {
    return (
      <div className="text-[12px] text-fg-muted italic text-center py-3">
        no hits in this stage
      </div>
    );
  }
  const max = Math.max(...hits.map((h) => Math.abs(h.score)), 0.0001);
  return (
    <div className="space-y-1.5">
      {hits.slice(0, 8).map((h) => (
        <div
          key={`${h.chunk_id}-${h.rank}`}
          className="grid grid-cols-[24px_1fr_64px] gap-2 items-center text-[11.5px] hover:bg-bg-subtle/60 rounded px-1 py-0.5 cursor-help"
          onMouseEnter={(e) =>
            onHover({ chunk: h, x: e.clientX, y: e.clientY })
          }
          onMouseLeave={() => onHover(null)}
        >
          <span className="text-fg-subtle font-mono text-right">{h.rank}</span>
          <div className="min-w-0">
            <div className="truncate text-fg" title={h.filename}>
              <span className="text-fg-muted">{prettifyFilename(h.filename)}</span>{" "}
              <span className="text-fg-subtle">· p.{h.page}</span>
            </div>
            <div className="h-1 rounded-full bg-bg-subtle overflow-hidden mt-0.5">
              <div
                className="h-full"
                style={{
                  width: `${Math.min(100, (Math.abs(h.score) / max) * 100)}%`,
                  background: color,
                }}
              />
            </div>
          </div>
          <span className="font-mono text-fg text-right">
            {h.score.toFixed(3)}
          </span>
        </div>
      ))}
      {hits.length > 8 && (
        <div className="text-[10.5px] text-fg-subtle text-center pt-1">
          + {hits.length - 8} more
        </div>
      )}
    </div>
  );
}

function prettifyFilename(filename: string): string {
  let s = filename.replace(/\.[a-z0-9]+$/i, "");
  s = s.replace(/^TechNova[_\- ]+/i, "");
  s = s.replace(/[_\-]+/g, " ").trim();
  return s || filename;
}

// ============================================================================
// Chunk Hover Popover (text + highlighted query terms)
// ============================================================================

function ChunkPopover({
  chunk,
  query,
  x,
  y,
  onClose: _onClose,
}: {
  chunk: StageHit;
  query: string;
  x: number;
  y: number;
  onClose: () => void;
}) {
  const terms = useMemo(
    () =>
      query
        .toLowerCase()
        .split(/[^a-z0-9]+/i)
        .filter((t) => t.length > 2),
    [query]
  );
  const highlighted = useMemo(() => {
    if (!terms.length) return chunk.text;
    const parts: { t: string; hit: boolean }[] = [];
    const re = new RegExp(`(${terms.map(escapeRegex).join("|")})`, "gi");
    let last = 0;
    chunk.text.replace(re, (match, _g, offset) => {
      if (offset > last) parts.push({ t: chunk.text.slice(last, offset), hit: false });
      parts.push({ t: match, hit: true });
      last = offset + match.length;
      return match;
    });
    if (last < chunk.text.length) parts.push({ t: chunk.text.slice(last), hit: false });
    return parts;
  }, [chunk.text, terms]);

  const left = Math.min(x + 14, window.innerWidth - 380);
  const top = Math.min(y + 14, window.innerHeight - 260);

  return (
    <div
      className="fixed z-50 pointer-events-none w-[360px]"
      style={{ left, top }}
    >
      <div className="rounded-lg border border-accent/40 bg-white shadow-xl p-3.5 text-[12px]">
        <div className="flex items-center gap-2 mb-2">
          <span
            className="text-[9.5px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
            style={{
              background: classificationColor(chunk.doc_level) + "20",
              color: classificationColor(chunk.doc_level),
            }}
          >
            L{chunk.doc_level} · {classificationLabel(chunk.doc_level)}
          </span>
          <span className="text-fg font-semibold truncate">{prettifyFilename(chunk.filename)}</span>
          <span className="text-fg-subtle text-[10.5px] ml-auto shrink-0">p.{chunk.page}</span>
        </div>
        <div className="rounded bg-bg-subtle border border-border p-2.5 text-[11.5px] font-mono leading-relaxed max-h-44 overflow-y-auto whitespace-pre-wrap">
          {Array.isArray(highlighted)
            ? highlighted.map((p, i) =>
                p.hit ? (
                  <mark key={i} className="bg-yellow-200/80 text-fg rounded px-0.5">
                    {p.t}
                  </mark>
                ) : (
                  <span key={i}>{p.t}</span>
                )
              )
            : highlighted}
        </div>
        <div className="text-[10.5px] text-fg-subtle mt-2">
          chunk {chunk.chunk_index} · score {chunk.score.toFixed(4)}
        </div>
      </div>
    </div>
  );
}

function escapeRegex(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function classificationLabel(level: number): string {
  return ["", "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"][level] || "PUBLIC";
}

function classificationColor(level: number): string {
  return ["#22c55e", "#22c55e", "#3b82f6", "#f59e0b", "#ef4444"][level] || "#22c55e";
}

// ============================================================================
// Rank Journey Bump Chart — chunks moving across stages
// ============================================================================

function RankJourney({
  dense,
  bm25,
  rrf,
  rerank,
}: {
  dense: StageHit[];
  bm25: StageHit[];
  rrf: StageHit[];
  rerank: StageHit[];
}) {
  // High-contrast palette for the surviving "winners" — each chunk gets
  // a distinct, vivid colour so individual journeys are trackable.
  // Indexed by final rerank position (0 = top result).
  const WINNER_PALETTE = ["#7c3aed", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#3b82f6", "#84cc16"];

  const option = useMemo(() => {
    const stages = ["Dense", "BM25", "RRF", "Rerank"];
    const stageData: StageHit[][] = [dense, bm25, rrf, rerank];
    // Collect every chunk that appeared in any stage (top 8 only per stage,
    // so the chart stays readable).
    const chunkIds = new Set<string>();
    stageData.forEach((s) => s.slice(0, 8).forEach((h) => chunkIds.add(h.chunk_id)));

    // Lookup for filenames so tooltips read like real docs, not chunk ids.
    const chunkInfo = new Map<string, { filename: string; page: number; rerankRank: number | null }>();
    Array.from(chunkIds).forEach((cid) => {
      const sample =
        rerank.find((h) => h.chunk_id === cid) ||
        rrf.find((h) => h.chunk_id === cid) ||
        dense.find((h) => h.chunk_id === cid) ||
        bm25.find((h) => h.chunk_id === cid)!;
      chunkInfo.set(cid, {
        filename: prettifyFilename(sample.filename),
        page: sample.page,
        rerankRank: rerank.find((h) => h.chunk_id === cid)?.rank ?? null,
      });
    });

    // Order series so winners draw on top of losers.
    const ordered = Array.from(chunkIds).sort((a, b) => {
      const ar = chunkInfo.get(a)!.rerankRank ?? 999;
      const br = chunkInfo.get(b)!.rerankRank ?? 999;
      return br - ar; // losers first, winners last
    });

    const series = ordered.map((cid) => {
      const info = chunkInfo.get(cid)!;
      const data = stageData.map((stage) => {
        const hit = stage.find((h) => h.chunk_id === cid);
        return hit ? hit.rank : null;
      });
      const winner = info.rerankRank !== null;
      const colour = winner
        ? WINNER_PALETTE[(info.rerankRank! - 1) % WINNER_PALETTE.length]
        : "#94a3b8";
      return {
        name: `${info.filename} · p.${info.page}`,
        type: "line" as const,
        data,
        smooth: false,
        symbol: "circle",
        symbolSize: winner ? 11 : 6,
        connectNulls: true,
        lineStyle: {
          width: winner ? 3 : 1.2,
          color: colour,
          opacity: winner ? 1 : 0.45,
          type: winner ? "solid" : "dashed",
          shadowColor: winner ? colour : "transparent",
          shadowBlur: winner ? 6 : 0,
        },
        itemStyle: {
          color: colour,
          borderColor: "#fff",
          borderWidth: winner ? 2 : 0,
          opacity: winner ? 1 : 0.55,
        },
        emphasis: {
          focus: "series" as const,
          lineStyle: { width: 4.5, opacity: 1, shadowBlur: 12 },
          itemStyle: { opacity: 1 },
        },
        z: winner ? 10 + (8 - (info.rerankRank ?? 0)) : 1,
      };
    });

    const allRanks = stageData.flatMap((s) => s.map((h) => h.rank));
    const maxRank = Math.max(...allRanks, 8);

    return {
      animation: true,
      animationDuration: 600,
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(15,23,42,0.94)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#fff", fontSize: 11.5 },
        padding: [8, 10],
        formatter: (p: any) => {
          const stage = p.name as string;
          const rank = p.data;
          return `<div style="font-weight:600;margin-bottom:3px">${p.seriesName}</div>
                  <div style="opacity:0.8">${stage} → rank <b style="color:${p.color}">${rank ?? "—"}</b></div>`;
        },
      },
      grid: { left: 56, right: 24, top: 12, bottom: 30 },
      xAxis: {
        type: "category",
        data: stages,
        boundaryGap: false,
        axisLabel: { color: "#1f2540", fontSize: 12, fontWeight: 700, margin: 12 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1", width: 1.2 } },
        splitLine: {
          show: true,
          lineStyle: { color: "#e2e8f0", type: "dashed" },
        },
      },
      yAxis: {
        type: "value",
        inverse: true,
        min: 0.5,
        max: maxRank + 0.5,
        interval: 1,
        name: "rank",
        nameLocation: "middle",
        nameGap: 38,
        nameTextStyle: { color: "#475569", fontSize: 10.5, fontWeight: 600 },
        axisLabel: {
          color: "#475569",
          fontSize: 10.5,
          fontWeight: 500,
          formatter: (v: number) => `#${v}`,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "#e2e8f0" } },
      },
      series,
    };
  }, [dense, bm25, rrf, rerank, WINNER_PALETTE]);

  // Build a small legend chip strip so winners are obviously identifiable.
  const winners = rerank
    .slice(0, 8)
    .map((h, i) => ({
      colour: WINNER_PALETTE[i % WINNER_PALETTE.length],
      label: prettifyFilename(h.filename),
      page: h.page,
      finalRank: h.rank,
    }));

  return (
    <div className="rounded-xl border border-border bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-border bg-gradient-to-r from-accent-soft/60 to-transparent flex items-start gap-3">
        <div className="w-9 h-9 rounded-md flex items-center justify-center shrink-0" style={{ background: "#7c3aed1a", border: "1px solid #7c3aed40" }}>
          <Layers className="w-4 h-4" strokeWidth={2} style={{ color: "#7c3aed" }} />
        </div>
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: "#7c3aed" }}>
            Rank Journey
          </div>
          <div className="text-[14px] font-semibold text-fg mt-0.5">
            How each chunk's rank changed across the four retrieval stages
          </div>
          <div className="text-[11.5px] text-fg-muted mt-0.5 leading-relaxed">
            Coloured lines = chunks that survived to the final rerank top-k (the cited sources).
            Dashed grey = first-pass false positives the cross-encoder dropped. Watch for lines that
            crash from low ranks to high — that's the rerank rescuing a great chunk that BM25 + dense missed.
          </div>
        </div>
      </div>
      <div className="px-3 pt-2">
        <ReactECharts
          option={option}
          notMerge
          style={{ height: 280, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
      </div>
      {winners.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-border bg-bg-subtle/40">
          <div className="text-[9.5px] uppercase tracking-wider text-fg-subtle font-semibold mb-1.5">
            Winners (final rerank top-{winners.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {winners.map((w) => (
              <span
                key={`${w.label}-${w.page}-${w.finalRank}`}
                className="inline-flex items-center gap-1.5 rounded-full bg-white border border-border px-2 py-0.5 text-[10.5px] text-fg shadow-sm"
                title={`Rank ${w.finalRank} after rerank`}
              >
                <span
                  className="w-2 h-2 rounded-full shadow-[0_0_5px_currentColor]"
                  style={{ background: w.colour, color: w.colour }}
                />
                <span className="font-semibold">#{w.finalRank}</span>
                <span className="text-fg-muted">{w.label}</span>
                <span className="text-fg-subtle">· p.{w.page}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Faithfulness Gauge
// ============================================================================

function FaithfulnessGauge({ value }: { value: number }) {
  // Hand-built SVG gauge. Pure React + viewBox — always responsive, never
  // clips inside narrow compare-mode columns. The arc sweeps 240° from
  // 7-o'clock through top to 5-o'clock; the colour band reflects the
  // qualitative buckets we actually use for demotion (red <0.5, amber
  // 0.5-0.8, green ≥0.8).
  const pct = Math.max(0, Math.min(1, value));
  const cx = 100;
  const cy = 100;
  const r = 78;
  const startA = (Math.PI * 7) / 6; // 210°
  const sweep = (Math.PI * 8) / 6;  // 240° total
  const endA = startA + sweep;

  const polar = (angle: number, radius: number) => ({
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle),
  });
  const arcPath = (a0: number, a1: number, radius: number) => {
    const p0 = polar(a0, radius);
    const p1 = polar(a1, radius);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M ${p0.x} ${p0.y} A ${radius} ${radius} 0 ${large} 1 ${p1.x} ${p1.y}`;
  };

  // Three-band background arc.
  const bandRed = arcPath(startA, startA + sweep * 0.5, r);
  const bandAmber = arcPath(startA + sweep * 0.5, startA + sweep * 0.8, r);
  const bandGreen = arcPath(startA + sweep * 0.8, endA, r);

  // Foreground progress arc (animated via stroke-dasharray would be
  // overkill; just compute the actual end angle from value).
  const progressEnd = startA + sweep * pct;
  const progressPath = arcPath(startA, progressEnd, r);
  const tipColour = pct >= 0.8 ? "#22c55e" : pct >= 0.5 ? "#f59e0b" : "#ef4444";
  const tipPos = polar(progressEnd, r);

  return (
    <div className="w-full">
      <div className="relative w-full max-w-[280px] mx-auto">
        <svg viewBox="0 0 200 160" className="w-full h-auto block">
          {/* Background bands — full sweep */}
          <path d={bandRed} fill="none" stroke="#fee2e2" strokeWidth="14" strokeLinecap="round" />
          <path d={bandAmber} fill="none" stroke="#fef3c7" strokeWidth="14" strokeLinecap="round" />
          <path d={bandGreen} fill="none" stroke="#dcfce7" strokeWidth="14" strokeLinecap="round" />
          {/* Active progress arc — animates on prop change */}
          <path
            d={progressPath}
            fill="none"
            stroke="#7c6cff"
            strokeWidth="14"
            strokeLinecap="round"
            style={{ filter: "drop-shadow(0 0 6px rgba(124,108,255,0.4))" }}
          />
          {/* Tip dot */}
          <circle cx={tipPos.x} cy={tipPos.y} r="6" fill={tipColour} stroke="#fff" strokeWidth="2.5" />
          {/* Centre value */}
          <text
            x={cx}
            y={cy + 6}
            textAnchor="middle"
            fontSize="28"
            fontWeight="700"
            fill="#111827"
            fontFamily="ui-sans-serif, system-ui, sans-serif"
          >
            {Math.round(pct * 100)}%
          </text>
          <text
            x={cx}
            y={cy + 30}
            textAnchor="middle"
            fontSize="9.5"
            letterSpacing="1.6"
            fontWeight="600"
            fill="#6b7280"
            fontFamily="ui-sans-serif, system-ui, sans-serif"
          >
            FAITHFULNESS
          </text>
        </svg>
      </div>
      <div className="text-[11px] text-fg-muted text-center mt-1 leading-snug px-2">
        {pct >= 0.8
          ? "Strongly grounded — every claim traces back to the cited chunks."
          : pct >= 0.5
          ? "Mostly grounded — the judge flagged minor unsupported phrasing."
          : "Weakly grounded — the answer drifted from the sources."}
      </div>
    </div>
  );
}

// ============================================================================
// Latency Chart
// ============================================================================

function LatencyChart({
  embed,
  dense,
  bm25,
  rrf,
  rerank,
  generate,
  total,
}: {
  embed: number;
  dense: number;
  bm25: number;
  rrf: number;
  rerank: number;
  generate: number;
  total: number;
}) {
  const data = [
    { name: "Embed", value: embed, color: "#6366f1" },
    { name: "Dense", value: dense, color: "#3b82f6" },
    { name: "BM25", value: bm25, color: "#f97316" },
    { name: "RRF", value: rrf, color: "#a855f7" },
    { name: "Rerank", value: rerank, color: "#f59e0b" },
    { name: "Generate", value: generate, color: "#22c55e" },
  ];
  const option = useMemo(
    () => ({
      grid: { left: 70, right: 50, top: 16, bottom: 24 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (p: any[]) => `${p[0].name}: <b>${p[0].value}ms</b>`,
      },
      xAxis: {
        type: "value",
        axisLabel: { color: "#6b7280", fontSize: 10, formatter: "{value}ms" },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      yAxis: {
        type: "category",
        data: data.map((d) => d.name),
        axisLabel: { color: "#374151", fontSize: 11, fontWeight: 500 },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      series: [
        {
          type: "bar",
          data: data.map((d) => ({
            value: d.value,
            itemStyle: { color: d.color, borderRadius: [0, 4, 4, 0] },
          })),
          barWidth: 14,
          label: {
            show: true,
            position: "right",
            color: "#111827",
            fontSize: 10.5,
            fontWeight: 600,
            formatter: "{c}ms",
          },
        },
      ],
    }),
    [data]
  );
  return (
    <div className="rounded-xl border border-border bg-white shadow-sm p-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
            End-to-End Latency
          </div>
          <div className="text-[13.5px] font-semibold text-fg mt-0.5 flex items-center gap-1.5">
            <Activity className="w-4 h-4 text-accent" strokeWidth={2} />
            Total {total}ms
          </div>
        </div>
      </div>
      <ReactECharts
        option={option}
        notMerge
        style={{ height: 220, width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

// ============================================================================
// Theory Modal — deep dive per stage
// ============================================================================

function TheoryModal({
  stageKey,
  onClose,
}: {
  stageKey: StageKey;
  onClose: () => void;
}) {
  const stage = STAGES.find((s) => s.key === stageKey)!;
  const Icon = stage.icon;
  return (
    <motion.div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, y: 10, opacity: 0 }}
        animate={{ scale: 1, y: 0, opacity: 1 }}
        exit={{ scale: 0.96, y: 10, opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="w-full max-w-xl rounded-xl bg-white shadow-2xl border border-border overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-5 py-4 border-b border-border flex items-start gap-3"
          style={{ background: stage.color + "10" }}
        >
          <div
            className="w-10 h-10 rounded-md flex items-center justify-center"
            style={{ background: stage.color + "20" }}
          >
            <Icon className="w-5 h-5" strokeWidth={1.75} style={{ color: stage.color }} />
          </div>
          <div className="flex-1">
            <div className="text-[10.5px] uppercase tracking-wider font-bold" style={{ color: stage.color }}>
              Stage {stage.n}
            </div>
            <div className="text-[16px] font-semibold text-fg">{stage.title}</div>
            <div className="text-[12px] text-fg-muted">{stage.tagline}</div>
          </div>
          <button
            onClick={onClose}
            className="text-fg-subtle hover:text-fg p-1 rounded hover:bg-bg-subtle"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="text-[13px] font-semibold text-fg">{stage.theory.heading}</div>
          {stage.theory.body.map((p, i) => (
            <p key={i} className="text-[12.5px] text-fg-muted leading-relaxed">
              {p}
            </p>
          ))}
        </div>
      </motion.div>
    </motion.div>
  );
}

// ============================================================================
// Run inspection — wraps the SSE call to /api/playground/inspect
// ============================================================================

async function runInspection(
  query: string,
  useRerank: boolean,
  setState: React.Dispatch<React.SetStateAction<PipelineState>>,
  signal: AbortSignal
) {
  await fetchEventSource("/api/playground/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ query, use_rerank: useRerank, top_k: 5 }),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      if (!ev.data) return;
      const data = JSON.parse(ev.data);
      switch (ev.event) {
        case "embed":
          setState((s) => ({
            ...s,
            embedVec: data.vector,
            embedModel: data.model,
            embedMs: data.duration_ms,
            step: "dense",
          }));
          break;
        case "dense":
          setState((s) => ({ ...s, dense: data.hits, denseMs: data.duration_ms, step: "bm25" }));
          break;
        case "bm25":
          setState((s) => ({ ...s, bm25: data.hits, bm25Ms: data.duration_ms, step: "rrf" }));
          break;
        case "rrf":
          setState((s) => ({
            ...s,
            rrf: data.hits,
            rrfMs: data.duration_ms,
            step: useRerank ? "rerank" : "generate",
          }));
          break;
        case "rerank":
          setState((s) => ({
            ...s,
            rerank: data.hits,
            rerankMs: data.duration_ms,
            rerankModel: data.model || s.rerankModel,
            step: "generate",
          }));
          break;
        case "token":
          setState((s) => ({ ...s, answer: s.answer + (data.delta || "") }));
          break;
        case "answer_reset":
          // Server is re-starting the answer (refusal detected → falling
          // back to general knowledge). Wipe the streamed refusal so new
          // tokens don't append to the old text.
          setState((s) => ({ ...s, answer: "" }));
          break;
        case "done":
          setState((s) => ({
            ...s,
            faithfulness: data.faithfulness,
            totalMs: data.latency_ms?.total ?? s.totalMs,
            generateMs: data.latency_ms?.generate ?? s.generateMs,
            promptTokens: data.tokens?.prompt ?? 0,
            completionTokens: data.tokens?.completion ?? 0,
            embedModel: data.models?.embed || s.embedModel,
            rerankModel: data.models?.rerank || s.rerankModel,
            generateModel: data.models?.generate || s.generateModel,
            step: "done",
          }));
          break;
        case "error":
          setState((s) => ({ ...s, step: "error" }));
          break;
      }
    },
  });
}

// ============================================================================
// Sticky CTA — sign in for the full experience
// ============================================================================

export function PipelineSignInBanner() {
  return (
    <Link
      to="/signin"
      className="fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-accent text-white text-[12.5px] font-semibold shadow-lg hover:bg-accent/90 transition-all"
    >
      Sign in for the full experience
      <ArrowRight className="w-3.5 h-3.5" strokeWidth={2.5} />
    </Link>
  );
}
