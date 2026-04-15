import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ChevronDown,
  Clock,
  Coins,
  Database,
  Gauge,
  MessagesSquare,
  RefreshCw,
  ShieldCheck,
  Zap,
} from "lucide-react";

import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";

/**
 * Per-message observability footer. Collapsed by default; shows latency
 * bars, token counts, faithfulness score, and the retrieved chunks' scores
 * as a mini-chart when expanded. This is the "show, don't tell" feature
 * that turns our hidden retrieval pipeline into a visible demo artifact.
 */
export function RetrievalTrace({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);

  const hasMeta =
    message.latency_ms ||
    message.tokens ||
    message.cached ||
    message.faithfulness !== undefined ||
    (message.sources && message.sources.length > 0);

  if (!hasMeta) return null;

  const L = message.latency_ms ?? { retrieve: 0, rerank: 0, generate: 0, total: 0 };
  const totalShown = Math.max(L.total, L.retrieve + L.generate, 1);
  const pct = (n: number) => Math.min(100, Math.round((n / totalShown) * 100));
  const retrievePct = pct(L.retrieve);
  const generatePct = pct(L.generate);
  const faith = message.faithfulness;
  const faithDisplay =
    faith === undefined || faith < 0 ? null : `${Math.round(faith * 100)}%`;
  const faithColor =
    faith === undefined || faith < 0
      ? ""
      : faith >= 0.8
      ? "text-clearance-public"
      : faith >= 0.5
      ? "text-clearance-confidential"
      : "text-clearance-restricted";

  return (
    <div className="mt-1">
      {/* Collapsed header — always visible */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 text-[11px] text-fg-subtle hover:text-fg-muted transition-colors group py-1"
      >
        <Activity className="w-3 h-3" strokeWidth={2} />
        <span className="font-mono">{L.total}ms</span>
        {message.tokens && (
          <span className="flex items-center gap-1 font-mono">
            <Coins className="w-3 h-3" strokeWidth={2} />
            {message.tokens.prompt + message.tokens.completion}
          </span>
        )}
        {message.cached && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-accent-soft text-accent font-semibold uppercase tracking-wider text-[9px]">
            <Zap className="w-2.5 h-2.5" strokeWidth={2.5} />
            Cached
          </span>
        )}
        {message.corrective_retries ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-clearance-confidential/10 text-clearance-confidential font-semibold uppercase tracking-wider text-[9px]">
            <RefreshCw className="w-2.5 h-2.5" strokeWidth={2.5} />
            Corrective ×{message.corrective_retries}
          </span>
        ) : null}
        {message.contextualized_query ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-accent-soft text-accent font-semibold uppercase tracking-wider text-[9px]">
            <MessagesSquare className="w-2.5 h-2.5" strokeWidth={2.5} />
            Contextualized
          </span>
        ) : null}
        {faithDisplay && (
          <span
            className={cn(
              "inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-hover font-semibold uppercase tracking-wider text-[9px]",
              faithColor
            )}
          >
            <ShieldCheck className="w-2.5 h-2.5" strokeWidth={2.5} />
            Faithful {faithDisplay}
          </span>
        )}
        <span className="ml-auto text-[10px] flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          Trace
          <ChevronDown
            className={cn("w-3 h-3 transition-transform", open && "rotate-180")}
            strokeWidth={2}
          />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="trace"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="mt-2 card p-3.5 text-[11.5px] space-y-3">
              {/* Latency breakdown */}
              <section>
                <div className="flex items-center gap-1.5 text-fg-muted mb-2">
                  <Clock className="w-3 h-3" strokeWidth={2} />
                  <span className="font-semibold uppercase tracking-wider text-[10px]">
                    Latency
                  </span>
                  <span className="ml-auto font-mono text-fg">{L.total}ms total</span>
                </div>
                <div className="grid grid-cols-[auto_1fr_auto] gap-x-2 gap-y-1 items-center">
                  <span className="text-fg-muted">Retrieve</span>
                  <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                    <div
                      className="h-full bg-accent"
                      style={{ width: `${retrievePct}%` }}
                    />
                  </div>
                  <span className="font-mono text-fg text-right">{L.retrieve}ms</span>

                  {L.rerank > 0 && (
                    <>
                      <span className="text-fg-muted">Rerank</span>
                      <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                        <div
                          className="h-full bg-accent/70"
                          style={{ width: `${pct(L.rerank)}%` }}
                        />
                      </div>
                      <span className="font-mono text-fg text-right">~{L.rerank}ms</span>
                    </>
                  )}

                  <span className="text-fg-muted">Generate</span>
                  <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                    <div
                      className="h-full bg-clearance-internal"
                      style={{ width: `${generatePct}%` }}
                    />
                  </div>
                  <span className="font-mono text-fg text-right">{L.generate}ms</span>
                </div>
              </section>

              {/* Tokens */}
              {message.tokens && (
                <section>
                  <div className="flex items-center gap-1.5 text-fg-muted mb-1.5">
                    <Coins className="w-3 h-3" strokeWidth={2} />
                    <span className="font-semibold uppercase tracking-wider text-[10px]">
                      Tokens
                    </span>
                  </div>
                  <div className="flex items-center gap-4 font-mono text-fg">
                    <span>
                      <span className="text-fg-muted mr-1">prompt</span>
                      {message.tokens.prompt}
                    </span>
                    <span>
                      <span className="text-fg-muted mr-1">completion</span>
                      {message.tokens.completion}
                    </span>
                    <span className="ml-auto text-fg-muted">
                      total {message.tokens.prompt + message.tokens.completion}
                    </span>
                  </div>
                </section>
              )}

              {/* Retrieved chunks scores */}
              {message.sources && message.sources.length > 0 && (
                <section>
                  <div className="flex items-center gap-1.5 text-fg-muted mb-2">
                    <Database className="w-3 h-3" strokeWidth={2} />
                    <span className="font-semibold uppercase tracking-wider text-[10px]">
                      Retrieved chunks ({message.sources.length})
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {message.sources.map((s) => {
                      // Normalize scores for bar width:
                      // RRF: ~0..0.08, rerank: 0..1
                      const rrfPct = Math.min(100, (s.rrf_score / 0.05) * 100);
                      const rerankPct =
                        s.rerank_score === null ? 0 : Math.min(100, s.rerank_score * 100);
                      return (
                        <div key={`${s.doc_id}-${s.index}`} className="text-[10.5px]">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className="w-4 h-4 rounded bg-accent-soft text-accent flex items-center justify-center text-[9px] font-bold border border-accent/20">
                              {s.index}
                            </span>
                            <span className="truncate text-fg flex-1">{s.filename}</span>
                            <span className="text-fg-subtle shrink-0">p.{s.page}</span>
                          </div>
                          <div className="grid grid-cols-[48px_1fr_44px] gap-x-2 items-center mb-0.5 pl-6">
                            <span className="text-fg-muted">RRF</span>
                            <div className="h-1 rounded-full bg-bg-subtle overflow-hidden">
                              <div
                                className="h-full bg-accent"
                                style={{ width: `${rrfPct}%` }}
                              />
                            </div>
                            <span className="font-mono text-fg-subtle text-right">
                              {s.rrf_score.toFixed(3)}
                            </span>
                          </div>
                          {s.rerank_score !== null && (
                            <div className="grid grid-cols-[48px_1fr_44px] gap-x-2 items-center pl-6">
                              <span className="text-fg-muted">Rerank</span>
                              <div className="h-1 rounded-full bg-bg-subtle overflow-hidden">
                                <div
                                  className="h-full bg-accent/50"
                                  style={{ width: `${rerankPct}%` }}
                                />
                              </div>
                              <span className="font-mono text-fg-subtle text-right">
                                {s.rerank_score.toFixed(3)}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* Faithfulness */}
              {faithDisplay && (
                <section>
                  <div className="flex items-center gap-1.5 text-fg-muted mb-1.5">
                    <Gauge className="w-3 h-3" strokeWidth={2} />
                    <span className="font-semibold uppercase tracking-wider text-[10px]">
                      Faithfulness
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                      <div
                        className={cn(
                          "h-full",
                          faith && faith >= 0.8
                            ? "bg-clearance-public"
                            : faith && faith >= 0.5
                            ? "bg-clearance-confidential"
                            : "bg-clearance-restricted"
                        )}
                        style={{ width: `${(faith ?? 0) * 100}%` }}
                      />
                    </div>
                    <span className={cn("font-mono text-[11px] font-semibold", faithColor)}>
                      {faithDisplay}
                    </span>
                  </div>
                  <div className="text-[10px] text-fg-subtle mt-1">
                    LLM-judged alignment between answer and cited sources.
                  </div>
                </section>
              )}

              {message.contextualized_query && (
                <section className="rounded-md bg-accent-soft/60 border border-accent/25 p-2">
                  <div className="flex items-center gap-1.5 text-accent font-semibold uppercase tracking-wider text-[10px] mb-1">
                    <MessagesSquare className="w-3 h-3" strokeWidth={2} />
                    Contextualized from history
                  </div>
                  <div className="text-fg-muted text-[11px] leading-relaxed">
                    Follow-up detected. Used chat history to rewrite the query
                    for retrieval:
                  </div>
                  <div className="mt-1 text-fg font-mono text-[11px] italic">
                    "{message.contextualized_query}"
                  </div>
                </section>
              )}

              {message.corrective_rewrite && (
                <section className="rounded-md bg-clearance-confidential/5 border border-clearance-confidential/20 p-2">
                  <div className="flex items-center gap-1.5 text-clearance-confidential font-semibold uppercase tracking-wider text-[10px] mb-1">
                    <RefreshCw className="w-3 h-3" strokeWidth={2} />
                    Corrective retry
                  </div>
                  <div className="text-fg-muted text-[11px] leading-relaxed">
                    First pass was weak. Rewrote query and retried:
                  </div>
                  <div className="mt-1 text-fg font-mono text-[11px] italic">
                    "{message.corrective_rewrite}"
                  </div>
                </section>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
