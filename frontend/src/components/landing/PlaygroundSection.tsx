import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Database,
  Gauge,
  Loader2,
  Search,
  Sparkles,
  Trophy,
  Zap,
} from "lucide-react";

import { playgroundRetrieve } from "@/lib/api";
import type { PlaygroundResponse, PlaygroundStage } from "@/lib/api";
import { cn } from "@/lib/utils";

const SAMPLES = [
  "What training is mandatory every year?",
  "Information security awareness training",
  "POSH training requirements",
];

const STAGES: Record<
  PlaygroundStage["stage"],
  { label: string; blurb: string; icon: React.ElementType; color: string }
> = {
  dense: {
    label: "Dense retrieval",
    blurb: "Semantic — embeds the query, finds chunks with similar vectors.",
    icon: Search,
    color: "clearance-internal",
  },
  bm25: {
    label: "BM25",
    blurb: "Lexical — classic IR; matches exact tokens weighted by frequency & rarity.",
    icon: Database,
    color: "clearance-confidential",
  },
  rrf: {
    label: "Reciprocal Rank Fusion",
    blurb: "Merges both ranked lists. Score = Σ 1 / (60 + rank).",
    icon: Zap,
    color: "light-accent",
  },
  rerank: {
    label: "Cross-encoder rerank",
    blurb: "bge-reranker reads each (query, chunk) pair and scores alignment 0–1.",
    icon: Trophy,
    color: "clearance-public",
  },
};

