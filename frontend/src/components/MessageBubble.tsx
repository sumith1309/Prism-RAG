import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import { HelpCircle, Info, ShieldAlert, Sparkles, User } from "lucide-react";
import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";
import { RetrievalTrace } from "./RetrievalTrace";
import { SourceCitationCard } from "./SourceCitationCard";
import { WelcomeCard } from "./WelcomeCard";

export function MessageBubble({
  message,
  onPickSuggestion,
}: {
  message: ChatMessage;
  onPickSuggestion?: (q: string) => void;
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

  // Unknown: neutral "no confident answer" card (all non-L4 + garbage +
  // grounded→unknown demotions when the LLM refused on irrelevant chunks).
  if (message.answerMode === "unknown") {
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
