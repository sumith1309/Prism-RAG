import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Database,
  Gauge,
  Github,
  Lock,
  Shield,
  ShieldAlert,
  Sparkles,
  Upload,
} from "lucide-react";

import { BentoCard, BentoGrid } from "@/components/magic/BentoGrid";
import { NumberTicker } from "@/components/magic/NumberTicker";
import { CopyButton, Terminal } from "@/components/magic/Terminal";

export function LandingPage() {
  return (
    <div className="min-h-screen w-full bg-light-bg text-light-fg">
      <Nav />
      <Hero />
      <PipelineShowcase />
      <StatsStrip />
      <FeatureBento />
      <CliSection />
      <ClosingCTA />
      <Footer />
    </div>
  );
}

// ─── Nav ─────────────────────────────────────────────────────────────────
function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <nav
      className={`sticky top-0 z-30 w-full border-b transition-all ${
        scrolled
          ? "border-light-border bg-white/85 backdrop-blur-lg"
          : "border-transparent bg-transparent"
      }`}
    >
      <div className="max-w-6xl mx-auto flex items-center justify-between px-6 py-3.5">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-light-accent/10 border border-light-accent/20 flex items-center justify-center">
            <Shield className="w-4 h-4 text-light-accent" strokeWidth={1.75} />
          </div>
          <span className="text-[14px] font-semibold tracking-tight text-light-fg">
            Prism RAG
          </span>
        </Link>
        <div className="flex items-center gap-5 text-[13px] text-light-fgMuted">
          <Link
            to="/pipeline"
            className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-light-accent/30 bg-light-accent/5 hover:bg-light-accent/10 hover:border-light-accent/50 text-light-accent transition-all font-semibold"
          >
            <span className="relative flex w-2 h-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-light-accent opacity-75 animate-ping" />
              <span className="relative inline-flex rounded-full w-2 h-2 bg-light-accent" />
            </span>
            Pipeline Lab
            <span className="text-[9.5px] uppercase tracking-wider px-1 py-px rounded bg-light-accent/15">LIVE</span>
          </Link>
          <a href="#features" className="hidden sm:inline hover:text-light-fg transition-colors">
            Features
          </a>
          <a href="#cli" className="hidden sm:inline hover:text-light-fg transition-colors">
            CLI
          </a>
          <Link
            to="/signin"
            className="inline-flex items-center gap-1.5 text-light-fgMuted hover:text-light-fg transition-colors"
          >
            Sign in <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

// ─── Hero ────────────────────────────────────────────────────────────────
const HEAD_LINE_1 = ["A", "knowledge", "base"];
const HEAD_LINE_2 = ["that", "answers", "only", "what", "you're", "cleared", "to", "see."];

function Hero() {
  return (
    <section className="max-w-5xl mx-auto px-6 pt-24 pb-16 sm:pt-32 sm:pb-20">
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-light-surface border border-light-border"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-light-accent" />
        <span className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-fgMuted">
          Retrieval · Access control · Observability
        </span>
      </motion.div>

      <h1 className="mt-6 text-[44px] sm:text-[60px] leading-[1.04] font-semibold tracking-tight text-light-fg max-w-4xl">
        <StaggerLine words={HEAD_LINE_1} delay={0.1} />
        <br />
        <StaggerLine words={HEAD_LINE_2} delay={0.25} gradient />
      </h1>

      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.9, duration: 0.45 }}
        className="mt-6 text-[16px] sm:text-[17px] text-light-fgMuted max-w-2xl leading-relaxed"
      >
        A retrieval-augmented chat platform with a six-mode answer engine,
        per-role visibility controls, and a public Pipeline Lab where anyone
        can watch the entire RAG system run live — enforced at the vector-store
        filter, not the prompt.
      </motion.p>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.05, duration: 0.45 }}
        className="mt-8 flex flex-wrap items-center gap-3"
      >
        <HangingCTA to="/pipeline">
          <span className="relative flex w-1.5 h-1.5 mr-0.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-white opacity-75 animate-ping" />
            <span className="relative inline-flex rounded-full w-1.5 h-1.5 bg-white" />
          </span>
          Try the Pipeline Lab <ArrowRight className="w-4 h-4" />
        </HangingCTA>
        <Link
          to="/signin"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md border border-light-border bg-white text-light-fg text-[14px] font-semibold hover:border-light-accent/50 hover:text-light-accent transition-all"
        >
          Sign in
          <ArrowRight className="w-4 h-4" />
        </Link>
        <span className="text-[11.5px] text-light-fgSubtle">
          No sign-in required to try the Lab.
        </span>
      </motion.div>
    </section>
  );
}

