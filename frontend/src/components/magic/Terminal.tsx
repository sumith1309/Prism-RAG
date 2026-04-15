import { useEffect, useState } from "react";
import { motion, useInView } from "framer-motion";
import { Check, Copy } from "lucide-react";
import { useRef } from "react";
import { cn } from "@/lib/utils";

export interface TerminalLine {
  prompt?: string; // e.g., "$" or null for raw output
  text: string;
  delay?: number; // seconds before this line starts typing
  output?: boolean; // no prompt, styled as stdout
}

/** Terminal window with line-by-line typing animation on scroll-into-view. */
export function Terminal({
  lines,
  title = "zsh",
  className,
}: {
  lines: TerminalLine[];
  title?: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  const [started, setStarted] = useState(false);

  useEffect(() => {
    if (inView) setStarted(true);
  }, [inView]);

  return (
    <div
      ref={ref}
      className={cn(
        "rounded-xl border border-light-border bg-[#0f0f12] shadow-light-pop overflow-hidden",
        className
      )}
    >
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-white/5 bg-[#16161a]">
        <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
        <span className="ml-2 text-[10px] text-white/40 font-mono">{title}</span>
      </div>
      <pre className="p-4 text-[12.5px] leading-relaxed text-white/90 font-mono min-h-[180px]">
        {started &&
          lines.map((ln, i) => <TerminalLineRow key={i} line={ln} index={i} />)}
      </pre>
    </div>
  );
}

function TerminalLineRow({ line, index }: { line: TerminalLine; index: number }) {
  const [shown, setShown] = useState("");
  const [typing, setTyping] = useState(false);
  const [done, setDone] = useState(false);
  const delayMs = Math.round((line.delay ?? index * 0.5) * 1000);

  useEffect(() => {
    const start = setTimeout(() => {
      setTyping(true);
      let i = 0;
      const interval = setInterval(() => {
        i += 1;
        setShown(line.text.slice(0, i));
        if (i >= line.text.length) {
          clearInterval(interval);
          setTyping(false);
          setDone(true);
        }
      }, 18);
      return () => clearInterval(interval);
    }, delayMs);
    return () => clearTimeout(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex">
      {!line.output && (
        <span className="text-accent/80 select-none mr-2">{line.prompt ?? "$"}</span>
      )}
      <span
        className={cn(
          "whitespace-pre-wrap",
          line.output ? "text-white/60" : "text-white/95"
        )}
      >
        {shown}
        {typing && !done && (
          <motion.span
            animate={{ opacity: [1, 0] }}
            transition={{ duration: 0.6, repeat: Infinity }}
            className="inline-block w-[7px] h-[1.05em] bg-accent align-middle ml-0.5"
          />
        )}
      </span>
    </div>
  );
}

/** Pure copy-to-clipboard pill — used next to install commands. */
export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] text-light-fgMuted hover:text-light-fg px-2 py-1 rounded-md border border-light-border bg-white hover:bg-light-elevated transition-colors",
        className
      )}
    >
      {copied ? (
        <>
          <Check className="w-3 h-3 text-clearance-public" /> Copied
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" /> Copy
        </>
      )}
    </button>
  );
}
