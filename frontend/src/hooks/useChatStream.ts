import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { getThread, streamChat } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import type { AnswerMode, ChatMessage, ThreadTurn } from "@/types";
import { pingThreadsChanged } from "./useThreads";

const uid = () => Math.random().toString(36).slice(2, 10);

function turnToMessage(turn: ThreadTurn): ChatMessage {
  const msg: ChatMessage = {
    id: `srv-${turn.id}`,
    role: turn.role,
    content: turn.content,
    sources: turn.sources,
    refused: turn.refused,
    answerMode: turn.answer_mode,
    streaming: false,
  };
  if (turn.answer_mode === "disambiguate" && turn.disambiguation) {
    msg.disambiguation = {
      query: turn.disambiguation.query || "",
      candidates: turn.disambiguation.candidates || [],
      chosen_doc_id: turn.disambiguation.chosen_doc_id,
    };
  }
  if (turn.answer_mode === "comparison" && turn.comparison) {
    msg.comparison = {
      query: "",
      columns: turn.comparison.columns || [],
    };
  }
  return msg;
}

export function useChatStream() {
  const { threadId: urlThreadId } = useParams<{ threadId?: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingThread, setIsLoadingThread] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const pendingNavRef = useRef<string | null>(null);
  // Live thread id. Must stay in sync with the current conversation
  // WITHOUT waiting for React Router, because we update the URL via
  // `window.history.replaceState` after a new thread is created
  // (to avoid remounting mid-stream). replaceState bypasses the router,
  // so `useParams` stays stale — any subsequent send() would read
  // `thread_id: null` and the backend would create yet another thread.
  // This ref is the single source of truth for outgoing requests.
  const activeThreadRef = useRef<string | null>(urlThreadId ?? null);
  const { activeDocIds, settings } = useAppStore();

  // Keep the ref in sync when the URL changes from outside this hook
  // (user clicks a thread in the sidebar, browser back/forward, etc.).
  useEffect(() => {
    activeThreadRef.current = urlThreadId ?? null;
  }, [urlThreadId]);

  // When URL thread id changes, load that thread's history.
  useEffect(() => {
    let cancelled = false;
    if (!urlThreadId) {
      setMessages([]);
      return;
    }
    setIsLoadingThread(true);
    getThread(urlThreadId)
      .then((detail) => {
        if (cancelled) return;
        setMessages(detail.turns.map(turnToMessage));
      })
      .catch((e) => {
        if (cancelled) return;
        toast.error(e.message || "Failed to load thread");
        navigate("/app", { replace: true });
      })
      .finally(() => !cancelled && setIsLoadingThread(false));
    return () => {
      cancelled = true;
    };
  }, [urlThreadId, navigate]);

  const send = useCallback(
    async (
      query: string,
      opts?: {
        // Agent path: user picked a doc from the disambiguation card.
        // We mark the prior assistant bubble with `chosen_doc_id` so
        // the UI can dim the un-picked candidates, and scope the new
        // retrieval to just that doc.
        preferredDocId?: string;
        replyToMessageId?: string;
        // Agent path: user edited the Intent Mirror pill. Sends the
        // rewritten query as `override_intent` so retrieval uses it
        // while the user's original message remains in the chat bubble.
        overrideIntent?: string;
        // Agent path: user clicked "Broaden" on a low-confidence chip.
        // Re-runs this query once with multi-query fan-out (ignores
        // global settings — temporary boost for just this call).
        broaden?: boolean;
        // Thread-memory scope. When set, retrieval is soft-filtered
        // to this doc (caller computes from recent turns). Explicit
        // activeDocIds always win over this.
        threadScopeDocId?: string;
        // Tier 2.2: user clicked "Compare all" on a disambiguation card.
        // Backend runs retrieval + generation once per doc in parallel
        // and emits a single `comparison` event with all columns.
        compareDocIds?: string[];
      }
    ) => {
      const trimmed = query.trim();
      if (!trimmed || isStreaming) return;

      // If this is a disambiguation retry, update the previous assistant
      // bubble to record the user's choice BEFORE appending the new
      // assistant message — keeps the chat replay coherent.
      if (opts?.replyToMessageId && opts.preferredDocId) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === opts.replyToMessageId && m.disambiguation
              ? {
                  ...m,
                  disambiguation: {
                    ...m.disambiguation,
                    chosen_doc_id: opts.preferredDocId,
                  },
                }
              : m
          )
        );
      }

      const userMsg: ChatMessage = { id: uid(), role: "user", content: trimmed };
      const assistantMsg: ChatMessage = {
        id: uid(),
        role: "assistant",
        content: "",
        sources: [],
        streaming: true,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);

      const history = messages
        .filter((m) => !m.streaming && m.content)
        .map((m) => ({ role: m.role, content: m.content }));

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setIsStreaming(true);
      pendingNavRef.current = null;

      // Compute the effective doc_ids filter:
      //   1. Explicit activeDocIds (from knowledge sidebar) wins — user
      //      said "scope to these docs" and we respect it.
      //   2. Else, if a thread-scope doc is provided AND no preferredDocId
      //      is set (which takes precedence via its own path), use it.
      const explicitScope = Array.from(activeDocIds);
      const effectiveDocIds =
        explicitScope.length > 0
          ? explicitScope
          : opts?.threadScopeDocId && !opts?.preferredDocId
          ? [opts.threadScopeDocId]
          : [];

      try {
        await streamChat(
          {
            query: trimmed,
            doc_ids: effectiveDocIds,
            use_hyde: settings.useHyde,
            use_rerank: settings.useRerank,
            use_multi_query: settings.useMultiQuery || !!opts?.broaden,
            use_corrective: settings.useCorrective,
            use_faithfulness: settings.useFaithfulness,
            section_filter: settings.sectionFilter.length ? settings.sectionFilter : undefined,
            top_k: settings.topK,
            history,
            thread_id: activeThreadRef.current,
            preferred_doc_id: opts?.preferredDocId ?? null,
            skip_disambiguation: !!opts?.preferredDocId,
            override_intent: opts?.overrideIntent ?? null,
            compare_doc_ids: opts?.compareDocIds ?? [],
          },
          {
            onThread: (threadId, _title, isNew) => {
              // Update the live thread id immediately so ANY follow-up
              // send() during the same session targets the same thread,
              // even if the user types before React Router catches up.
              activeThreadRef.current = threadId;
              if (isNew && !urlThreadId) {
                // Stash — navigate only after `done` so SSE isn't interrupted by unmount.
                pendingNavRef.current = threadId;
              }
            },
            onSources: (sources) =>
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantMsg.id ? { ...m, sources } : m))
              ),
            onToken: (delta) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, content: m.content + delta } : m
                )
              ),
            onRefused: (msg, rbacBlocked) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        refused: true,
                        rbacBlocked,
                        answerMode: "refused" as AnswerMode,
                        streaming: false,
                        sources: [],
                      }
                    : m
                )
              ),
            onGeneral: (_msg) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, answerMode: "general" as AnswerMode, sources: [] }
                    : m
                )
              ),
            onUnknown: (msg, rbacBlocked) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        refused: true,
                        rbacBlocked,
                        answerMode: "unknown" as AnswerMode,
                        streaming: false,
                        sources: [],
                      }
                    : m
                )
              ),
            onCached: () =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, cached: true } : m
                )
              ),
            onCorrective: (rewritten) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, corrective_rewrite: rewritten }
                    : m
                )
              ),
            onContextualized: (rewritten) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, contextualized_query: rewritten }
                    : m
                )
              ),
            onAnswerReset: () =>
              // Server is restarting the answer (e.g. grounded refusal
              // → general fallback for L4). Wipe the streamed tokens
              // so the new answer doesn't append to the old refusal.
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, content: "", sources: [], faithfulness: undefined }
                    : m
                )
              ),
            onWelcome: (payload) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: payload.greeting,
                        answerMode: "social" as AnswerMode,
                        welcome: payload,
                        sources: [],
                        streaming: false,
                      }
                    : m
                )
              ),
            onDisambiguate: (q, candidates, msg) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        answerMode: "disambiguate" as AnswerMode,
                        disambiguation: { query: q, candidates },
                        sources: [],
                        streaming: false,
                      }
                    : m
                )
              ),
            onIntent: (intent, _original, edited) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, intent: { text: intent, edited } }
                    : m
                )
              ),
            onCitationCheck: (check) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, citationCheck: check } : m
                )
              ),
            onComparison: (q, columns) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        answerMode: "comparison" as AnswerMode,
                        comparison: { query: q, columns },
                        sources: [],
                        streaming: false,
                      }
                    : m
                )
              ),
            onRecencyBoost: () =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, recencyBoostApplied: true }
                    : m
                )
              ),
            onTopKExpanded: (from, to, subQuestions) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, topkExpanded: { from, to, subQuestions } }
                    : m
                )
              ),
            onFollowups: (questions) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, followups: questions }
                    : m
                )
              ),
            onBlocked: (msg, _reason) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        answerMode: "blocked" as AnswerMode,
                        streaming: false,
                        sources: [],
                      }
                    : m
                )
              ),
            onDone: (answerMode, thread_id, meta) => {
              const finalMode = (answerMode as AnswerMode) || "grounded";
              // Backend can demote grounded → unknown post-generation when the
              // LLM refused despite retrieved chunks (e.g., off-topic query
              // that pulled up unrelated docs). Drop the stale sources in that
              // case so the UI matches the authoritative final mode.
              const stripSources =
                finalMode === "unknown" ||
                finalMode === "refused" ||
                finalMode === "general" ||
                finalMode === "meta" ||
                finalMode === "system" ||
                finalMode === "disambiguate" ||
                finalMode === "comparison" ||
                finalMode === "blocked";
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        streaming: false,
                        answerMode: finalMode,
                        sources: stripSources ? [] : m.sources,
                        latency_ms: meta.latency_ms,
                        tokens: meta.tokens,
                        cached: meta.cached ?? m.cached,
                        corrective_retries: meta.corrective_retries,
                        faithfulness: meta.faithfulness,
                        confidence: meta.confidence ?? null,
                        rbacBlocked: meta.rbac_blocked ?? m.rbacBlocked,
                        citationCheck: meta.citation_check ?? m.citationCheck ?? null,
                      }
                    : m
                )
              );
              pingThreadsChanged();
              const navTarget = pendingNavRef.current || (!urlThreadId ? thread_id : null);
              if (navTarget) {
                window.history.replaceState(null, "", `/app/t/${navTarget}`);
              }
              pendingNavRef.current = null;
            },
            onError: (msg) => {
              toast.error(`Stream error: ${msg}`);
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, streaming: false, content: m.content || `⚠️ ${msg}` }
                    : m
                )
              );
            },
          },
          ctrl.signal
        );
      } catch (e: any) {
        if (e?.name !== "AbortError") {
          toast.error(`Chat failed: ${e?.message || e}`);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMsg.id ? { ...m, streaming: false } : m))
        );
      }
    },
    [activeDocIds, isStreaming, messages, settings, urlThreadId]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    if (urlThreadId) navigate("/app", { replace: false });
  }, [urlThreadId, navigate]);

  return { messages, send, stop, clear, isStreaming, isLoadingThread };
}
