import { motion } from "framer-motion";
import { ArrowRight, Check, FileText, GitCompareArrows, Sparkles } from "lucide-react";

import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";

/** Renders when the retrieval pipeline detects that a user's query legitimately
 * matches 2+ distinct documents with comparable scores. Instead of blending
 * the docs into one answer (the correctness bug), we pause and let the user
 * pick. Once picked, the card freezes: the chosen candidate turns green,
 * the others dim. Thread replay re-renders the frozen state.
 *
 * Tier 2.2 addition: a "Compare all" button next to the pick list that
 * kicks off parallel retrieval+generation for every candidate and
 * renders the answers side-by-side in a ComparisonCard.
 */
export function DisambiguationCard({
  message,
  onPick,
  onCompareAll,
}: {
  message: ChatMessage;
  onPick: (docId: string, query: string, messageId: string) => void;
  onCompareAll?: (docIds: string[], query: string, messageId: string) => void;
}) {
  const d = message.disambiguation;
  if (!d || !d.candidates || d.candidates.length === 0) return null;
  const chosen = d.chosen_doc_id;
  const isFrozen = !!chosen;
  const query = d.query || "";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
    >
      <div className="flex items-start gap-2.5 max-w-full">
        <div className="w-7 h-7 shrink-0 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center mt-0.5">
          <Sparkles className="w-3.5 h-3.5 text-accent" strokeWidth={1.75} />
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <div className="card px-4 py-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="text-[10.5px] uppercase tracking-wider font-semibold text-accent">
                Clarifying question
              </div>
              {isFrozen && (
                <div className="text-[10px] px-1.5 py-0.5 rounded bg-clearance-public/10 text-clearance-public font-semibold inline-flex items-center gap-1">
                  <Check className="w-2.5 h-2.5" strokeWidth={2.5} />
                  Scoped
                </div>
              )}
            </div>
            <div className="text-[14px] text-fg leading-relaxed mb-3">
              {isFrozen
                ? "You scoped the answer to:"
                : message.content ||
                  "Your question could match these documents — pick one to scope the answer."}
            </div>

            <div className="space-y-2">
              {d.candidates.map((c) => {
                const isChosen = chosen === c.doc_id;
                const isDimmed = isFrozen && !isChosen;
                return (
                  <button
                    key={c.doc_id}
                    disabled={isFrozen}
                    onClick={() => onPick(c.doc_id, query, message.id)}
                    className={cn(
                      "w-full text-left rounded-md border px-3 py-2.5 transition-all group",
                      isChosen
                        ? "border-clearance-public/50 bg-clearance-public/5"
                        : isDimmed
                        ? "border-border bg-bg-subtle opacity-55"
                        : "border-border bg-bg-elevated hover:border-accent/50 hover:bg-accent-soft/40 hover:shadow-sm"
                    )}
                  >
                    <div className="flex items-start gap-2.5">
                      <div
                        className={cn(
                          "w-7 h-7 shrink-0 rounded border flex items-center justify-center mt-0.5",
                          isChosen
                            ? "bg-clearance-public/10 border-clearance-public/40"
                            : "bg-bg border-border"
                        )}
                      >
                        {isChosen ? (
                          <Check
                            className="w-3.5 h-3.5 text-clearance-public"
                            strokeWidth={2.5}
                          />
                        ) : (
                          <FileText
                            className="w-3.5 h-3.5 text-fg-muted"
                            strokeWidth={1.75}
                          />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <div className="text-[13px] font-semibold text-fg truncate">
                            {c.label}
                          </div>
                          <div className="text-[10px] text-fg-subtle font-mono tabular-nums">
                            {c.chunk_count} chunk{c.chunk_count === 1 ? "" : "s"}
                            {" · "}
                            score {c.top_score.toFixed(2)}
                          </div>
                        </div>
                        {c.hint && (
                          <div className="text-[12px] text-fg-muted leading-snug mt-0.5 line-clamp-2">
                            {c.hint}
                          </div>
                        )}
                      </div>
                      {!isFrozen && (
                        <ArrowRight
                          className="w-3.5 h-3.5 text-fg-subtle opacity-0 group-hover:opacity-100 transition-opacity mt-2"
                          strokeWidth={2}
                        />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {!isFrozen && (
              <div className="mt-3 flex items-center gap-3 flex-wrap">
                <div className="text-[11px] text-fg-subtle flex-1 min-w-0">
                  Not sure? Tap the closest match — I'll answer strictly from that doc.
                </div>
                {onCompareAll && d.candidates.length >= 2 && (
                  <button
                    onClick={() =>
                      onCompareAll(
                        d.candidates.map((c) => c.doc_id),
                        query,
                        message.id
                      )
                    }
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-accent/40 bg-white text-[11.5px] font-semibold text-accent hover:bg-accent hover:text-white transition-colors shrink-0"
                    title="Generate a separate answer for each doc and show them side-by-side"
                  >
                    <GitCompareArrows className="w-3 h-3" strokeWidth={2.25} />
                    Compare all
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
