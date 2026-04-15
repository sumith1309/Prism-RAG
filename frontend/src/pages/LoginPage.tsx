import { useState } from "react";
import { motion } from "framer-motion";
import { Loader2, Lock, Shield, User as UserIcon } from "lucide-react";
import { toast } from "sonner";

import { QuickLoginCard } from "@/components/QuickLoginCard";
import { login } from "@/lib/api";
import { useAppStore } from "@/store/appStore";

const QUICK_LOGINS = [
  {
    role: "guest" as const,
    title: "Intern / Guest",
    username: "guest",
    password: "guest_pass",
    classification: "PUBLIC" as const,
    level: 1,
    reads: "Public documents only",
  },
  {
    role: "employee" as const,
    title: "Employee",
    username: "employee",
    password: "employee_pass",
    classification: "INTERNAL" as const,
    level: 2,
    reads: "Public + Internal",
  },
  {
    role: "manager" as const,
    title: "Manager",
    username: "manager",
    password: "manager_pass",
    classification: "CONFIDENTIAL" as const,
    level: 3,
    reads: "Public + Internal + Confidential",
  },
  {
    role: "executive" as const,
    title: "Executive",
    username: "exec",
    password: "exec_pass",
    classification: "RESTRICTED" as const,
    level: 4,
    reads: "Full access, incl. Restricted",
  },
];

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const { setAuth } = useAppStore();

  async function doLogin(u: string, p: string) {
    setLoading(true);
    try {
      const resp = await login(u, p);
      setAuth(
        { username: resp.username, role: resp.role, level: resp.level, title: resp.title },
        resp.access_token
      );
      toast.success(`Signed in as ${resp.username} (${resp.role})`);
    } catch (e: any) {
      toast.error(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-bg p-6 scrollbar-thin overflow-y-auto">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="w-full max-w-5xl grid lg:grid-cols-[1.1fr_1fr] gap-8 my-8"
      >
        {/* Left — sign-in card */}
        <div className="card p-8 shadow-pop">
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-8 h-8 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center">
              <Shield className="w-4 h-4 text-accent" strokeWidth={1.75} />
            </div>
            <div className="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
              Prism RAG
            </div>
          </div>
          <h1 className="text-2xl font-semibold text-fg mt-4">Sign in to your workspace</h1>
          <p className="text-sm text-fg-muted mt-1.5 max-w-md">
            Ask questions across the TechNova corpus. What you can read is enforced by your role —
            not the model.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (username && password) doLogin(username, password);
            }}
            className="mt-6 space-y-3"
          >
            <div>
              <label className="block text-xs font-medium text-fg-muted mb-1.5">Username</label>
              <div className="relative">
                <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-subtle" />
                <input
                  className="input pl-9"
                  placeholder="guest · employee · manager · exec"
                  value={username}
                  autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-fg-muted mb-1.5">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-subtle" />
                <input
                  type="password"
                  className="input pl-9"
                  placeholder="••••••••"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </div>
            <button type="submit" className="btn-primary w-full mt-2 py-2" disabled={loading}>
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-border text-[11px] text-fg-subtle leading-relaxed">
            Authentication uses a bcrypt-hashed password store and signed JWTs. Access control is
            enforced at the vector-store filter, so the LLM never sees documents above your
            clearance — no prompt injection can reveal them.
          </div>
        </div>

        {/* Right — Quick-Login cards */}
        <div>
          <div className="mb-4">
            <div className="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
              Demo quick-login
            </div>
            <div className="text-sm text-fg mt-0.5">One click per role — for the live demo</div>
          </div>
          <div className="grid gap-2.5">
            {QUICK_LOGINS.map((q) => (
              <QuickLoginCard key={q.username} {...q} onClick={doLogin} loading={loading} />
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
