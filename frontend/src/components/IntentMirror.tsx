import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Edit3, Sparkles, X } from "lucide-react";

import { cn } from "@/lib/utils";

/** One-line "Understood as" pill above the answer. Shows the agent's
 * interpretation of the user's query BEFORE the answer streams, so the
 * user can redirect if the agent misread them. Clicking the pencil
 * opens an inline editor; submitting re-runs the query with the edit
 * as `override_intent` (the original message stays in the chat log).
 */
export function IntentMirror({
  intent,
  original,
  edited,
  onReRun,
}: {
  intent: string;
  original: string;
  edited: boolean;
  onReRun: (rewritten: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(intent.replace(/^You're asking[:,]?\s*/i, ""));

  if (!intent) return null;

  const submit = () => {
    const v = draft.trim();
    setEditing(false);
    if (v && v !== intent && v !== original) {
      onReRun(v);
    }
  };

  return (
    <AnimatePresence mode="wait">
      {editing ? (
        <motion.div
          key="editing"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.18 }}
          className="overflow-hidden"
        >
          <div className="rounded-md border border-accent/40 bg-accent-soft px-3 py-2 flex items-start gap-2">
            <Sparkles
              className="w-3.5 h-3.5 text-accent mt-1 shrink-0"
              strokeWidth={1.75}
            />
            <div className="flex-1 min-w-0 space-y-1.5">
              <div className="text-[10.5px] uppercase tracking-wider text-accent font-semibold">
                Edit what I should search for
              </div>
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submit();
                  if (e.key === "Escape") setEditing(false);
                }}
                className="w-full bg-white border border-accent/40 rounded px-2 py-1 text-[12.5px] text-fg focus:outline-none focus:border-accent"
                placeholder="Rephrase the query exactly as you meant it…"
              />
              <div className="flex items-center gap-1.5">
                <button
                  onClick={submit}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-accent text-white text-[11px] font-semibold hover:bg-accent/90"
                >
                  <Check className="w-3 h-3" strokeWidth={2.5} />
                  Re-run
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border text-[11px] text-fg-muted hover:text-fg hover:bg-bg-subtle"
                >
                  <X className="w-3 h-3" strokeWidth={2.25} />
                  Cancel
                </button>
                <div className="text-[10px] text-fg-subtle ml-1">
                  Enter to submit · Esc to cancel
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="pill"
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18 }}
          className={cn(
            "rounded-md border px-3 py-1.5 flex items-start gap-2 group",
            edited
              ? "border-clearance-public/40 bg-clearance-public/5"
              : "border-accent/25 bg-accent-soft"
          )}
        >
          <Sparkles
            className={cn(
              "w-3 h-3 mt-[3px] shrink-0",
              edited ? "text-clearance-public" : "text-accent"
            )}
            strokeWidth={1.75}
          />
          <div className="flex-1 min-w-0 text-[12px] leading-snug text-fg">
            <span
              className={cn(
                "font-semibold mr-1",
                edited ? "text-clearance-public" : "text-accent"
              )}
            >
              {edited ? "Using your edit:" : "Understood as:"}
            </span>
            <span className="text-fg-muted">
              {intent.replace(/^You're asking[:,]?\s*/i, "")}
            </span>
          </div>
          <button
            onClick={() => {
              setDraft(intent.replace(/^You're asking[:,]?\s*/i, ""));
              setEditing(true);
            }}
            className="shrink-0 text-fg-subtle hover:text-accent transition-colors p-0.5 opacity-60 group-hover:opacity-100"
            title="Edit — I'll re-run the answer using your rephrase"
          >
            <Edit3 className="w-3 h-3" strokeWidth={2} />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
