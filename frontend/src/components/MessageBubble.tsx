import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Clock,
  HelpCircle,
  Info,
  Layers,
  ShieldAlert,
  ShieldX,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  User,
  Zap,
} from "lucide-react";
import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";
import { submitFeedback } from "@/lib/api";
import { AccessRequestBanner } from "./AccessRequestBanner";
import { CitationCheckChip } from "./CitationCheckChip";
import { ComparisonCard } from "./ComparisonCard";
import { DataCard } from "./DataCard";
import { ConfidenceChip } from "./ConfidenceChip";
import { DisambiguationCard } from "./DisambiguationCard";
import { IntentMirror } from "./IntentMirror";
import { RetrievalTrace } from "./RetrievalTrace";
import { SourceCitationCard } from "./SourceCitationCard";
import { WelcomeCard } from "./WelcomeCard";

export function MessageBubble({
  message,
  precedingUserQuery,
  onPickSuggestion,
  onPickDisambiguation,
  onCompareAll,
  onReRunWithIntent,
  onBroaden,
}: {
  message: ChatMessage;
  precedingUserQuery?: string;
  onPickSuggestion?: (q: string) => void;
  onPickDisambiguation?: (docId: string, query: string, messageId: string) => void;
  onCompareAll?: (docIds: string[], query: string, messageId: string) => void;
  onReRunWithIntent?: (rewritten: string, originalQuery: string) => void;
  onBroaden?: (messageId: string) => void;
}) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end"
      >
        <div className="max-w-[85%] flex items-start gap-2.5">
          <div className="order-2 w-7 h-7 shrink-0 rounded-md bg-bg-elevated border border-border flex items-center justify-center mt-0.5">
            <User className="w-3.5 h-3.5 text-fg-muted" strokeWidth={1.5} />
          </div>
          <div className="order-1 rounded-lg px-3.5 py-2 bg-accent text-white">
            <div className="text-[14px] leading-relaxed whitespace-pre-wrap">{message.content}</div>
          </div>
        </div>
      </motion.div>
    );
  }

  // Social: warm welcome card (greetings, thanks, meta-questions). Short-
  // circuits retrieval — no sources, no generation, just a hospitable reply.
  if (message.answerMode === "social") {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
        <div className="flex items-start gap-2.5 max-w-full">
          <div className="w-7 h-7 shrink-0 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center mt-0.5">
            <Sparkles className="w-3.5 h-3.5 text-accent" strokeWidth={1.75} />
          </div>
          <div className="flex-1 min-w-0 card px-4 py-4">
            {message.welcome ? (
              <WelcomeCard
                payload={message.welcome}
                onPickSuggestion={onPickSuggestion ?? (() => {})}
                compact
              />
            ) : (
              <div className="text-[14px] leading-relaxed text-fg">
                {message.content || "Hi — how can I help?"}
              </div>
            )}
          </div>
        </div>
      </motion.div>
    );
  }

  // Refused: amber-red card (L4 only; rare)
  if (message.answerMode === "refused") {
    // RBAC-blocked refused (exec diagnostic) uses the access-request
    // pattern — the exec can still request access for themselves as a
    // way to acknowledge / forward the request.
    if (message.rbacBlocked && precedingUserQuery) {
      return (
        <AccessRequestBanner
          message={message}
          userQuery={precedingUserQuery}
        />
      );
    }
    return (
      <ModeBanner
        icon={<ShieldAlert className="w-3.5 h-3.5 text-clearance-restricted" strokeWidth={1.75} />}
        borderColor="border-clearance-restricted/30"
        bgColor="bg-clearance-restricted/5"
        iconBgColor="bg-clearance-restricted/10 border-clearance-restricted/30"
        eyebrow="Access refused"
        eyebrowColor="text-clearance-restricted"
        content={message.content}
        message={message}
      />
    );
  }

  // Disambiguate: candidate-doc picker. Renders when retrieval found
  // multiple docs with comparable relevance and the agent paused to
  // confirm which one the user actually means. Also exposes a
  // "Compare all" button (Tier 2.2) for when the user wants both docs
  // covered in one turn.
  if (message.answerMode === "disambiguate" && message.disambiguation) {
    return (
      <DisambiguationCard
        message={message}
        onPick={(docId, query, messageId) =>
          onPickDisambiguation?.(docId, query, messageId)
        }
        onCompareAll={
          onCompareAll
            ? (docIds, query, messageId) =>
                onCompareAll(docIds, query, messageId)
            : undefined
        }
      />
    );
  }

  // Comparison: side-by-side columns — one answer per doc. Rendered
  // when the user clicked "Compare all" on a disambiguation card.
  if (message.answerMode === "comparison" && message.comparison?.columns?.length) {
    return <ComparisonCard columns={message.comparison.columns} />;
  }

  // Analytics: data query answered by the SQL analytics agent
  if (message.answerMode === "analytics" && message.analytics) {
    return <DataCard data={message.analytics} />;
  }

  // Blocked: prompt injection guardrail triggered
  if (message.answerMode === "blocked") {
    return (
      <ModeBanner
        icon={<ShieldX className="w-3.5 h-3.5 text-clearance-restricted" strokeWidth={1.75} />}
        borderColor="border-clearance-restricted/30"
        bgColor="bg-clearance-restricted/5"
        iconBgColor="bg-clearance-restricted/10 border-clearance-restricted/30"
        eyebrow="Security guardrail"
        eyebrowColor="text-clearance-restricted"
        content={message.content}
        message={message}
      />
    );
  }

  // Unknown: neutral "no confident answer" card (all non-L4 + garbage +
  // grounded→unknown demotions when the LLM refused on irrelevant chunks).
  // When the block was RBAC-triggered, upgrade to the AccessRequestBanner
  // so the user can action their way out instead of staring at a wall.
  if (message.answerMode === "unknown") {
    if (message.rbacBlocked && precedingUserQuery) {
      return (
        <AccessRequestBanner
          message={message}
          userQuery={precedingUserQuery}
        />
      );
    }
    return (
      <ModeBanner
        icon={<HelpCircle className="w-3.5 h-3.5 text-fg-muted" strokeWidth={1.75} />}
        borderColor="border-border"
        bgColor="bg-surface"
        iconBgColor="bg-bg-elevated border-border"
        eyebrow="No confident answer"
        eyebrowColor="text-fg-muted"
        content={message.content}
        message={message}
      />
    );
  }

  // Grounded / general / meta / system all stream tokens through the
  // bubble. Meta answers "what did I ask earlier" from chat history;
  // general answers off-corpus questions from world knowledge; system
  // answers "show recent queries by users" from audit data. None have
  // doc sources.
  const isGeneral = message.answerMode === "general";
  const isMeta = message.answerMode === "meta";
  const isSystem = message.answerMode === "system";

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex items-start gap-2.5 max-w-full">
        <div
          className={cn(
            "w-7 h-7 shrink-0 rounded-md border flex items-center justify-center mt-0.5",
            isGeneral
              ? "bg-accent-soft border-accent/30"
              : "bg-accent-soft border-accent/30"
          )}
        >
          <Sparkles className="w-3.5 h-3.5 text-accent" strokeWidth={1.75} />
        </div>

        <div className="flex-1 min-w-0 space-y-3">
          {isGeneral && (
            <div className="rounded-md border border-accent/25 bg-accent-soft px-3 py-2 flex items-start gap-2">
              <Info className="w-3.5 h-3.5 text-accent mt-0.5 shrink-0" strokeWidth={1.75} />
              <div className="text-[12px] text-fg leading-relaxed">
                <span className="font-semibold text-accent">General knowledge mode.</span>{" "}
                This question wasn't in your document corpus — answered from the model's
                general knowledge, without source citations.
              </div>
            </div>
          )}
          {isMeta && (
            <div className="rounded-md border border-accent/25 bg-accent-soft px-3 py-2 flex items-start gap-2">
              <Info className="w-3.5 h-3.5 text-accent mt-0.5 shrink-0" strokeWidth={1.75} />
              <div className="text-[12px] text-fg leading-relaxed">
                <span className="font-semibold text-accent">Conversation memory mode.</span>{" "}
                This is a question about our chat itself, so I'm answering from
                this thread's history — no document retrieval.
              </div>
            </div>
          )}
          {isSystem && (
            <div className="rounded-md border border-accent/25 bg-accent-soft px-3 py-2 flex items-start gap-2">
              <Info className="w-3.5 h-3.5 text-accent mt-0.5 shrink-0" strokeWidth={1.75} />
              <div className="text-[12px] text-fg leading-relaxed">
                <span className="font-semibold text-accent">System intelligence mode.</span>{" "}
                Answering from the audit log — recent queries, user activity,
                and platform usage. RBAC-scoped to what your role can see.
              </div>
            </div>
          )}

          {message.intent?.text && (
            <IntentMirror
              intent={message.intent.text}
              original=""
              edited={message.intent.edited}
              onReRun={(rewritten) =>
                onReRunWithIntent?.(rewritten, "")
              }
            />
          )}

          {!message.streaming &&
            (message.answerMode === "grounded" || message.answerMode === "general") &&
            (typeof message.confidence === "number" ||
              message.citationCheck ||
              message.recencyBoostApplied) && (
              <div className="flex items-center gap-2 flex-wrap">
                {typeof message.confidence === "number" && (
                  <ConfidenceChip
                    value={message.confidence}
                    onBroaden={
                      message.confidence < 60
                        ? () => onBroaden?.(message.id)
                        : undefined
                    }
                  />
                )}
                {message.citationCheck && (
                  <CitationCheckChip check={message.citationCheck} />
                )}
                {message.recencyBoostApplied && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 py-[3px] text-[10.5px] font-semibold text-accent"
                    title="Recency-sensitive query: newer documents ranked higher."
                  >
                    <Clock className="w-3 h-3" strokeWidth={2.25} />
                    Newer first
                  </span>
                )}
                {message.topkExpanded && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 py-[3px] text-[10.5px] font-semibold text-accent"
                    title={`Compound query detected (${message.topkExpanded.subQuestions} sub-questions). Auto-expanded retrieval from ${message.topkExpanded.from} → ${message.topkExpanded.to} chunks so each sub-part gets covered.`}
                  >
                    <Layers className="w-3 h-3" strokeWidth={2.25} />
                    +{message.topkExpanded.to - message.topkExpanded.from} chunks
                  </span>
                )}
              </div>
            )}

          <div className="card px-4 py-3">
            {message.content ? (
              <div className="text-[14px] leading-relaxed text-fg prose-like">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
                    ul: ({ children }) => (
                      <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>
                    ),
                    ol: ({ children }) => (
                      <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>
                    ),
                    code: ({ children }) => (
                      <code className="bg-accent-soft border border-accent/15 text-accent rounded px-1.5 py-0.5 text-[12px] font-mono">
                        {children}
                      </code>
                    ),
                    strong: ({ children }) => (
                      <strong className="text-fg font-semibold">{children}</strong>
                    ),
                    a: ({ children, href }) => (
                      <a
                        className="text-accent hover:underline"
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {children}
                      </a>
                    ),
                  }}
                >
                  {highlightSourceTags(message.content)}
                </ReactMarkdown>
              </div>
            ) : message.streaming ? (
              <StreamingDots />
            ) : (
              <div className="text-fg-subtle italic text-[13px]">(no content)</div>
            )}
            {message.streaming && message.content && (
              <span className="inline-block w-1.5 h-[1.05em] bg-accent/80 ml-0.5 align-middle animate-pulse" />
            )}
          </div>

          {!isGeneral && message.sources && message.sources.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
                Sources ({message.sources.length})
              </div>
              {message.sources.map((s) => (
                <SourceCitationCard key={`${s.doc_id}-${s.index}`} source={s} />
              ))}
            </div>
          )}

          {/* Cached indicator */}
          {!message.streaming && message.cached && (
            <div className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 py-[3px] text-[10.5px] font-semibold text-accent">
              <Zap className="w-3 h-3" strokeWidth={2.25} />
              Cached response
            </div>
          )}

          {/* Follow-up question pills */}
          {!message.streaming && message.followups && message.followups.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
                Follow-up questions
              </div>
              <div className="flex flex-wrap gap-1.5">
                {message.followups.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => onPickSuggestion?.(q)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border hover:border-accent/50 bg-surface hover:bg-accent-soft px-3 py-1.5 text-[12px] text-fg-muted hover:text-accent transition-all duration-150 cursor-pointer group"
                  >
                    <ArrowRight className="w-3 h-3 text-fg-subtle group-hover:text-accent transition-colors" strokeWidth={2} />
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Thumbs up/down feedback */}
          {!message.streaming && message.content && (
            <FeedbackButtons message={message} />
          )}

          {!message.streaming && <RetrievalTrace message={message} />}
        </div>
      </div>
    </motion.div>
  );
}

