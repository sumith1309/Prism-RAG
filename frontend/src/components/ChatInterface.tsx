import { useEffect, useRef, useState } from "react";
import { useChatStream } from "@/hooks/useChatStream";
import { fetchWelcome } from "@/lib/api";
import type { WelcomePayload } from "@/types";
import { ChatComposer } from "./ChatComposer";
import { MessageBubble } from "./MessageBubble";
import { WelcomeCard } from "./WelcomeCard";

export function ChatInterface() {
  const { messages, send, stop, clear, isStreaming } = useChatStream();
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

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin">
        {messages.length === 0 ? (
          welcome ? (
            <WelcomeCard payload={welcome} onPickSuggestion={pickSuggestion} />
          ) : null
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onPickSuggestion={pickSuggestion}
              />
            ))}
          </div>
        )}
      </div>

      <ChatComposer
        onSend={(t) => {
          setPrefill(undefined);
          send(t);
        }}
        onStop={stop}
        isStreaming={isStreaming}
        initialValue={prefill}
      />
    </div>
  );
}
