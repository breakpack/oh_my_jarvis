"use client";

import { useEffect, useState } from "react";
import { MemoryPanel } from "./memory-panel";

type Project = {
  id: string;
  name: string;
  description?: string | null;
};

type Conversation = {
  id: string;
  summary?: string | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

type SidebarProps = {
  activeProjectId: string | null;
  conversationId: string | null;
  onSelectProject: (id: string | null) => void;
  onSelectConversation: (id: string | null) => void;
};

export function Sidebar({
  activeProjectId,
  conversationId,
  onSelectProject,
  onSelectConversation,
}: SidebarProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsError, setConversationsError] = useState("");

  useEffect(() => {
    if (!apiBaseUrl) return;
    fetch(`${apiBaseUrl}/api/v1/projects`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const list = Array.isArray(data)
          ? data
          : ((data as { items?: unknown[] })?.items ?? []);
        setProjects(list as Project[]);
      })
      .catch((err) => {
        setProjectsError(
          err instanceof Error ? err.message : "프로젝트 목록을 불러오지 못했습니다.",
        );
      });
  }, []);

  useEffect(() => {
    if (!apiBaseUrl || !activeProjectId) {
      queueMicrotask(() => setConversations([]));
      return;
    }
    fetch(
      `${apiBaseUrl}/api/v1/conversations?project_id=${encodeURIComponent(activeProjectId)}`,
    )
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const list = Array.isArray(data)
          ? data
          : ((data as { items?: unknown[] })?.items ?? []);
        setConversations(list as Conversation[]);
        setConversationsError("");
      })
      .catch((err) => {
        setConversationsError(
          err instanceof Error ? err.message : "대화 목록을 불러오지 못했습니다.",
        );
      });
  }, [activeProjectId, conversationId]);

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault();
    const name = newProjectName.trim();
    if (!name || !apiBaseUrl) return;
    setCreatingProject(true);
    setProjectsError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const project = (await res.json()) as Project;
      setProjects((prev) => [...prev, project]);
      setNewProjectName("");
      onSelectProject(project.id);
    } catch (err) {
      setProjectsError(
        err instanceof Error ? err.message : "프로젝트 생성에 실패했습니다.",
      );
    } finally {
      setCreatingProject(false);
    }
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col overflow-y-auto border-r border-zinc-200 dark:border-zinc-800">
      <section className="border-b border-zinc-200 p-4 dark:border-zinc-800">
        <h2 className="mb-2 text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
          프로젝트
        </h2>
        <select
          value={activeProjectId ?? ""}
          onChange={(e) => onSelectProject(e.target.value || null)}
          className="mb-2 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        >
          <option value="">(프로젝트 없음)</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <form onSubmit={handleCreateProject} className="flex gap-1">
          <input
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="새 프로젝트 이름"
            className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
          <button
            type="submit"
            disabled={creatingProject || !newProjectName.trim()}
            className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
          >
            추가
          </button>
        </form>
        {projectsError && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            {projectsError}
          </p>
        )}
      </section>

      <section className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
            대화
          </h2>
          <button
            onClick={() => onSelectConversation(null)}
            className="text-xs font-medium text-zinc-600 hover:underline dark:text-zinc-300"
          >
            + 새 대화
          </button>
        </div>
        {!activeProjectId && (
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            프로젝트를 선택하면 대화 목록이 표시됩니다.
          </p>
        )}
        {conversationsError && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {conversationsError}
          </p>
        )}
        <ul className="flex flex-col gap-1">
          {conversations.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => onSelectConversation(c.id)}
                className={`w-full truncate rounded-lg px-2 py-1.5 text-left text-sm ${
                  c.id === conversationId
                    ? "bg-zinc-200 dark:bg-zinc-800"
                    : "hover:bg-zinc-100 dark:hover:bg-zinc-900"
                }`}
                title={c.summary ?? c.id}
              >
                {c.summary || `대화 ${c.id.slice(0, 8)}`}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <MemoryPanel activeProjectId={activeProjectId} />
    </aside>
  );
}
