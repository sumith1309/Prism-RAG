import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

import { fetchSuggestedQuestions } from "@/lib/api";
import { useAppStore } from "@/store/appStore";

const DEFAULT_QUESTIONS = [
  "What topics does this corpus cover?",
  "Summarize the key policies.",
  "What are the mandatory training requirements?",
  "What is the on-call rotation?",
  "Summarize Q4 revenue numbers.",
  "What was the recent security incident?",
];

export function SuggestedQuestions({ onPick }: { onPick: (q: string) => void }) {
  const { documents, activeDocIds, user } = useAppStore();
  const [questions, setQuestions] = useState<string[]>(DEFAULT_QUESTIONS);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const ids = Array.from(activeDocIds);
    if (ids.length !== 1) {
      setQuestions(DEFAULT_QUESTIONS);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchSuggestedQuestions(ids[0])
      .then((qs) => {
        if (cancelled) return;
        setQuestions(qs.length ? qs : DEFAULT_QUESTIONS);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [activeDocIds, documents]);

  const headline =
    activeDocIds.size === 0
      ? "Select a document to begin"
      : activeDocIds.size === 1
      ? "Try asking"
      : `Ask across ${activeDocIds.size} documents in scope`;

  return (
    <div className="max-w-3xl mx-auto px-6 pt-10 pb-4 min-h-full flex flex-col justify-center">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="mb-7"
      >
        <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-accent-soft border border-accent/20 text-[11px] font-medium text-accent mb-4 shadow-subtle">
          <Sparkles className="w-3 h-3" strokeWidth={2} /> {headline}
        </div>
        <h1 className="text-[32px] sm:text-[36px] font-semibold tracking-tight text-fg leading-tight">
          {user ? (
            <>
              Welcome back,{" "}
              <span className="bg-gradient-to-br from-accent to-[#9387ff] bg-clip-text text-transparent">
                {user.username}
              </span>
              .
            </>
          ) : (
            "Welcome."
          )}
        </h1>
        <p className="text-fg-muted text-[14.5px] mt-2.5 leading-relaxed max-w-xl">
          Hybrid retrieval (dense + BM25 + RRF, reranked), grounded generation with
          inline citations, and RBAC enforced at the vector-store filter.
        </p>
      </motion.div>

      <div className="grid sm:grid-cols-2 gap-2.5">
        {questions.slice(0, 6).map((q, i) => (
          <motion.button
            key={q}
            onClick={() => onPick(q)}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06 + i * 0.04, duration: 0.3, ease: "easeOut" }}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            className="text-left text-[13.5px] card card-hover p-3.5 flex items-start gap-3 group"
          >
            <span className="shrink-0 w-6 h-6 rounded-md bg-accent-soft text-accent flex items-center justify-center text-[11px] font-bold border border-accent/20 group-hover:bg-accent group-hover:text-white group-hover:border-accent transition-all">
              {i + 1}
            </span>
            <span className="leading-snug text-fg pt-0.5">{q}</span>
          </motion.button>
        ))}
      </div>
      {loading && (
        <div className="flex items-center justify-center gap-2 text-xs text-fg-muted mt-4">
          <Loader2 className="w-3 h-3 animate-spin" /> Generating tailored questions…
        </div>
      )}
    </div>
  );
}
