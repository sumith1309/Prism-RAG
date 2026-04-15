import { motion } from "framer-motion";
import {
  Check,
  FileText,
  Lock,
  Shield,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from "lucide-react";

import type { Classification, WelcomePayload } from "@/types";
import { cn } from "@/lib/utils";

const TIER_ICON: Record<Classification, typeof Shield> = {
  PUBLIC: Shield,
  INTERNAL: Shield,
  CONFIDENTIAL: ShieldCheck,
  RESTRICTED: Lock,
};

const TIER_COLOR: Record<Classification, string> = {
  PUBLIC: "text-clearance-public border-clearance-public/30 bg-clearance-public/5",
  INTERNAL: "text-clearance-internal border-clearance-internal/30 bg-clearance-internal/5",
  CONFIDENTIAL:
    "text-clearance-confidential border-clearance-confidential/30 bg-clearance-confidential/5",
  RESTRICTED: "text-clearance-restricted border-clearance-restricted/30 bg-clearance-restricted/5",
};

export function WelcomeCard({
  payload,
  onPickSuggestion,
  compact = false,
}: {
  payload: WelcomePayload;
  onPickSuggestion: (q: string) => void;
  /** When embedded inside a chat bubble (post-greeting), render tighter. */
  compact?: boolean;
}) {
  const { user, tiers, suggestions, upload_hint, accessible_count } = payload;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className={cn(
        "w-full",
        compact ? "space-y-3" : "max-w-3xl mx-auto px-6 pt-10 pb-4 space-y-5"
      )}
    >
      {/* Greeting header */}
      <div className={compact ? "" : "mb-1"}>
        <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-accent-soft border border-accent/20 text-[11px] font-medium text-accent mb-3 shadow-subtle">
          <Sparkles className="w-3 h-3" strokeWidth={2} /> Prism RAG Assistant
        </div>
        <h1
          className={cn(
            "font-semibold tracking-tight text-fg leading-tight",
            compact ? "text-[22px]" : "text-[30px] sm:text-[34px]"
          )}
        >
          Hi{" "}
          <span className="bg-gradient-to-br from-accent to-[#9387ff] bg-clip-text text-transparent">
            {user.username}
          </span>
          , welcome back.
        </h1>
        <p
          className={cn(
            "text-fg-muted leading-relaxed mt-2",
            compact ? "text-[13px]" : "text-[14.5px] max-w-xl"
          )}
        >
          You're signed in as{" "}
          <span className="font-semibold text-fg">{user.role_title}</span> with{" "}
          <span className="font-semibold text-fg">{user.clearance_label}</span> (L
          {user.level}) clearance. I can answer across{" "}
          <span className="font-semibold text-fg">{accessible_count}</span> documents
          you're cleared to see.
        </p>
      </div>

      {/* Knowledge tiers */}
      <section>
        <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold mb-2">
          Your knowledge base
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {tiers.map((t) => {
            const Icon = TIER_ICON[t.label];
            return (
              <div
                key={t.level}
                className={cn(
                  "rounded-md border px-3 py-2.5 flex flex-col gap-1 transition-opacity",
                  t.accessible ? TIER_COLOR[t.label] : "border-border bg-surface opacity-50"
                )}
                title={t.description}
              >
                <div className="flex items-center gap-1.5">
                  <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
                  <span className="text-[10.5px] uppercase tracking-wider font-semibold">
                    {t.label}
                  </span>
                </div>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[18px] font-bold font-mono tabular-nums">
                    {t.accessible ? t.count : "—"}
                  </span>
                  <span className="text-[10px] text-fg-subtle">
                    {t.accessible ? (t.count === 1 ? "doc" : "docs") : "locked"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Suggested prompts */}
      {suggestions.length > 0 && (
        <section>
          <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold mb-2">
            Try asking
          </div>
          <div className="grid sm:grid-cols-2 gap-2">
            {suggestions.map((q, i) => (
              <motion.button
                key={q}
                onClick={() => onPickSuggestion(q)}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.06 + i * 0.04, duration: 0.25 }}
                whileHover={{ y: -2 }}
                whileTap={{ scale: 0.98 }}
                className="text-left text-[13px] card card-hover p-3 flex items-start gap-2.5 group"
              >
                <span className="shrink-0 w-5 h-5 rounded bg-accent-soft text-accent flex items-center justify-center text-[10px] font-bold border border-accent/20 group-hover:bg-accent group-hover:text-white group-hover:border-accent transition-all">
                  {i + 1}
                </span>
                <span className="leading-snug text-fg pt-0.5">{q}</span>
              </motion.button>
            ))}
          </div>
        </section>
      )}

      {/* Upload hint */}
      <section className="rounded-md border border-accent/20 bg-accent-soft/40 px-3 py-2.5 flex items-start gap-2.5">
        <UploadCloud className="w-4 h-4 text-accent mt-0.5 shrink-0" strokeWidth={1.75} />
        <div className="text-[12.5px] text-fg leading-relaxed">
          <span className="font-semibold text-accent">Add your own documents.</span>{" "}
          {upload_hint}
        </div>
      </section>

      {/* What I can do — always-on capabilities list */}
      <section className="text-[11.5px] text-fg-muted leading-relaxed space-y-1.5">
        {[
          "Hybrid retrieval (dense + BM25 → RRF fusion → cross-encoder rerank)",
          "Grounded answers with inline source citations + faithfulness score",
          "RBAC enforced at the vector-store filter — you only see your clearance",
          "Multi-query + corrective RAG + per-thread history, all togglable",
        ].map((cap) => (
          <div key={cap} className="flex items-start gap-2">
            <Check
              className="w-3 h-3 text-accent mt-1 shrink-0"
              strokeWidth={2.5}
            />
            <span>{cap}</span>
          </div>
        ))}
      </section>

      {!compact && (
        <div className="flex items-center gap-2 pt-2 text-[11px] text-fg-subtle">
          <FileText className="w-3 h-3" strokeWidth={2} />
          Answers are grounded in retrieved sources with inline citations.
        </div>
      )}
    </motion.div>
  );
}