function ModeBanner({
  icon,
  borderColor,
  bgColor,
  iconBgColor,
  eyebrow,
  eyebrowColor,
  content,
  message,
}: {
  icon: React.ReactNode;
  borderColor: string;
  bgColor: string;
  iconBgColor: string;
  eyebrow: string;
  eyebrowColor: string;
  content: string;
  message?: ChatMessage;
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex items-start gap-2.5 max-w-full">
        <div
          className={cn(
            "w-7 h-7 shrink-0 rounded-md border flex items-center justify-center mt-0.5",
            iconBgColor
          )}
        >
          {icon}
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <div className={cn("card px-4 py-3", borderColor, bgColor)}>
            <div className={cn("text-[11px] uppercase tracking-wider font-semibold mb-1", eyebrowColor)}>
              {eyebrow}
            </div>
            <div className="text-[13.5px] leading-relaxed text-fg">{content}</div>
          </div>
          {message && !message.streaming && <RetrievalTrace message={message} />}
        </div>
      </div>
    </motion.div>
  );
}

function FeedbackButtons({ message }: { message: ChatMessage }) {
  const [vote, setVote] = useState<number | null>(message.feedbackVote ?? null);
  const [submitting, setSubmitting] = useState(false);

  const handleVote = async (v: number) => {
    if (submitting) return;
    const newVote = vote === v ? null : v; // toggle off if clicking same
    setVote(newVote);
    if (newVote === null) return; // un-voted, no API call
    setSubmitting(true);
    try {
      // We need thread_id and turn_id. For now, use the message id pattern.
      // The turn_id comes from the backend via the done event; we store a
      // placeholder. In production you'd extract it from the SSE events.
      // For the demo, we send a best-effort call.
      const threadMatch = window.location.pathname.match(/\/t\/([a-z0-9]+)/);
      const threadId = threadMatch?.[1] || "";
      // turn_id: extract numeric suffix from server-generated IDs (srv-123)
      const turnIdMatch = message.id.match(/^srv-(\d+)$/);
      const turnId = turnIdMatch ? parseInt(turnIdMatch[1], 10) : 0;
      if (threadId && turnId) {
        await submitFeedback(threadId, turnId, newVote);
      }
    } catch {
      // Silent fail — demo-grade
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex items-center gap-1 mt-0.5">
      <button
        onClick={() => handleVote(1)}
        className={cn(
          "p-1 rounded-md transition-all duration-150",
          vote === 1
            ? "text-green-600 bg-green-50 border border-green-200"
            : "text-fg-subtle hover:text-green-600 hover:bg-green-50/50"
        )}
        title="Helpful"
      >
        <ThumbsUp className="w-3.5 h-3.5" strokeWidth={vote === 1 ? 2.25 : 1.5} />
      </button>
      <button
        onClick={() => handleVote(-1)}
        className={cn(
          "p-1 rounded-md transition-all duration-150",
          vote === -1
            ? "text-red-500 bg-red-50 border border-red-200"
            : "text-fg-subtle hover:text-red-500 hover:bg-red-50/50"
        )}
        title="Not helpful"
      >
        <ThumbsDown className="w-3.5 h-3.5" strokeWidth={vote === -1 ? 2.25 : 1.5} />
      </button>
    </div>
  );
}

function highlightSourceTags(text: string): string {
  return text.replace(/\[Source (\d+)\]/g, "**[Source $1]**");
}

function StreamingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      <span className="w-1.5 h-1.5 rounded-full bg-accent/80 animate-pulse" />
      <span
        className="w-1.5 h-1.5 rounded-full bg-accent/60 animate-pulse"
        style={{ animationDelay: "150ms" }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-accent/40 animate-pulse"
        style={{ animationDelay: "300ms" }}
      />
      <span className="ml-2 text-[12px] text-fg-muted">Searching &amp; reasoning…</span>
    </div>
  );
}