function StaggerLine({
  words,
  delay = 0,
  gradient = false,
}: {
  words: string[];
  delay?: number;
  gradient?: boolean;
}) {
  return (
    <span className="inline-block">
      {words.map((w, i) => (
        <motion.span
          key={`${w}-${i}`}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: delay + i * 0.06, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          className={`inline-block mr-[0.28em] ${
            gradient
              ? "bg-gradient-to-br from-light-accent via-[#8e74ff] to-[#b89eff] bg-clip-text text-transparent"
              : ""
          }`}
        >
          {w}
        </motion.span>
      ))}
    </span>
  );
}

function HangingCTA({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-light-accent text-white text-[14px] font-semibold hover:bg-light-accentHover hover:-translate-y-0.5 transition-all shadow-light-hang"
    >
      {children}
    </Link>
  );
}

// ─── Pipeline Showcase — flagship public feature callout ──────────────
function PipelineShowcase() {
  const stages = [
    { n: "01", label: "Embed", model: "MiniLM-L6 · 384d", colour: "#6366f1" },
    { n: "02", label: "Retrieve", model: "Qdrant + BM25", colour: "#3b82f6" },
    { n: "03", label: "Fuse + Rerank", model: "RRF · BGE-reranker", colour: "#a855f7" },
    { n: "04", label: "Generate + Judge", model: "gpt-4o-mini", colour: "#22c55e" },
  ];
  return (
    <section className="relative max-w-5xl mx-auto px-6 mb-16">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="rounded-2xl border border-light-border bg-white shadow-light-card overflow-hidden"
      >
        <div className="px-7 py-6 sm:px-10 sm:py-9 grid sm:grid-cols-[1.2fr_1fr] gap-8 items-center">
          <div>
            <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-accent mb-3">
              Public Pipeline Lab · no sign-in
            </div>
            <h2 className="text-[24px] sm:text-[28px] leading-[1.2] font-semibold tracking-tight text-light-fg">
              See the entire RAG pipeline run live.
            </h2>
            <p className="mt-3 text-[13.5px] text-light-fgMuted leading-relaxed max-w-lg">
              Type a question — watch every stage fire in sequence with real
              data: embedding heatmap, chunk rank journey, side-by-side
              compare mode, and the faithfulness judge.
            </p>
            <div className="mt-5 flex items-center gap-3">
              <Link
                to="/pipeline"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-light-fg text-white text-[13px] font-semibold hover:bg-light-accent transition-colors"
              >
                Try it now
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
              <span className="text-[11px] text-light-fgSubtle">
                ~3–5s per query
              </span>
            </div>
          </div>

          <div className="space-y-1.5">
            {stages.map((s) => (
              <div
                key={s.label}
                className="flex items-center gap-3 rounded-md border border-light-border bg-light-bg/40 px-3 py-2"
              >
                <span
                  className="text-[10.5px] font-mono font-semibold tabular-nums"
                  style={{ color: s.colour }}
                >
                  {s.n}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] font-semibold text-light-fg">
                    {s.label}
                  </div>
                  <div className="text-[10px] text-light-fgSubtle font-mono truncate">
                    {s.model}
                  </div>
                </div>
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: s.colour }}
                />
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </section>
  );
}

