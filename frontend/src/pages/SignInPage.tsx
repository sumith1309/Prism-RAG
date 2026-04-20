import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, ChevronRight, Cpu, Loader2, Lock, Shield, User as UserIcon } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { login } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import { setToken } from "@/lib/auth";
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
  const [searchParams] = useSearchParams();

  // Handle SSO callback — token arrives in URL params after Google OAuth
  useEffect(() => {
    const ssoToken = searchParams.get("sso_token");
    const ssoUser = searchParams.get("sso_user");
    const ssoRole = searchParams.get("sso_role") as User["role"] | null;
    const ssoLevel = searchParams.get("sso_level");
    const error = searchParams.get("error");

    if (error) {
      toast.error(`SSO failed: ${error}`);
      return;
    }
    if (ssoToken && ssoUser && ssoRole) {
      setToken(ssoToken);
      setAuth(
        { username: ssoUser, role: ssoRole, level: parseInt(ssoLevel || "2"), title: ssoUser },
        ssoToken
      );
      toast.success(`Signed in via Google as ${ssoUser}`);
      navigate("/app", { replace: true });
    }
  }, [searchParams, setAuth, navigate]);

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

            <Link
              to="/pipeline"
              className="mt-4 inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-light-accent/40 bg-light-accent/5 text-light-accent text-[12.5px] font-semibold hover:bg-light-accent/10 transition-colors group"
            >
              <Cpu className="w-3.5 h-3.5" strokeWidth={2.25} />
              Try the Pipeline Lab — no sign-in needed
              <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" strokeWidth={2.5} />
            </Link>

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

            {/* SSO divider + Google button */}
            <div className="mt-6 flex items-center gap-3">
              <div className="flex-1 h-px bg-light-border" />
              <span className="text-[11px] text-light-fgSubtle uppercase tracking-wider">or</span>
              <div className="flex-1 h-px bg-light-border" />
            </div>
            <a
              href="/api/sso/google/authorize"
              className="mt-4 w-full inline-flex items-center justify-center gap-2.5 rounded-md border border-light-border bg-white hover:bg-gray-50 px-4 py-2.5 text-[14px] font-medium text-light-fg transition-colors shadow-sm"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              Sign in with Google
            </a>

            <div className="mt-6 pt-5 border-t border-light-border text-[11.5px] text-light-fgSubtle leading-relaxed">
              Authentication uses bcrypt-hashed passwords and signed JWTs. SSO via Google OAuth2.
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