export function PlaygroundSection() {
  const [query, setQuery] = useState("What training is mandatory every year?");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PlaygroundResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState<PlaygroundStage["stage"]>("rerank");

  const run = async (q?: string) => {
    const input = (q ?? query).trim();
    if (!input) return;
    setQuery(input);
    setLoading(true);
    setError(null);
    try {
      const r = await playgroundRetrieve(input, 5);
      setResult(r);
      setActiveStage("rerank");
    } catch (e: any) {
      setError(e.message || "playground call failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section id="playground" className="bg-light-surface border-y border-light-border">
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div className="max-w-2xl">
          <div className="text-[11px] uppercase tracking-wider font-semibold text-light-accent">
            Try it live — no sign-in required
          </div>
          <h2 className="mt-2 text-[30px] sm:text-[36px] leading-tight font-semibold tracking-tight text-light-fg">
            See the RAG pipeline actually run.
          </h2>
          <p className="mt-3 text-[14.5px] text-light-fgMuted max-w-xl leading-relaxed">
            Type a question. We run the full retrieval stack on our PUBLIC corpus and show
            exactly which chunks surface at each stage — dense, BM25, RRF fusion, and
            cross-encoder rerank — with their live scores.
          </p>
        </div>

        {/* Query input + samples */}
        <div className="mt-8 flex flex-col sm:flex-row gap-2">
          <div className="flex-1 relative">
            <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-accent" />
            <input
              className="w-full bg-white border border-light-border rounded-md pl-9 pr-3 py-2.5 text-[14px] text-light-fg placeholder:text-light-fgSubtle focus:border-light-accent focus:ring-2 focus:ring-light-accent/15 outline-none transition-all"
              placeholder="Ask the PUBLIC corpus…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
          </div>
          <button
            onClick={() => run()}
            disabled={loading || !query.trim()}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-md bg-light-accent text-white text-[14px] font-semibold hover:bg-light-accentHover shadow-light-hang disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Retrieving…
              </>
            ) : (
              <>
                Run pipeline <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <span className="text-[11px] text-light-fgSubtle pt-1">Try:</span>
          {SAMPLES.map((s) => (
            <button
              key={s}
              onClick={() => run(s)}
              className="text-[11px] px-2 py-1 rounded-md border border-light-border bg-white hover:border-light-accent/50 hover:bg-light-accent/5 text-light-fgMuted hover:text-light-fg transition-colors"
            >
              {s}
            </button>
          ))}
        </div>

        {error && (
          <div className="mt-6 rounded-md border border-clearance-restricted/30 bg-clearance-restricted/5 px-4 py-3 text-[13px] text-clearance-restricted">
            {error}
          </div>
        )}

        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-8"
            >
              {/* Stage picker */}
              <div className="flex flex-wrap gap-1.5 mb-3 items-center">
                <span className="text-[11px] uppercase tracking-wider font-semibold text-light-fgSubtle mr-2">
                  Stage
                </span>
                {result.stages.map((s) => {
                  const meta = STAGES[s.stage];
                  const Icon = meta.icon;
                  const active = activeStage === s.stage;
                  return (
                    <button
                      key={s.stage}
                      onClick={() => setActiveStage(s.stage)}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-[12px] transition-all",
                        active
                          ? "bg-light-accent text-white border-light-accent shadow-light-hang"
                          : "bg-white text-light-fgMuted border-light-border hover:border-light-accent/40 hover:text-light-fg"
                      )}
                    >
                      <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
                      <span className="font-semibold">{meta.label}</span>
                      <span
                        className={cn(
                          "font-mono text-[10.5px]",
                          active ? "text-white/80" : "text-light-fgSubtle"
                        )}
                      >
                        {s.duration_ms}ms
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Stage explanation */}
              <div className="rounded-lg border border-light-border bg-light-elevated p-3.5 mb-3 flex items-start gap-2.5">
                <Gauge className="w-4 h-4 text-light-accent mt-0.5 shrink-0" strokeWidth={1.75} />
                <div className="text-[12.5px] text-light-fgMuted leading-relaxed">
                  <span className="text-light-fg font-semibold">
                    {STAGES[activeStage].label}:
                  </span>{" "}
                  {STAGES[activeStage].blurb}
                </div>
              </div>

              {/* Stage hits */}
              <StageHitsPanel stage={result.stages.find((s) => s.stage === activeStage)!} />

              <div className="mt-4 text-[11.5px] text-light-fgSubtle">
                Searched over <span className="font-semibold text-light-fg">{result.public_doc_count}</span>{" "}
                PUBLIC documents. Higher-clearance content is never returned to this
                endpoint — the vector-store filter enforces it.
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}

function StageHitsPanel({ stage }: { stage: PlaygroundStage }) {
  const maxScore = Math.max(...stage.hits.map((h) => h.score), 0.0001);
  return (
    <motion.div
      key={stage.stage}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="space-y-2"
    >
      {stage.hits.length === 0 ? (
        <div className="rounded-lg border border-light-border bg-white p-4 text-[12.5px] text-light-fgMuted text-center">
          No hits at this stage.
        </div>
      ) : (
        stage.hits.map((h) => {
          const pct = Math.max(8, (h.score / maxScore) * 100);
          return (
            <div
              key={`${stage.stage}-${h.rank}`}
              className="rounded-lg border border-light-border bg-white p-3.5 shadow-light-sm"
            >
              <div className="flex items-start gap-2.5">
                <div className="shrink-0 w-6 h-6 rounded-md bg-light-accent/10 text-light-accent flex items-center justify-center text-[11px] font-bold border border-light-accent/20">
                  {h.rank}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[12.5px] font-semibold text-light-fg truncate">
                      {h.filename}
                    </span>
                    <span className="text-[10.5px] text-light-fgSubtle">p.{h.page}</span>
                    {h.section && (
                      <span className="text-[10.5px] text-light-fgSubtle truncate">
                        · {h.section}
                      </span>
                    )}
                    <span className="ml-auto text-[11px] font-mono text-light-accent font-semibold">
                      {h.score.toFixed(4)}
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-light-border overflow-hidden mb-2">
                    <motion.div
                      className="h-full bg-light-accent"
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.5, ease: "easeOut" }}
                    />
                  </div>
                  <p className="text-[11.5px] text-light-fgMuted leading-relaxed line-clamp-2">
                    {h.text}
                  </p>
                </div>
              </div>
            </div>
          );
        })
      )}
    </motion.div>
  );
}
