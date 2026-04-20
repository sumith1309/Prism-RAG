import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Bot,
  BrainCircuit,
  Building2,
  CheckCircle2,
  Code2,
  Cpu,
  Database,
  FileSpreadsheet,
  Gauge,
  Github,
  Globe,
  Key,
  Layers,
  Lock,
  MessageSquare,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  ThumbsUp,
  Upload,
  Users,
  Zap,
} from "lucide-react";

import { BentoCard, BentoGrid } from "@/components/magic/BentoGrid";
import { NumberTicker } from "@/components/magic/NumberTicker";
import { CopyButton, Terminal } from "@/components/magic/Terminal";

export function LandingPage() {
  return (
    <div className="min-h-screen w-full bg-light-bg text-light-fg">
      <Nav />
      <Hero />
      <LogoBar />
      <StatsStrip />
      <PipelineShowcase />
      <FeatureBento />
      <AnalyticsAgentSection />
      <EnterpriseSection />
      <IntegrationsSection />
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
          <a href="#enterprise" className="hidden sm:inline hover:text-light-fg transition-colors">
            Enterprise
          </a>
          <Link
            to="/signin"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-light-accent text-white text-[13px] font-semibold hover:bg-light-accentHover transition-colors"
          >
            Sign in <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

// ─── Hero ────────────────────────────────────────────────────────────────
const HEAD_LINE_1 = ["Your", "documents."];
const HEAD_LINE_2 = ["Your", "data.", "Your", "answers."];

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
          Enterprise RAG · Analytics · RBAC · SSO
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
        An enterprise-grade knowledge platform that answers questions from your documents,
        analyzes data from your spreadsheets, and enforces role-based access at the
        infrastructure level — not the prompt. With built-in analytics, Slack integration,
        Google SSO, and a public Pipeline Lab.
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

      {/* Trust badges */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4, duration: 0.5 }}
        className="mt-10 flex flex-wrap items-center gap-4 text-[11px] text-light-fgSubtle"
      >
        {[
          { icon: ShieldCheck, text: "RBAC-enforced" },
          { icon: Zap, text: "Sub-2s retrieval" },
          { icon: Lock, text: "Injection-guarded" },
          { icon: Globe, text: "Multi-tenant" },
          { icon: Key, text: "SSO ready" },
        ].map(({ icon: Icon, text }) => (
          <span key={text} className="inline-flex items-center gap-1.5">
            <Icon className="w-3 h-3 text-light-accent" strokeWidth={2} />
            {text}
          </span>
        ))}
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

// ─── Logo bar / tech stack ──────────────────────────────────────────────
function LogoBar() {
  const stack = [
    "FastAPI", "React", "Qdrant", "OpenAI", "Pandas",
    "ECharts", "Tailwind", "Docker",
  ];
  return (
    <section className="border-y border-light-border bg-white/50">
      <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-center gap-8 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-light-fgSubtle font-semibold">
          Built with
        </span>
        {stack.map((s) => (
          <span key={s} className="text-[12px] font-semibold text-light-fgMuted/60 tracking-tight">
            {s}
          </span>
        ))}
      </div>
    </section>
  );
}

// ─── Stats strip ─────────────────────────────────────────────────────────
function StatsStrip() {
  const [live, setLive] = useState<{ docs: number; chunks: number } | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && typeof d.docs_count === "number") {
          setLive({ docs: d.docs_count, chunks: d.chunks_count ?? 0 });
        }
      })
      .catch(() => {});
  }, []);

  const items = [
    { label: "Documents", value: live?.docs ?? 18, suffix: "", dynamic: true },
    { label: "Answer modes", value: 9, suffix: "", dynamic: false },
    { label: "Indexed chunks", value: live?.chunks ?? 839, suffix: "", dynamic: true },
    { label: "File formats", value: 7, suffix: "", dynamic: false },
    { label: "RBAC compliance", value: 100, suffix: "%", dynamic: false },
  ];
  return (
    <section className="bg-white">
      <div className="max-w-5xl mx-auto px-6 py-14 grid grid-cols-2 sm:grid-cols-5 gap-6">
        {items.map((it) => (
          <div key={it.label} className="text-center relative">
            <div className="text-[30px] sm:text-[34px] font-semibold text-light-fg tabular-nums tracking-tight">
              <NumberTicker value={it.value} suffix={it.suffix} />
            </div>
            <div className="text-[10.5px] uppercase tracking-[0.12em] text-light-fgSubtle mt-1.5 font-medium inline-flex items-center gap-1.5">
              {it.label}
              {it.dynamic && live && (
                <span className="relative flex w-1.5 h-1.5" title="Live from /api/health">
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

// ─── Pipeline Showcase ──────────────────────────────────────────────────
function PipelineShowcase() {
  const stages = [
    { n: "01", label: "Embed", model: "MiniLM-L6 · 384d", colour: "#6366f1" },
    { n: "02", label: "Retrieve", model: "Qdrant + BM25 hybrid", colour: "#3b82f6" },
    { n: "03", label: "Fuse + Rerank", model: "RRF · BGE-reranker-large", colour: "#a855f7" },
    { n: "04", label: "Generate", model: "gpt-4o-mini · streaming", colour: "#22c55e" },
    { n: "05", label: "Judge", model: "Faithfulness 0–1 · Citations", colour: "#f59e0b" },
  ];
  return (
    <section className="relative max-w-5xl mx-auto px-6 py-20">
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
              Watch the entire RAG pipeline run live.
            </h2>
            <p className="mt-3 text-[13.5px] text-light-fgMuted leading-relaxed max-w-lg">
              Type a question — watch every stage fire in sequence with real
              data: embedding heatmap, chunk rank journey, side-by-side
              compare mode, and the faithfulness judge. No sign-in needed.
            </p>
            <div className="mt-5 flex items-center gap-3">
              <Link
                to="/pipeline"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-light-fg text-white text-[13px] font-semibold hover:bg-light-accent transition-colors"
              >
                Try it now
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
              <span className="text-[11px] text-light-fgSubtle">~3–5s per query</span>
            </div>
          </div>

          <div className="space-y-1.5">
            {stages.map((s) => (
              <div
                key={s.label}
                className="flex items-center gap-3 rounded-md border border-light-border bg-light-bg/40 px-3 py-2"
              >
                <span className="text-[10.5px] font-mono font-semibold tabular-nums" style={{ color: s.colour }}>
                  {s.n}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] font-semibold text-light-fg">{s.label}</div>
                  <div className="text-[10px] text-light-fgSubtle font-mono truncate">{s.model}</div>
                </div>
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.colour }} />
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </section>
  );
}

// ─── Feature Bento ───────────────────────────────────────────────────────
function FeatureBento() {
  return (
    <section id="features" className="max-w-5xl mx-auto px-6 py-24">
      <div className="max-w-2xl mb-12">
        <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-accent">
          Core Intelligence
        </div>
        <h2 className="mt-2 text-[30px] sm:text-[36px] leading-[1.15] font-semibold tracking-tight text-light-fg">
          Every feature a production RAG platform needs.
        </h2>
        <p className="mt-3 text-[14.5px] text-light-fgMuted leading-relaxed max-w-xl">
          Nine answer modes, hybrid retrieval, smart refusal, data analytics,
          prompt injection guardrails, and continuous learning from user feedback.
        </p>
      </div>

      <BentoGrid>
        <BentoCard
          span="2"
          accent
          icon={<BrainCircuit className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Nine-mode intelligent router"
          description="Grounded, refused, general, unknown, social, meta, system intelligence, analytics, and comparison — each detected before retrieval. Compound questions auto-decomposed. Follow-up queries contextualized from thread history. Ambiguous queries disambiguated with a doc picker."
        />

        <BentoCard
          icon={<Lock className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="RBAC at the filter layer"
          description="Four clearance levels enforced inside Qdrant's where-clause — not the prompt. 120/120 evaluation pass rate. Zero chunk leaks. Exec-only per-role visibility kill-switch."
        />

        <BentoCard
          icon={<Gauge className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Faithfulness + citations"
          description="Every answer scored 0–1 by an LLM judge. Citation verification catches fabricated [Source N] tags. Confidence chip shows retrieval + judge composite score."
        />

        <BentoCard
          icon={<Database className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Hybrid retrieval"
          description="Dense vectors via Qdrant + BM25 lexical search, fused with RRF, reranked by BGE cross-encoder (560M params). Corpus-aware query expansion. Corrective RAG retry."
        />

        <BentoCard
          icon={<ShieldAlert className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Prompt injection guardrail"
          description="12 regex patterns detect system-prompt overrides, role-play attacks, and data exfiltration attempts — fires before any retrieval or LLM call. Zero-cost, zero-latency protection."
        />

        <BentoCard
          icon={<FileSpreadsheet className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="SQL analytics agent"
          description="Upload Excel or CSV — ask questions in natural language. The agent loads data into pandas, generates safe code in a sandbox, and returns tables + inline ECharts. With auto-retry on failed code."
        />

        <BentoCard
          icon={<MessageSquare className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Suggested follow-ups"
          description="After every answer, 3 contextual follow-up questions appear as clickable pills. LLM-generated, timeout-guarded, zero-blocking. Thumbs up/down feedback loop on every response."
        />

        <BentoCard
          span="2"
          icon={<Sparkles className="w-4 h-4 text-light-accent" strokeWidth={1.75} />}
          title="Full observability on every message"
          description="Per-stage latency bars, token counts, chunk-level RRF and rerank scores, faithfulness badge, confidence chip, contextualization rewrites, corrective retries, cached-response indicator. Nothing hidden, nothing claimed without a number."
        />
      </BentoGrid>
    </section>
  );
}

// ─── Analytics Agent Section ─────────────────────────────────────────────
function AnalyticsAgentSection() {
  return (
    <section className="bg-white border-y border-light-border">
      <div className="max-w-5xl mx-auto px-6 py-24">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5 }}
          className="grid lg:grid-cols-2 gap-12 items-center"
        >
          <div>
            <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-sky-600 mb-3">
              SQL Analytics Agent
            </div>
            <h2 className="text-[28px] sm:text-[32px] leading-[1.15] font-semibold tracking-tight text-light-fg">
              Ask your spreadsheets anything.
            </h2>
            <p className="mt-3 text-[14px] text-light-fgMuted leading-relaxed">
              Upload an Excel or CSV file and ask questions in plain English. The analytics
              agent loads your data into pandas, writes safe code, executes it in a
              sandboxed environment, and returns tables with inline charts.
            </p>
            <ul className="mt-6 space-y-2.5 text-[13px] text-light-fgMuted">
              {[
                "Natural language → pandas code → sandboxed execution",
                "Inline ECharts (bar, line, pie) generated automatically",
                "15 safety patterns block malicious code before execution",
                "Corrective retry: if code fails, LLM self-repairs once",
                "Smart routing: doc queries go to RAG, data queries to pandas",
                "RAG-miss fallback: if no document matches, tries data agent",
              ].map((s) => (
                <li key={s} className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-sky-500 mt-0.5 shrink-0" strokeWidth={2} />
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Visual: code → table → chart */}
          <div className="space-y-3">
            <div className="rounded-xl border border-light-border bg-[#1e1e2e] p-4 shadow-light-card">
              <div className="flex items-center gap-2 mb-3">
                <Code2 className="w-3.5 h-3.5 text-sky-400" />
                <span className="text-[10px] text-sky-400/60 font-mono uppercase tracking-wider">Generated Code</span>
              </div>
              <pre className="text-[11px] text-[#cdd6f4] font-mono leading-relaxed">
{`result = (
  df.groupby("Department")["Salary"]
  .agg(["mean", "count", "sum"])
  .round(2)
  .sort_values("sum", ascending=False)
)

chart = {
  "type": "bar",
  "title": "Salary by Department",
  "xAxis": result.index.tolist(),
  "series": [{"name": "Total",
              "data": result["sum"].tolist()}]
}`}
              </pre>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-light-border bg-light-bg p-3">
                <div className="text-[9px] text-light-fgSubtle uppercase tracking-wider mb-2">Table Result</div>
                <div className="space-y-1 text-[10.5px] font-mono text-light-fgMuted">
                  <div className="flex justify-between"><span>Engineering</span><span className="text-light-fg font-semibold">$2.4M</span></div>
                  <div className="flex justify-between"><span>Sales</span><span className="text-light-fg font-semibold">$1.8M</span></div>
                  <div className="flex justify-between"><span>Finance</span><span className="text-light-fg font-semibold">$1.2M</span></div>
                </div>
              </div>
              <div className="rounded-lg border border-light-border bg-light-bg p-3">
                <div className="text-[9px] text-light-fgSubtle uppercase tracking-wider mb-2">Inline Chart</div>
                <div className="flex items-end gap-1.5 h-12">
                  {[75, 56, 38, 25].map((h, i) => (
                    <div key={i} className="flex-1 rounded-sm bg-sky-500/70" style={{ height: `${h}%` }} />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Enterprise Section ──────────────────────────────────────────────────
function EnterpriseSection() {
  const features = [
    { icon: Building2, title: "Multi-tenant isolation", desc: "Each organization gets isolated data, users, and usage limits. Plan tiers with configurable quotas." },
    { icon: Users, title: "4-level RBAC", desc: "Guest → Employee → Manager → Executive. Enforced at the vector-store filter, not the prompt." },
    { icon: Key, title: "Google SSO", desc: "One-click sign-in with Google OAuth2. Auto-provisions users. Extensible to Okta, Azure AD, SAML." },
    { icon: Bot, title: "Slack bot", desc: "Webhook receiver answers questions in channels and DMs. RBAC-scoped. Sources cited in thread replies." },
    { icon: Zap, title: "API keys", desc: "Generate prism_xxx tokens with scoped permissions. Embed Prism RAG in your own tools and workflows." },
    { icon: ShieldCheck, title: "Audit trail", desc: "Every query logged: who asked, when, what mode, latency, faithfulness score, cached or live." },
    { icon: BarChart3, title: "Executive analytics", desc: "ECharts dashboards: mode distribution, latency trends, token costs, day-by-hour heatmap, user activity." },
    { icon: ThumbsUp, title: "Feedback loop", desc: "Thumbs up/down on every answer. Aggregated in admin dashboard for continuous improvement." },
    { icon: Upload, title: "7 file formats", desc: "PDF, DOCX, XLSX, XLS, CSV, TXT, Markdown. Table-aware extraction from PDFs and spreadsheets." },
  ];

  return (
    <section id="enterprise" className="max-w-5xl mx-auto px-6 py-24">
      <div className="text-center mb-14">
        <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-accent">
          Enterprise Ready
        </div>
        <h2 className="mt-2 text-[30px] sm:text-[36px] font-semibold tracking-tight text-light-fg">
          Everything you need to deploy at scale.
        </h2>
        <p className="mt-3 text-[14px] text-light-fgMuted mx-auto max-w-xl leading-relaxed">
          Multi-tenant architecture, SSO, API access, Slack integration, and
          complete audit trails — built for teams, not just demos.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {features.map(({ icon: Icon, title, desc }) => (
          <motion.div
            key={title}
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4 }}
            className="rounded-xl border border-light-border bg-white p-5 hover:border-light-accent/40 hover:shadow-light-card transition-all group"
          >
            <div className="w-8 h-8 rounded-md bg-light-accent/8 border border-light-accent/15 flex items-center justify-center mb-3 group-hover:bg-light-accent/12 transition-colors">
              <Icon className="w-4 h-4 text-light-accent" strokeWidth={1.75} />
            </div>
            <div className="text-[14px] font-semibold text-light-fg mb-1">{title}</div>
            <div className="text-[12.5px] text-light-fgMuted leading-relaxed">{desc}</div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

// ─── Integrations Section ────────────────────────────────────────────────
function IntegrationsSection() {
  return (
    <section className="bg-white border-y border-light-border">
      <div className="max-w-5xl mx-auto px-6 py-20">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <div className="text-[10.5px] uppercase tracking-[0.12em] font-semibold text-light-accent">
            Integrations
          </div>
          <h2 className="mt-2 text-[28px] sm:text-[32px] font-semibold tracking-tight text-light-fg">
            Connect to your existing workflow.
          </h2>
        </motion.div>

        <div className="grid sm:grid-cols-4 gap-4">
          {[
            { name: "Slack", status: "Live", desc: "Answer questions in channels and DMs" },
            { name: "Google SSO", status: "Live", desc: "One-click OAuth2 sign-in" },
            { name: "REST API", status: "Live", desc: "API keys with scoped permissions" },
            { name: "Webhooks", status: "Live", desc: "Event notifications for doc uploads" },
          ].map((int) => (
            <div key={int.name} className="text-center rounded-xl border border-light-border bg-light-bg/40 p-5">
              <div className="text-[14px] font-semibold text-light-fg">{int.name}</div>
              <div className="inline-flex items-center gap-1 mt-1.5 px-2 py-0.5 rounded-full bg-clearance-public/10 text-clearance-public text-[10px] font-semibold">
                <span className="w-1 h-1 rounded-full bg-clearance-public" />
                {int.status}
              </div>
              <div className="text-[11.5px] text-light-fgMuted mt-2">{int.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── CLI section ─────────────────────────────────────────────────────────
function CliSection() {
  const repoUrl = "https://github.com/sumith1309/Prism-RAG";
  const installCmd =
    "git clone git@github.com:sumith1309/Prism-RAG.git && cd Prism-RAG/homework-basic && ./setup.sh && source .venv/bin/activate && python rag_cli.py";

  return (
    <section id="cli" className="border-t border-light-border bg-white">
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div className="grid lg:grid-cols-[1.05fr_1fr] gap-10 items-center">
          <div>
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-accent">
              Open Source · CLI
            </div>
            <h2 className="mt-2 text-[28px] sm:text-[32px] leading-tight font-semibold tracking-tight text-light-fg">
              Run it locally in 3 commands.
            </h2>
            <p className="mt-3 text-[14px] text-light-fgMuted leading-relaxed max-w-xl">
              Clone, set up, and start querying. The CLI runs the same retrieval
              stack as the full platform — dense + BM25 + RRF — against any PDF.
            </p>

            <ul className="mt-6 space-y-2 text-[13px] text-light-fgMuted">
              {[
                "Qdrant in Docker (shared with the web app)",
                "all-MiniLM-L6-v2 embeddings (384-d, CPU-fast)",
                "Configurable chunk size + overlap",
                "Full RAG prompt printed before generation",
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
            </div>
          </div>

          <Terminal
            title="Prism-RAG · zsh"
            lines={[
              { prompt: "$", text: "git clone git@github.com:sumith1309/Prism-RAG.git", delay: 0.2 },
              { prompt: "$", text: "cd Prism-RAG && ./setup.sh", delay: 1.6 },
              {
                output: true,
                text: "==> Python venv ready\n==> Qdrant on :6333\n==> 18 docs · 839 chunks indexed",
                delay: 2.8,
              },
              { prompt: "$", text: "python rag_cli.py", delay: 4.8 },
              {
                output: true,
                text: "Prism RAG v2.0 ready.\n  9 answer modes · RBAC · Analytics · SSO\n  Model: gpt-4o-mini · Reranker: BGE-large",
                delay: 5.6,
              },
              { prompt: "?", text: "What is the total salary by department?", delay: 7.5 },
            ]}
          />
        </div>
      </div>
    </section>
  );
}

// ─── Closing CTA ────────────────────────────────────────────────────────
function ClosingCTA() {
  return (
    <section className="max-w-5xl mx-auto px-6 py-24 text-center">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
      >
        <h2 className="text-[30px] sm:text-[36px] font-semibold tracking-tight text-light-fg">
          Ready to make your knowledge searchable?
        </h2>
        <p className="mt-3 text-[14.5px] text-light-fgMuted max-w-lg mx-auto leading-relaxed">
          Four demo roles let you walk through every access boundary in under
          two minutes. Or sign in with Google to get started instantly.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3 flex-wrap">
          <Link
            to="/signin"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-light-accent text-white text-[14px] font-semibold hover:bg-light-accentHover shadow-light-hang transition-all hover:-translate-y-0.5"
          >
            Get started free
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/pipeline"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md border border-light-border bg-white text-light-fg text-[14px] font-semibold hover:border-light-accent/50 hover:text-light-accent transition-all"
          >
            Try Pipeline Lab
            <ArrowRight className="w-4 h-4" />
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
      <div className="max-w-6xl mx-auto px-6 py-10">
        <div className="grid sm:grid-cols-4 gap-8 mb-8">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Shield className="w-4 h-4 text-light-accent" strokeWidth={1.75} />
              <span className="text-[13px] font-semibold text-light-fg">Prism RAG</span>
            </div>
            <p className="text-[12px] text-light-fgMuted leading-relaxed">
              Enterprise-grade knowledge platform with hybrid retrieval,
              RBAC, and data analytics.
            </p>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted mb-3">Product</div>
            <div className="space-y-2 text-[12.5px] text-light-fgMuted">
              <Link to="/pipeline" className="block hover:text-light-accent transition-colors">Pipeline Lab</Link>
              <a href="#features" className="block hover:text-light-accent transition-colors">Features</a>
              <a href="#enterprise" className="block hover:text-light-accent transition-colors">Enterprise</a>
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted mb-3">Developers</div>
            <div className="space-y-2 text-[12.5px] text-light-fgMuted">
              <a href="https://github.com/sumith1309/Prism-RAG" target="_blank" rel="noreferrer" className="block hover:text-light-accent transition-colors">GitHub</a>
              <a href="/docs" className="block hover:text-light-accent transition-colors">API docs</a>
              <a href="#cli" className="block hover:text-light-accent transition-colors">CLI</a>
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted mb-3">Security</div>
            <div className="space-y-2 text-[12.5px] text-light-fgMuted">
              <span className="block">SOC 2 compliant architecture</span>
              <span className="block">End-to-end encryption</span>
              <span className="block">RBAC + injection guards</span>
            </div>
          </div>
        </div>
        <div className="pt-6 border-t border-light-border flex flex-wrap items-center justify-between gap-3 text-[11px] text-light-fgSubtle">
          <span>Prism RAG · Built for enterprise knowledge management</span>
          <span>Qdrant · FastAPI · React · ECharts · Pandas · OpenAI</span>
        </div>
      </div>
    </footer>
  );
}
