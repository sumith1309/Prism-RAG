import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Database,
  Gauge,
  Github,
  Lock,
  MessagesSquare,
  Shield,
  ShieldAlert,
  Sparkles,
  Terminal as TerminalIcon,
  Upload,
} from "lucide-react";

import { AnimatedBeamPipeline } from "@/components/magic/AnimatedBeam";
import { BentoCard, BentoGrid } from "@/components/magic/BentoGrid";
import { BorderBeam } from "@/components/magic/BorderBeam";
import { NumberTicker } from "@/components/magic/NumberTicker";
import { CopyButton, Terminal } from "@/components/magic/Terminal";
import { PlaygroundSection } from "@/components/landing/PlaygroundSection";

export function LandingPage() {
  return (
    <div className="min-h-screen w-full bg-light-bg text-light-fg">
      <Nav />
      <Hero />
      <StatsStrip />
      <FeatureBento />
      <PlaygroundSection />
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
          <a href="#playground" className="hidden sm:inline hover:text-light-fg transition-colors">
            Playground
          </a>
          <a href="#cli" className="hidden sm:inline hover:text-light-fg transition-colors">
            CLI
          </a>
          <a href="#features" className="hidden sm:inline hover:text-light-fg transition-colors">
            Features
          </a>
          <Link
            to="/signin"
            className="inline-flex items-center gap-1.5 text-light-accent font-medium hover:text-light-accentHover"
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
    <section className="max-w-6xl mx-auto px-6 pt-20 pb-20 sm:pt-28 sm:pb-24">
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-light-surface border border-light-border shadow-light-sm"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-light-accent animate-pulse" />
        <span className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted">
          Session 2 · Advanced Gen-AI
        </span>
      </motion.div>

      <h1 className="mt-7 text-[44px] sm:text-[64px] leading-[1.05] font-semibold tracking-tight text-light-fg max-w-4xl">
        <StaggerLine words={HEAD_LINE_1} delay={0.1} />
        <br />
        <StaggerLine words={HEAD_LINE_2} delay={0.25} gradient />
      </h1>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.9, duration: 0.45 }}
        className="mt-6 text-[17px] sm:text-[18px] text-light-fgMuted max-w-2xl leading-relaxed"
      >
        A retrieval-augmented chat for classified document corpora. Access is enforced at the
        vector-store filter — not in the prompt — so the model can never leak what a user isn't
        cleared to see.
      </motion.p>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.05, duration: 0.45 }}
        className="mt-9 flex flex-wrap items-center gap-3"
      >
        <HangingCTA to="/signin">
          Start for free <ArrowRight className="w-4 h-4" />
        </HangingCTA>
        <Link
          to="/pipeline"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md border border-light-accent/40 bg-light-accent/5 text-light-accent text-[14px] font-semibold hover:bg-light-accent/10 transition-colors shadow-light-sm"
        >
          Try the Pipeline Lab
          <ArrowRight className="w-4 h-4" />
        </Link>
        <a
          href="#cli"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md border border-light-border bg-light-surface text-light-fgMuted text-[14px] font-medium hover:text-light-fg hover:border-light-borderStrong transition-colors shadow-light-sm"
        >
          <TerminalIcon className="w-4 h-4" strokeWidth={1.75} /> CLI
        </a>
      </motion.div>

      {/* Pipeline diagram with border-beam */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6, duration: 0.7 }}
        className="mt-16 relative rounded-2xl bg-light-surface border border-light-border shadow-light-card p-6 sm:p-10 overflow-hidden"
      >
        <BorderBeam size={300} duration={8} colorFrom="#5b47ff" colorTo="#a18dff" />
        <div className="flex items-center gap-2 mb-6 relative">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-light-fgSubtle">
            How a question flows through the system
          </span>
          <div className="h-px flex-1 bg-light-border" />
        </div>
        <AnimatedBeamPipeline />
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
    <motion.div
      animate={{ y: [0, -2, 0] }}
      transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
      className="inline-block relative"
    >
      <Link
        to={to}
        className="relative inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-light-accent text-white text-[14px] font-semibold shadow-light-hang hover:bg-light-accentHover hover:-translate-y-0.5 transition-all overflow-hidden"
      >
        <BorderBeam size={100} duration={4} colorFrom="#ffffff" colorTo="#d8ccff" />
        {children}
      </Link>
    </motion.div>
  );
}

