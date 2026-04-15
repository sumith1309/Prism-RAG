import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { getThread, streamChat } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import type { AnswerMode, ChatMessage, ThreadTurn } from "@/types";
import { pingThreadsChanged } from "./useThreads";

const uid = () => Math.random().toString(36).slice(2, 10);

function turnToMessage(turn: ThreadTurn): ChatMessage {
  return {
    id: `srv-${turn.id}`,
    role: turn.role,
    content: turn.content,
    sources: turn.sources,
    refused: turn.refused,
    answerMode: turn.answer_mode,
    streaming: false,
  };
}

export function useChatStream() {
  const { threadId: urlThreadId } = useParams<{ threadId?: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingThread, setIsLoadingThread] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const pendingNavRef = useRef<string | null>(null);
  const { activeDocIds, settings } = useAppStore();

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
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || isStreaming) return;

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

      try {
        await streamChat(
          {
            query: trimmed,
            doc_ids: Array.from(activeDocIds),
            use_hyde: settings.useHyde,
            use_rerank: settings.useRerank,
            use_multi_query: settings.useMultiQuery,
            use_corrective: settings.useCorrective,
            use_faithfulness: settings.useFaithfulness,
            section_filter: settings.sectionFilter.length ? settings.sectionFilter : undefined,
            top_k: settings.topK,
            history,
            thread_id: urlThreadId ?? null,
          },
          {
            onThread: (threadId, _title, isNew) => {
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
            onRefused: (msg) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        refused: true,
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
            onUnknown: (msg) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: msg,
                        refused: true,
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
                finalMode === "system";
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
