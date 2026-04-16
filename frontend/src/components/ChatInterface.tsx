import { useEffect, useMemo, useRef, useState } from "react";
import { Target, X } from "lucide-react";

import { useChatStream } from "@/hooks/useChatStream";
import { fetchWelcome } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import type { WelcomePayload } from "@/types";
import { ChatComposer } from "./ChatComposer";
import { MessageBubble } from "./MessageBubble";
import { WelcomeCard } from "./WelcomeCard";

// Tuning: how many recent grounded turns to look at, and how many of
// them must share the SAME top-cited doc before we auto-scope the thread.
const SCOPE_LOOKBACK = 3;
const SCOPE_MIN_HITS = 2;

function prettyDoc(filename: string): string {
  let s = filename.replace(/\.[a-z0-9]+$/i, "");
  const parts = s.replace(/_/g, "-").split("-").filter(Boolean);
  const deduped: string[] = [];
  for (const p of parts) {
    if (!deduped.length || deduped[deduped.length - 1].toLowerCase() !== p.toLowerCase()) {
      deduped.push(p);
    }
  }
  return deduped.join(" ").trim() || filename;
}

export function ChatInterface() {
  const { messages, send, stop, clear, isStreaming } = useChatStream();
  const activeDocIds = useAppStore((s) => s.activeDocIds);

  // Thread-scope memory: detect when the user has been asking about the
  // same doc across recent turns and quietly scope retrieval to it. The
  // chip above the composer makes the implicit scope visible and gives
  // the user a one-click escape hatch.
  const detectedScope = useMemo(() => {
    const recent = messages
      .filter(
        (m) =>
          m.role === "assistant" &&
          m.answerMode === "grounded" &&
          (m.sources?.length ?? 0) > 0
      )
      .slice(-SCOPE_LOOKBACK);
    if (recent.length < SCOPE_MIN_HITS) return null;
    const docCounts: Record<string, { count: number; filename: string }> = {};
    for (const m of recent) {
      const top = m.sources![0];
      if (!top.doc_id) continue;
      const e = docCounts[top.doc_id] ?? { count: 0, filename: top.filename };
      e.count += 1;
      docCounts[top.doc_id] = e;
    }
    const winners = Object.entries(docCounts)
      .filter(([, v]) => v.count >= SCOPE_MIN_HITS)
      .sort((a, b) => b[1].count - a[1].count);
    if (winners.length === 0) return null;
    const [docId, v] = winners[0];
    return { docId, filename: v.filename, count: v.count };
  }, [messages]);

  const [scopeDismissedFor, setScopeDismissedFor] = useState<string | null>(null);
  const activeThreadScope =
    detectedScope && detectedScope.docId !== scopeDismissedFor && activeDocIds.size === 0
      ? detectedScope
      : null;

  // Broaden-search callback — looks up the user message immediately
  // before the clicked assistant bubble and re-runs with multi-query
  // fan-out for one call. Gives low-confidence answers a second shot
  // without touching the user's global settings.
  const broadenForMessage = (assistantMessageId: string) => {
    const idx = messages.findIndex((m) => m.id === assistantMessageId);
    if (idx <= 0) return;
    // Walk backwards to the previous user turn.
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === "user" && messages[i].content) {
        send(messages[i].content, { broaden: true });
        return;
      }
    }
  };
  const [prefill, setPrefill] = useState<string | undefined>(undefined);
  const [welcome, setWelcome] = useState<WelcomePayload | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Fetch welcome payload once for the empty-state card. Reused as fallback
  // for the inline WelcomeCard on social turns that haven't rehydrated one.
  useEffect(() => {
    let cancelled = false;
    fetchWelcome()
      .then((p) => !cancelled && setWelcome(p))
      .catch(() => {
        /* empty state will gracefully omit — component handles null */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // expose clear to parent via window event (consumed by Header's "New chat")
  useEffect(() => {
    const fn = () => clear();
    window.addEventListener("technova:clear-chat", fn);
    return () => window.removeEventListener("technova:clear-chat", fn);
  }, [clear]);

  const pickSuggestion = (q: string) => {
    setPrefill(undefined);
    send(q);
  };

  const pickDisambiguation = (docId: string, query: string, messageId: string) => {
    // Re-run the original query scoped to the chosen doc. The hook
    // marks the prior assistant bubble as `chosen_doc_id`, then appends
    // a fresh user+assistant pair for the scoped answer.
    if (!query.trim()) return;
    send(query, { preferredDocId: docId, replyToMessageId: messageId });
  };

  const compareAll = (docIds: string[], query: string, _messageId: string) => {
    // Tier 2.2 — kick off the comparison flow. Backend runs one
    // retrieval+generation per doc in parallel and emits a single
    // `comparison` event with all columns.
    if (!query.trim() || docIds.length < 2) return;
    send(query, { compareDocIds: docIds });
  };

  const reRunWithIntent = (rewritten: string) => {
    // Intent Mirror edit: treat the rewrite as a new user turn. The
    // original user message stays in the log above; the new answer is
    // generated from the edited query so retrieval can recover what
    // the agent misread the first time.
    const v = rewritten.trim();
    if (!v) return;
    send(v);
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin">
        {messages.length === 0 ? (
          welcome ? (
            <WelcomeCard payload={welcome} onPickSuggestion={pickSuggestion} />
          ) : null
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
            {messages.map((m, idx) => {
              // Walk back to find the user message that this assistant
              // bubble is responding to. Used by the AccessRequestBanner
              // to include the original query in the audit entry.
              let precedingUserQuery: string | undefined;
              if (m.role === "assistant") {
                for (let i = idx - 1; i >= 0; i--) {
                  if (messages[i].role === "user" && messages[i].content) {
                    precedingUserQuery = messages[i].content;
                    break;
                  }
                }
              }
              return (
                <MessageBubble
                  key={m.id}
                  message={m}
                  precedingUserQuery={precedingUserQuery}
                  onPickSuggestion={pickSuggestion}
                  onPickDisambiguation={pickDisambiguation}
                  onCompareAll={compareAll}
                  onReRunWithIntent={reRunWithIntent}
                  onBroaden={broadenForMessage}
                />
              );
            })}
          </div>
        )}
      </div>

      {activeThreadScope && (
        <div className="px-4 pt-3 pb-0">
          <div className="max-w-3xl mx-auto">
            <div className="inline-flex items-center gap-2 rounded-full border border-accent/30 bg-accent-soft px-3 py-1 text-[11.5px]">
              <Target className="w-3 h-3 text-accent" strokeWidth={2.25} />
              <span className="text-fg-muted">Following up in</span>
              <span className="font-semibold text-fg">
                {prettyDoc(activeThreadScope.filename)}
              </span>
              <span className="text-fg-subtle">
                · {activeThreadScope.count} recent answers
              </span>
              <button
                onClick={() => setScopeDismissedFor(activeThreadScope.docId)}
                className="ml-1 p-0.5 rounded hover:bg-white/60 text-fg-subtle hover:text-fg transition-colors"
                title="Clear scope and search all docs"
              >
                <X className="w-3 h-3" strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </div>
      )}

      <ChatComposer
        onSend={(t) => {
          setPrefill(undefined);
          send(t, {
            threadScopeDocId: activeThreadScope?.docId,
          });
        }}
        onStop={stop}
        isStreaming={isStreaming}
        initialValue={prefill}
      />
    </div>
  );
}
