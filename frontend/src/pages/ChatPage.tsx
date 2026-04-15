import { useState } from "react";
import { Header } from "@/components/Header";
import { Sidebar } from "@/components/Sidebar";
import { ChatInterface } from "@/components/ChatInterface";
import { SettingsDrawer } from "@/components/SettingsDrawer";

export function ChatPage() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <>
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Header
          onOpenSettings={() => setSettingsOpen(true)}
          onClearChat={() => window.dispatchEvent(new Event("technova:clear-chat"))}
        />
        <ChatInterface />
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
