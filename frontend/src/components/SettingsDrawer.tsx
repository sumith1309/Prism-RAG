import { useMemo } from "react";
import { Layers, SlidersHorizontal, Wand2, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { settings, updateSettings, documents } = useAppStore();

  const allSections = useMemo(() => {
    const set = new Set<string>();
    documents.forEach((d) => d.sections.forEach((s) => s && set.add(s)));
    return Array.from(set).sort();
  }, [documents]);

  const toggleSection = (s: string) => {
    const cur = new Set(settings.sectionFilter);
    if (cur.has(s)) cur.delete(s);
    else cur.add(s);
    updateSettings({ sectionFilter: Array.from(cur) });
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-fg/20 backdrop-blur-sm z-30"
          />
          <motion.aside
            initial={{ x: 400, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 400, opacity: 0 }}
            transition={{ type: "spring", damping: 26, stiffness: 240 }}
            className="fixed right-0 top-0 bottom-0 w-[380px] max-w-[92vw] bg-bg-elevated border-l border-border z-40 flex flex-col shadow-pop"
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <SlidersHorizontal className="w-4 h-4 text-fg-muted" strokeWidth={1.5} />
                <div className="font-semibold tracking-tight text-fg">Retrieval settings</div>
              </div>
              <button onClick={onClose} className="btn-ghost w-8 h-8 p-0 flex items-center justify-center">
                <X className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-6 text-sm">
              <Toggle
                label="Cross-encoder reranking"
                desc="Second-stage rerank of top candidates with BAAI/bge-reranker-base. Biggest accuracy win."
                value={settings.useRerank}
                onChange={(v) => updateSettings({ useRerank: v })}
              />
              <Toggle
                label="HyDE query rewriting"
                desc="LLM drafts a hypothetical answer, then retrieves with that. Helps vague questions."
                value={settings.useHyde}
                onChange={(v) => updateSettings({ useHyde: v })}
              />
              <Toggle
                label="Corrective RAG"
                desc="If the first retrieval pass is weak, auto-rewrite the query and retry once before declaring 'not found'."
                value={settings.useCorrective}
                onChange={(v) => updateSettings({ useCorrective: v })}
              />
              <Toggle
                label="Multi-query fan-out"
                desc="LLM expands your question into 3 variants, runs parallel retrievals, and fuses. Higher recall, +5-8s latency."
                value={settings.useMultiQuery}
                onChange={(v) => updateSettings({ useMultiQuery: v })}
              />
              <Toggle
                label="Faithfulness scoring"
                desc="After the answer streams, an LLM judge scores how well it aligns with the cited sources (0-100%)."
                value={settings.useFaithfulness}
                onChange={(v) => updateSettings({ useFaithfulness: v })}
              />

              <div>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-medium text-fg">Top-K sources</div>
                    <div className="text-[11px] text-fg-muted">
                      How many grounded passages to send to the LLM.
                    </div>
                  </div>
                  <span className="font-mono text-accent">{settings.topK}</span>
                </div>
                <input
                  type="range"
                  min={3}
                  max={10}
                  value={settings.topK}
                  onChange={(e) => updateSettings({ topK: Number(e.target.value) })}
                  className="w-full accent-accent"
                />
              </div>

              {allSections.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Layers className="w-3.5 h-3.5 text-fg-muted" strokeWidth={1.5} />
                    <div className="font-medium text-fg">Filter by section</div>
                  </div>
                  <div className="text-[11px] text-fg-muted mb-2">
                    Leave empty to search all sections.
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {allSections.map((s) => {
                      const on = settings.sectionFilter.includes(s);
                      return (
                        <button
                          key={s}
                          onClick={() => toggleSection(s)}
                          className={cn(
                            "text-[11px] px-2 py-1 rounded-md border transition-colors",
                            on
                              ? "bg-accent-soft border-accent/50 text-accent"
                              : "bg-bg border-border text-fg-muted hover:text-fg hover:border-border-strong"
                          )}
                        >
                          {s}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="pt-2 border-t border-border">
                <div className="flex items-center gap-2 text-[12px] text-fg mb-2">
                  <Wand2 className="w-3.5 h-3.5 text-accent" strokeWidth={1.5} />
                  Pipeline at a glance
                </div>
                <ol className="space-y-1.5 text-[12px] text-fg-muted list-decimal list-inside">
                  <li>Query cache lookup (10-min TTL, per-user+role+docs)</li>
                  <li>Optional multi-query fan-out (3 LLM rewrites, parallel)</li>
                  <li>Dense retrieval (Qdrant · all-MiniLM-L6-v2)</li>
                  <li>Keyword retrieval (BM25 over tokenized chunks)</li>
                  <li>RRF fusion (k=60)</li>
                  <li>Cross-encoder rerank (bge-reranker-base)</li>
                  <li>RBAC filter at Qdrant layer — <code className="text-fg">doc_level ≤ user.level</code></li>
                  <li>Corrective retry if first pass fails the relevance gate</li>
                  <li>4-way mode: grounded / refused / general / unknown</li>
                  <li>Grounded generation with inline [Source N] citations</li>
                  <li>LLM-judge faithfulness score (0-100%)</li>
                </ol>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Toggle({
  label,
  desc,
  value,
  onChange,
}: {
  label: string;
  desc: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer select-none">
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={cn(
          "mt-0.5 relative w-9 h-5 rounded-full transition-colors shrink-0",
          value ? "bg-accent" : "bg-bg"
        )}
        style={value ? undefined : { border: "1px solid var(--tw-border-color, #1f1f22)" }}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm",
            value && "translate-x-4"
          )}
        />
      </button>
      <div>
        <div className="font-medium text-fg">{label}</div>
        <div className="text-[11px] text-fg-muted leading-snug">{desc}</div>
      </div>
    </label>
  );
}
