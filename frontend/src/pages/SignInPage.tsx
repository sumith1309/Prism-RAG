import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, ChevronRight, Loader2, Lock, Shield, User as UserIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { login } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";
import type { Classification, User } from "@/types";

const QUICK_LOGINS: {
  role: User["role"];
  title: string;
  username: string;
  password: string;
  classification: Classification;
  level: number;
  reads: string;
}[] = [
  {
    role: "guest",
    title: "Intern / Guest",
    username: "guest",
    password: "guest_pass",
    classification: "PUBLIC",
    level: 1,
    reads: "Public documents",
  },
  {
    role: "employee",
    title: "Employee",
    username: "employee",
    password: "employee_pass",
    classification: "INTERNAL",
    level: 2,
    reads: "Public + Internal",
  },
  {
    role: "manager",
    title: "Manager",
    username: "manager",
    password: "manager_pass",
    classification: "CONFIDENTIAL",
    level: 3,
    reads: "Public + Internal + Confidential",
  },
  {
    role: "executive",
    title: "Executive",
    username: "exec",
    password: "exec_pass",
    classification: "RESTRICTED",
    level: 4,
    reads: "Full access, incl. Restricted",
  },
];

const CLEARANCE_STYLES: Record<Classification, { dot: string; text: string }> = {
  PUBLIC: { dot: "bg-clearance-public", text: "text-clearance-public" },
  INTERNAL: { dot: "bg-clearance-internal", text: "text-clearance-internal" },
  CONFIDENTIAL: { dot: "bg-clearance-confidential", text: "text-clearance-confidential" },
  RESTRICTED: { dot: "bg-clearance-restricted", text: "text-clearance-restricted" },
};

export function SignInPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const setAuth = useAppStore((s) => s.setAuth);
  const navigate = useNavigate();

  async function doLogin(u: string, p: string) {
    setLoading(true);
    try {
      const resp = await login(u, p);
      setAuth(
        { username: resp.username, role: resp.role, level: resp.level, title: resp.title },
        resp.access_token
      );
      toast.success(`Signed in as ${resp.username}`);
      navigate("/app", { replace: true });
    } catch (e: any) {
      toast.error(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-full bg-light-bg text-light-fg">
      <nav className="max-w-6xl mx-auto flex items-center justify-between px-6 py-4">
        <Link to="/" className="inline-flex items-center gap-1.5 text-[13px] text-light-fgMuted hover:text-light-fg transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to home
        </Link>
        <Link to="/" className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-light-accent/10 border border-light-accent/20 flex items-center justify-center">
            <Shield className="w-3.5 h-3.5 text-light-accent" strokeWidth={1.75} />
          </div>
          <span className="text-[13px] font-semibold tracking-tight">Prism RAG</span>
        </Link>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-10">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="grid lg:grid-cols-[1.05fr_1fr] gap-8"
        >
          {/* Left — classic login card */}
          <div className="rounded-2xl bg-light-surface border border-light-border shadow-light-card p-8 sm:p-10">
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted">
              Welcome back
            </div>
            <h1 className="text-[26px] sm:text-[28px] font-semibold tracking-tight text-light-fg mt-2">
              Sign in to your workspace
            </h1>
            <p className="text-[14px] text-light-fgMuted mt-2 max-w-md leading-relaxed">
              What you can read is enforced by your clearance — not by the model. No prompt
              injection can reveal documents above your level.
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (username && password) doLogin(username, password);
              }}
              className="mt-7 space-y-3"
            >
              <div>
                <label className="block text-[12px] font-medium text-light-fgMuted mb-1.5">
                  Username
                </label>
                <div className="relative">
                  <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-fgSubtle" />
                  <input
                    className="w-full bg-white border border-light-border rounded-md pl-9 pr-3 py-2.5 text-[14px] text-light-fg placeholder:text-light-fgSubtle focus:border-light-accent focus:ring-2 focus:ring-light-accent/15 outline-none transition-all"
                    placeholder="guest · employee · manager · exec"
                    value={username}
                    autoComplete="username"
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-light-fgMuted mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-fgSubtle" />
                  <input
                    type="password"
                    className="w-full bg-white border border-light-border rounded-md pl-9 pr-3 py-2.5 text-[14px] text-light-fg placeholder:text-light-fgSubtle focus:border-light-accent focus:ring-2 focus:ring-light-accent/15 outline-none transition-all"
                    placeholder="••••••••"
                    value={password}
                    autoComplete="current-password"
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={loading || !username || !password}
                className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-light-accent text-white px-4 py-2.5 text-[14px] font-semibold hover:bg-light-accentHover disabled:opacity-50 disabled:cursor-not-allowed transition-colors mt-2"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
              </button>
            </form>

            <div className="mt-8 pt-5 border-t border-light-border text-[11.5px] text-light-fgSubtle leading-relaxed">
              Authentication uses bcrypt-hashed passwords and signed JWTs.
              Access control is applied in the vector-store filter — not in the prompt.
            </div>
          </div>

          {/* Right — Quick-Login cards */}
          <div>
            <div className="text-[11px] uppercase tracking-wider font-semibold text-light-fgMuted mb-1">
              Demo quick-login
            </div>
            <div className="text-[16px] text-light-fg font-semibold">One click per role</div>
            <p className="text-[12.5px] text-light-fgMuted mt-1 mb-4 leading-relaxed">
              Seeded demo accounts. Use these to walk through the four-tier access model live.
            </p>
            <div className="space-y-2">
              {QUICK_LOGINS.map((q) => {
                const style = CLEARANCE_STYLES[q.classification];
                return (
                  <motion.button
                    key={q.username}
                    type="button"
                    disabled={loading}
                    onClick={() => doLogin(q.username, q.password)}
                    whileHover={{ y: -1 }}
                    className={cn(
                      "group w-full text-left rounded-lg bg-white border border-light-border shadow-light-sm",
                      "hover:border-light-accent/50 hover:shadow-light-card transition-all p-4",
                      "disabled:opacity-60 disabled:pointer-events-none"
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={cn("w-1.5 h-1.5 rounded-full", style.dot)} />
                          <span className={cn("text-[10px] uppercase tracking-wider font-semibold", style.text)}>
                            {q.classification}
                          </span>
                          <span className="text-[10px] uppercase tracking-wider text-light-fgSubtle">
                            L{q.level}
                          </span>
                        </div>
                        <div className="text-[14px] font-semibold text-light-fg">{q.title}</div>
                        <div className="text-[11.5px] text-light-fgMuted mt-0.5 font-mono">
                          {q.username} · {q.password}
                        </div>
                        <div className="text-[11.5px] text-light-fgMuted mt-2">{q.reads}</div>
                      </div>
                      <ChevronRight className="w-4 h-4 text-light-fgSubtle group-hover:text-light-accent transition-colors shrink-0 mt-1" />
                    </div>
                  </motion.button>
                );
              })}
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
