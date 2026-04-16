import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Lock, Send, X } from "lucide-react";
import { toast } from "sonner";

import { requestAccess } from "@/lib/api";
import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";
import { RetrievalTrace } from "./RetrievalTrace";

/** Enriched unknown/refused card when the block was RBAC-triggered. Tells
 * the user the content exists but is above their clearance, and offers a
 * one-click "Request Access" that logs to the audit trail. Replaces the
 * bland "I don't have a confident answer" card in this specific case.
 */
export function AccessRequestBanner({
  message,
  userQuery,
}: {
  message: ChatMessage;
  userQuery: string;
}) {
  const [state, setState] = useState<"idle" | "editing" | "submitting" | "done">("idle");
  const [reason, setReason] = useState("");

  const submit = async () => {
    setState("submitting");
    try {
      const resp = await requestAccess(userQuery, reason || undefined);
      if (resp.ok) {
        setState("done");
        toast.success(resp.message);
      } else {
        setState("idle");
        toast.error(resp.message || "Request failed");
      }
    } catch (e: any) {
      setState("idle");
      toast.error(`Request failed: ${e?.message || e}`);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex items-start gap-2.5 max-w-full">
        <div className="w-7 h-7 shrink-0 rounded-md bg-clearance-confidential/10 border border-clearance-confidential/30 flex items-center justify-center mt-0.5">
          <Lock
            className="w-3.5 h-3.5 text-clearance-confidential"
            strokeWidth={1.75}
          />
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <div className="card px-4 py-3 border-clearance-confidential/30 bg-clearance-confidential/5">
            <div className="text-[11px] uppercase tracking-wider font-semibold text-clearance-confidential mb-1 flex items-center gap-2">
              Above your clearance
              {state === "done" && (
                <span className="normal-case tracking-normal text-[10px] px-1.5 py-0.5 rounded bg-clearance-public/15 text-clearance-public font-semibold inline-flex items-center gap-1">
                  <Check className="w-2.5 h-2.5" strokeWidth={2.5} />
                  Request sent
                </span>
              )}
            </div>
            <div className="text-[13.5px] leading-relaxed text-fg">
              {message.content}
            </div>

            {state === "idle" && (
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setState("editing")}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-clearance-confidential/40 bg-white text-[12px] font-semibold text-clearance-confidential hover:bg-clearance-confidential hover:text-white transition-colors"
                >
                  <Send className="w-3 h-3" strokeWidth={2.25} />
                  Request access
                </button>
                <span className="text-[11px] text-fg-subtle">
                  Logs an audit entry for a manager to review.
                </span>
              </div>
            )}

            {state === "editing" && (
              <div className="mt-3 space-y-2">
                <label className="block text-[10.5px] uppercase tracking-wider text-fg-muted font-semibold">
                  Why do you need this? (optional)
                </label>
                <textarea
                  autoFocus
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Working on the security incident review — need visibility into the November report."
                  rows={2}
                  className="w-full rounded-md border border-border bg-white px-2.5 py-1.5 text-[12.5px] text-fg focus:outline-none focus:border-accent resize-none"
                />
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={submit}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-semibold transition-colors",
                      "bg-accent text-white hover:bg-accent/90"
                    )}
                  >
                    <Send className="w-3 h-3" strokeWidth={2.25} />
                    Submit
                  </button>
                  <button
                    onClick={() => {
                      setState("idle");
                      setReason("");
                    }}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border text-[12px] text-fg-muted hover:text-fg hover:bg-bg-subtle"
                  >
                    <X className="w-3 h-3" strokeWidth={2.25} />
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {state === "submitting" && (
              <div className="mt-3 text-[12px] text-fg-muted inline-flex items-center gap-2">
                <span className="w-3 h-3 rounded-full border-2 border-accent/30 border-t-accent animate-spin" />
                Logging request…
              </div>
            )}

            {state === "done" && (
              <div className="mt-3 text-[12px] text-fg-muted">
                Your request has been logged. A manager can see it in the Audit tab.
              </div>
            )}
          </div>
          {!message.streaming && <RetrievalTrace message={message} />}
        </div>
      </div>
    </motion.div>
  );
}
