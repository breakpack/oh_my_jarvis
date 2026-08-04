"use client";

import { useEffect, useState } from "react";
import { ChatView } from "./chat-view";
import { HealthStatus } from "./health-status";
import { Sidebar } from "./sidebar";

const ACTIVE_PROJECT_KEY = "pai:activeProjectId";
const CONVERSATION_KEY = "pai:conversationId";

export function AppShell() {
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => {
      setActiveProjectId(localStorage.getItem(ACTIVE_PROJECT_KEY));
      setConversationId(localStorage.getItem(CONVERSATION_KEY));
    });
  }, []);

  function selectProject(id: string | null) {
    setActiveProjectId(id);
    if (id) localStorage.setItem(ACTIVE_PROJECT_KEY, id);
    else localStorage.removeItem(ACTIVE_PROJECT_KEY);
    selectConversation(null);
  }

  function selectConversation(id: string | null) {
    setConversationId(id);
    if (id) localStorage.setItem(CONVERSATION_KEY, id);
    else localStorage.removeItem(CONVERSATION_KEY);
  }

  return (
    <div className="flex h-screen flex-col bg-zinc-50 dark:bg-black">
      <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <h1 className="text-xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Personal AI OS
        </h1>
        <HealthStatus compact />
      </header>
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          activeProjectId={activeProjectId}
          conversationId={conversationId}
          onSelectProject={selectProject}
          onSelectConversation={selectConversation}
        />
        <ChatView
          activeProjectId={activeProjectId}
          conversationId={conversationId}
          onConversationCreated={selectConversation}
        />
      </div>
    </div>
  );
}
