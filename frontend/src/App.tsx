import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { Header } from "./components/Header";
import { LandingPage } from "./pages/LandingPage";
import { SignInPage } from "./pages/SignInPage";
import { ChatPage } from "./pages/ChatPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { PipelinePage } from "./pages/PipelinePage";
import { useAppStore } from "./store/appStore";
import { fetchMe } from "./lib/api";
import { getToken } from "./lib/auth";

/** Re-validate any cached JWT on boot; drop if server rejects. */
function useBootAuth() {
  const { user, setAuth, logout } = useAppStore();
  useEffect(() => {
    const token = getToken();
    if (!token || !user) return;
    fetchMe()
      .then((fresh) => setAuth(fresh, token))
      .catch(() => logout());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/** Entire app (landing, sign-in, chat, audit) shares the light premium theme. */
function useGlobalLightTheme() {
  useEffect(() => {
    const html = document.documentElement;
    html.classList.add("light");
    html.classList.remove("dark");
  }, []);
}

function ProtectedShell() {
  const user = useAppStore((s) => s.user);
  if (!user) return <Navigate to="/signin" replace />;
  return (
    <div className="flex h-screen w-screen overflow-hidden app-canvas text-fg">
      <Outlet />
    </div>
  );
}

function ChatShell() {
  return <ChatPage />;
}

function AuditShell() {
  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header onOpenSettings={() => {}} onClearChat={() => {}} />
      <AuditLogPage />
    </div>
  );
}

function AnalyticsShell() {
  return (
    <div className="flex-1 flex flex-col min-w-0">
      <Header onOpenSettings={() => {}} onClearChat={() => {}} />
      <AnalyticsPage />
    </div>
  );
}

export default function App() {
  useBootAuth();
  useGlobalLightTheme();

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/signin" element={<SignInPage />} />
      {/* Public Pipeline Lab — anyone can run the live retrieval + generation
          pipeline against the full corpus. No auth required. */}
      <Route path="/pipeline" element={<PipelinePage />} />
      <Route path="/app" element={<ProtectedShell />}>
        <Route index element={<ChatShell />} />
        <Route path="t/:threadId" element={<ChatShell />} />
        <Route path="audit" element={<AuditShell />} />
        <Route path="analytics" element={<AnalyticsShell />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