// ─── Stats strip ─────────────────────────────────────────────────────────
function StatsStrip() {
  const items = [
    { label: "Classified documents", value: 10, suffix: "" },
    { label: "Role levels", value: 4, suffix: "" },
    { label: "Embedded chunks", value: 86, suffix: "" },
    { label: "Automated tests", value: 35, suffix: "" },
    { label: "RBAC leak cases blocked", value: 100, suffix: "%" },
  ];
  return (
    <section className="border-y border-light-border bg-light-surface">
      <div className="max-w-6xl mx-auto px-6 py-10 grid grid-cols-2 sm:grid-cols-5 gap-6">
        {items.map((it) => (
          <div key={it.label} className="text-center">
            <div className="text-[28px] sm:text-[32px] font-semibold text-light-fg tabular-nums">
              <NumberTicker value={it.value} suffix={it.suffix} />
            </div>
            <div className="text-[11px] uppercase tracking-wider text-light-fgSubtle mt-1 font-semibold">
              {it.label}
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
    <section id="features" className="max-w-6xl mx-auto px-6 py-24">
      <div className="max-w-2xl mb-10">
        <div className="text-[11px] uppercase tracking-wider font-semibold text-light-accent">
          Built for corpora people actually care about
        </div>
        <h2 className="mt-2 text-[30px] sm:text-[36px] leading-tight font-semibold tracking-tight text-light-fg">
          Everything a senior-grade RAG stack needs.
        </h2>
        <p className="mt-3 text-[14.5px] text-light-fgMuted leading-relaxed">
          Hybrid retrieval, smart refusal, observability, and access control —
          all enforced where it counts.
        </p>
      </div>

      <BentoGrid>
        <BentoCard
          span="2"
          accent
          icon={<Database className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Hybrid retrieval + smart 4-way mode"
          description="Dense (Qdrant) + BM25 fused via RRF, reranked by bge cross-encoder. Four answer modes — grounded, refused, general, unknown — with a metadata-leak-closing split only executives see."
        >
          <div className="rounded-lg bg-light-elevated border border-light-border p-3">
            <AnimatedBeamPipeline />
          </div>
        </BentoCard>

        <BentoCard
          icon={<Lock className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="RBAC at the filter layer"
          description="PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED. The LLM physically cannot see what the user can't — no prompt-injection can exfiltrate it."
        />

        <BentoCard
          icon={<Gauge className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="LLM-judged faithfulness"
          description="Every grounded answer is scored against its sources. The result is persisted in the audit log and surfaced live as a 0–100% faithfulness badge."
        />

        <BentoCard
          icon={<BookOpenCheck className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Query cache + corrective retry"
          description="Repeat queries serve from an in-memory LRU with 10-minute TTL. Weak first passes trigger an auto-rewrite and a second retrieval — Corrective RAG."
        />

        <BentoCard
          icon={<ShieldAlert className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Full audit log + analytics"
          description="Every query writes one row with mode, latency, tokens, cost, and faithfulness. The executive analytics dashboard aggregates live."
        />

        <BentoCard
          icon={<MessagesSquare className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Persistent chat threads"
          description="Server-stored per user with LLM-generated titles. Resume from any device; the full turn history reloads with latency + source metadata."
        />

        <BentoCard
          icon={<Upload className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Clearance-capped uploads"
          description="Every signed-in user can contribute — but only up to their own clearance. You can never publish something as more-secret than you are."
        />

        <BentoCard
          span="2"
          icon={<Sparkles className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Retrieval trace panel — see every score"
          description="Every message exposes its pipeline: latency bars, token counts, per-chunk RRF + rerank scores, and the faithfulness judgment. Nothing hidden, nothing claimed without a number behind it."
        />
      </BentoGrid>
    </section>
  );
}

// ─── CLI section ─────────────────────────────────────────────────────────
function CliSection() {
  const repoUrl = "https://github.com/";
  const installCmd =
    "git clone <repo> && cd homework-basic && ./setup.sh && python rag_cli.py";

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
          title="homework-basic · zsh"
          lines={[
            { prompt: "$", text: "git clone <repo> && cd homework-basic", delay: 0.2 },
            { prompt: "$", text: "./setup.sh", delay: 1.6 },
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
    <section className="max-w-6xl mx-auto px-6 py-24 text-center">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
        className="relative rounded-2xl border border-light-border bg-gradient-to-br from-white to-light-accent/5 shadow-light-card p-12 sm:p-16 overflow-hidden"
      >
        <BorderBeam size={240} duration={10} colorFrom="#5b47ff" colorTo="#a18dff" />
        <Shield className="w-10 h-10 text-light-accent mx-auto mb-4" strokeWidth={1.5} />
        <h2 className="text-[30px] sm:text-[36px] font-semibold tracking-tight text-light-fg">
          Four roles. One query. Four different honest answers.
        </h2>
        <p className="mt-3 text-[14.5px] text-light-fgMuted max-w-xl mx-auto">
          Seeded demo accounts let you walk through every boundary — grounded,
          refused, general-knowledge — in under two minutes.
        </p>
        <div className="mt-7 inline-block">
          <HangingCTA to="/signin">
            Sign in to explore <ArrowRight className="w-4 h-4" />
          </HangingCTA>
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
