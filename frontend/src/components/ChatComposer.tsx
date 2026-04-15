import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export function ChatComposer({
  onSend,
  onStop,
  isStreaming,
  disabled,
  initialValue,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  initialValue?: string;
}) {
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (initialValue !== undefined) {
      setValue(initialValue);
      taRef.current?.focus();
    }
  }, [initialValue]);

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, [value]);

  const submit = () => {
    const t = value.trim();
    if (!t) return;
    onSend(t);
    setValue("");
  };

  return (
    <div className="px-4 pb-4 pt-4 sticky bottom-0 z-10 bg-gradient-to-t from-bg via-bg/95 to-bg/0">
      <div className="max-w-3xl mx-auto">
        <div
          className={cn(
            "card shadow-card overflow-hidden relative transition-all duration-200",
            "focus-within:border-accent/50 focus-within:shadow-accent-glow",
            disabled && "opacity-50"
          )}
        >
          <textarea
            ref={taRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Ask a question about the corpus…"
            disabled={disabled}
            className="w-full resize-none bg-transparent outline-none px-4 py-3 pr-14 text-[14px] placeholder:text-fg-subtle text-fg"
          />
          <button
            onClick={isStreaming ? onStop : submit}
            disabled={disabled || (!isStreaming && !value.trim())}
            className={cn(
              "absolute right-2 bottom-2 w-9 h-9 rounded-md flex items-center justify-center",
              "bg-accent text-white hover:bg-accent-hover shadow-accent-glow",
              "transition-all duration-150 active:scale-95 hover:-translate-y-0.5",
              "disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none disabled:translate-y-0"
            )}
            title={isStreaming ? "Stop" : "Send"}
          >
            {isStreaming ? <Square className="w-3.5 h-3.5" fill="white" /> : <ArrowUp className="w-4 h-4" />}
          </button>
        </div>
        <div className="text-center mt-2 text-[11px] text-fg-subtle">
          Answers are grounded in retrieved sources with inline citations.
          Access is enforced at the vector-store filter.
        </div>
      </div>
    </div>
  );
}
