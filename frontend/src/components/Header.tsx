import { useEffect, useState } from "react";
import { BarChart3, Building2, LogOut, MessagesSquare, Settings2, Shield, ShieldCheck } from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";
import { RoleBadge } from "./RoleBadge";

export function Header({
  onOpenSettings,
  onClearChat,
}: {
  onOpenSettings: () => void;
  onClearChat: () => void;
}) {
  const user = useAppStore((s) => s.user);
  const logout = useAppStore((s) => s.logout);
  const loc = useLocation();
  const navigate = useNavigate();

  const [orgName, setOrgName] = useState<string>("");
  useEffect(() => {
    fetch("/api/orgs/current", {
      headers: { Authorization: `Bearer ${localStorage.getItem("technova.token") || ""}` },
    })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setOrgName(d.name))
      .catch(() => {});
  }, []);

  const onAuditRoute = loc.pathname.startsWith("/app/audit");
  const onAnalyticsRoute = loc.pathname.startsWith("/app/analytics");
  const onAppMeta = onAuditRoute || onAnalyticsRoute;

  const handleLogout = () => {
    logout();
    navigate("/signin", { replace: true });
  };

  return (
    <header className="flex items-center justify-between px-5 py-2.5 border-b border-border bg-white/85 backdrop-blur-lg sticky top-0 z-20">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center">
          <Shield className="w-4 h-4 text-accent" strokeWidth={1.75} />
        </div>
        <div>
          <div className="text-[13px] font-semibold tracking-tight text-fg">Prism RAG</div>
          <div className="text-[10px] uppercase tracking-wider text-fg-subtle -mt-0.5 flex items-center gap-1.5">
            Hybrid retrieval · 4-level RBAC
            {orgName && (
              <span className="inline-flex items-center gap-1 ml-1 px-1.5 py-0.5 rounded border border-border bg-bg text-[9px] font-semibold text-fg-muted normal-case tracking-normal">
                <Building2 className="w-2.5 h-2.5" strokeWidth={2} />
                {orgName}
              </span>
            )}
          </div>
        </div>

        <div className="ml-6 hidden md:flex items-center gap-0.5 bg-bg border border-border rounded-md p-0.5">
          <NavLink
            to="/app"
            end
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-sm transition-colors",
                isActive && !onAppMeta
                  ? "bg-surface-active text-fg"
                  : "text-fg-muted hover:text-fg"
              )
            }
          >
            <MessagesSquare className="w-3.5 h-3.5" />
            Chat
          </NavLink>
          {user && user.level >= 4 && (
            <>
              <NavLink
                to="/app/audit"
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-sm transition-colors",
                    isActive
                      ? "bg-surface-active text-fg"
                      : "text-fg-muted hover:text-fg"
                  )
                }
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Audit
              </NavLink>
              <NavLink
                to="/app/analytics"
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-sm transition-colors",
                    isActive
                      ? "bg-surface-active text-fg"
                      : "text-fg-muted hover:text-fg"
                  )
                }
              >
                <BarChart3 className="w-3.5 h-3.5" />
                Analytics
              </NavLink>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {user && <RoleBadge user={user} />}

        {!onAppMeta && (
          <>
            <button onClick={onClearChat} className="btn-ghost text-xs px-2.5 py-1">
              New chat
            </button>
            <button
              onClick={onOpenSettings}
              title="Retrieval settings"
              className="btn-ghost w-8 h-8 p-0 flex items-center justify-center"
            >
              <Settings2 className="w-4 h-4" strokeWidth={1.5} />
            </button>
          </>
        )}

        <button
          onClick={handleLogout}
          title="Sign out"
          className="btn-ghost w-8 h-8 p-0 flex items-center justify-center"
        >
          <LogOut className="w-4 h-4" strokeWidth={1.5} />
        </button>
      </div>
    </header>
  );
}