// ─── Stats strip ─────────────────────────────────────────────────────────
function StatsStrip() {
  // Documents + chunks are LIVE from /api/health — upload a doc and this
  // strip reflects the new count after ~30s. Answer modes, tests, and
  // RBAC-leaks-blocked are baseline facts about the codebase itself
  // (not the corpus), so they stay static.
  const [live, setLive] = useState<{ docs: number; chunks: number } | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && typeof d.docs_count === "number") {
          setLive({ docs: d.docs_count, chunks: d.chunks_count ?? 0 });
        }
      })
      .catch(() => {
        /* fall back to static values below */
      });
  }, []);

  const items = [
    { label: "Documents", value: live?.docs ?? 13, suffix: "", dynamic: true },
    { label: "Answer modes", value: 6, suffix: "", dynamic: false },
    { label: "Indexed chunks", value: live?.chunks ?? 145, suffix: "", dynamic: true },
    { label: "Integration tests", value: 38, suffix: "", dynamic: false },
    { label: "RBAC leaks blocked", value: 100, suffix: "%", dynamic: false },
  ];
  return (
    <section className="border-y border-light-border bg-white">
      <div className="max-w-5xl mx-auto px-6 py-12 grid grid-cols-2 sm:grid-cols-5 gap-6">
        {items.map((it) => (
          <div key={it.label} className="text-center relative">
            <div className="text-[30px] sm:text-[34px] font-semibold text-light-fg tabular-nums tracking-tight">
              <NumberTicker value={it.value} suffix={it.suffix} />
            </div>
            <div className="text-[10.5px] uppercase tracking-[0.12em] text-light-fgSubtle mt-1.5 font-medium inline-flex items-center gap-1.5">
              {it.label}
              {it.dynamic && live && (
                <span
                  className="relative flex w-1.5 h-1.5"
                  title="Live from /api/health"
                >
                  <span className="absolute inline-flex h-full w-full rounded-full bg-clearance-public opacity-75 animate-ping" />
                  <span className="relative inline-flex rounded-full w-1.5 h-1.5 bg-clearance-public" />
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Feature Bento ───────────────────────────────────────────────────────
function FeatureBento() {
  return (
    <section id="features" className="max-w-5xl mx-auto px-6 py-24">
      <div className="max-w-2xl mb-12">
        <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-accent">
          Capabilities
        </div>
        <h2 className="mt-2 text-[30px] sm:text-[36px] leading-[1.15] font-semibold tracking-tight text-light-fg">
          Everything a production RAG stack needs.
        </h2>
        <p className="mt-3 text-[14.5px] text-light-fgMuted leading-relaxed max-w-xl">
          Hybrid retrieval, smart refusal, observability, and access control —
          each enforced where it counts, each measured, each explainable.
        </p>
      </div>

      <BentoGrid>
        <BentoCard
          span="2"
          accent
          icon={<Cpu className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Six-mode answer engine"
          description="Grounded, refused, general, unknown, social greetings, and system intelligence — each routed by a dedicated detector before retrieval. Conversational follow-ups rewritten from thread history. Off-corpus questions gracefully fall back to general knowledge."
        />

        <BentoCard
          icon={<Lock className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="RBAC at the filter layer"
          description="Four clearance levels enforced inside Qdrant's where-clause. Plus an exec-only switch to hide any document from any subset of roles, atomically across the registry, vector index, and BM25 store."
        />

        <BentoCard
          icon={<Gauge className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Faithfulness scoring"
          description="Every grounded answer is scored 0–1 by an LLM judge. Refusal-phrase detection demotes weakly-grounded responses automatically, so misleading sources never reach the user."
        />

        <BentoCard
          icon={<Database className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Hybrid retrieval"
          description="Dense vectors via Qdrant plus BM25 lexical search, fused with RRF and reranked by BGE cross-encoder. Combined recall beats either alone on technical jargon and proper nouns."
        />

        <BentoCard
          icon={<ShieldAlert className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Executive analytics"
          description="Donut, gauge, Sankey, day-by-hour heatmap, latency bars, sparkline KPIs. Built directly from the audit log — every query, every refusal, every faithfulness score."
        />

        <BentoCard
          icon={<Upload className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Uploads with provenance"
          description="Every doc carries its uploader's identity on a visible chip. Clearance-capped at upload, instantly re-classifiable by exec — no re-ingest required."
        />

        <BentoCard
          span="2"
          icon={<Sparkles className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Observability on every message"
          description="Each chat turn exposes its full pipeline: per-stage latency bars, token counts, per-chunk RRF and rerank scores, faithfulness badge, contextualization rewrites, corrective retries. Nothing hidden, nothing claimed without a number behind it."
        />
      </BentoGrid>
    </section>
  );
}

// ─── CLI section ─────────────────────────────────────────────────────────
function CliSection() {
  const repoUrl = "https://github.com/sumith1309/Prism-RAG";
  const installCmd =
    "git clone git@github.com:sumith1309/Prism-RAG.git && cd Prism-RAG/homework-basic && ./setup.sh && source .venv/bin/activate && python rag_cli.py";

  return (
    <section id="cli" className="max-w-6xl mx-auto px-6 py-24">
      <div className="grid lg:grid-cols-[1.05fr_1fr] gap-10 items-center">
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-light-accent">
            HW1 · Python CLI
          </div>
          <h2 className="mt-2 text-[30px] sm:text-[36px] leading-tight font-semibold tracking-tight text-light-fg">
            Run the same retrieval stack in your terminal.
          </h2>
          <p className="mt-3 text-[14.5px] text-light-fgMuted leading-relaxed max-w-xl">
            A single-file, ~320-line Python CLI that indexes any PDF into Qdrant, runs
            dense + BM25 retrieval side-by-side, fuses with RRF, and calls GPT-4o-mini
            for grounded generation. Uses RFC 7519 (JSON Web Tokens) by default — the
            same auth spec powering this web app.
          </p>

          <ul className="mt-6 space-y-2 text-[13px] text-light-fgMuted">
            {[
              "Qdrant in Docker (shared with the web app)",
              "Configurable chunk size + overlap (defaults 500 / 100)",
              "all-MiniLM-L6-v2 embeddings (384-d, CPU-fast)",
              "Interactive loop with `quit` sentinel",
              "Prints the full assembled RAG prompt before generation",
              "Optional GPT-4o-mini answer if OPENAI_API_KEY is set",
            ].map((s) => (
              <li key={s} className="flex items-start gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-clearance-public mt-0.5 shrink-0" strokeWidth={2} />
                <span>{s}</span>
              </li>
            ))}
          </ul>

          <div className="mt-7 flex flex-wrap items-center gap-2.5">
            <a
              href={repoUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-light-accent text-white text-[13px] font-semibold hover:bg-light-accentHover shadow-light-hang transition-colors"
            >
              <Github className="w-4 h-4" /> Open on GitHub
            </a>
            <CopyButton text={installCmd} />
            <span className="text-[11px] text-light-fgSubtle">
              Copy to paste into any terminal.
            </span>
          </div>
        </div>

        <Terminal
          title="Prism-RAG / homework-basic · zsh"
          lines={[
            { prompt: "$", text: "git clone git@github.com:sumith1309/Prism-RAG.git", delay: 0.2 },
            { prompt: "$", text: "cd Prism-RAG/homework-basic && ./setup.sh", delay: 1.6 },
            {
              output: true,
              text: "==> Python virtual environment\n==> Downloading RFC 7519 PDF\n==> Starting Qdrant on :6333\n==> Done.",
              delay: 2.8,
            },
            { prompt: "$", text: "source .venv/bin/activate", delay: 4.8 },
            { prompt: "$", text: "python rag_cli.py", delay: 5.6 },
            {
              output: true,
              text: "Loading PDF: data/rfc7519_jwt.pdf\n  pages=30  chunks=43  (size=500, overlap=100)\nReady. Generation: gpt-4o-mini (OPENAI_API_KEY set)",
              delay: 6.8,
            },
            { prompt: "?", text: "How is a JWT signature validated?", delay: 9.6 },
          ]}
        />
      </div>
    </section>
  );
}

// ─── Closing CTA ────────────────────────────────────────────────────────
function ClosingCTA() {
  return (
    <section className="max-w-5xl mx-auto px-6 py-20 text-center">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
      >
        <h2 className="text-[28px] sm:text-[32px] font-semibold tracking-tight text-light-fg">
          Four roles. One query. Four honest answers.
        </h2>
        <p className="mt-3 text-[14px] text-light-fgMuted max-w-lg mx-auto">
          Seeded demo accounts — guest, employee, manager, executive — let you
          walk through every access boundary in under two minutes.
        </p>
        <div className="mt-7 flex items-center justify-center gap-3 flex-wrap">
          <Link
            to="/signin"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md bg-light-fg text-white text-[13px] font-semibold hover:bg-light-accent transition-colors"
          >
            Sign in
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <Link
            to="/pipeline"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md border border-light-border bg-white text-light-fg text-[13px] font-semibold hover:border-light-accent/50 hover:text-light-accent transition-all"
          >
            Pipeline Lab
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </motion.div>
    </section>
  );
}

// ─── Footer ─────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="border-t border-light-border bg-light-surface">
      <div className="max-w-6xl mx-auto px-6 py-8 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 text-[12px] text-light-fgMuted">
          <Shield className="w-3.5 h-3.5 text-light-accent" strokeWidth={1.75} />
          <span className="font-medium text-light-fg">Prism RAG</span>
          <span className="opacity-60">·</span>
          <span>Session 2 · Advanced Gen-AI</span>
        </div>
        <div className="text-[12px] text-light-fgSubtle">
          Qdrant · FastAPI · React · magic-ui · bge-reranker
        </div>
      </div>
    </footer>
  );
}
