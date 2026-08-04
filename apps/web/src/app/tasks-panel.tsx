"use client";

import { useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Task = {
  id: string;
  title: string;
  description?: string | null;
  project_id?: string | null;
  status: string;
  due_at?: string | null;
};

const STATUS_OPTIONS = ["open", "in_progress", "done", "cancelled"];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function TasksPanel({
  activeProjectId,
}: {
  activeProjectId: string | null;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [listError, setListError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState("");

  async function loadTasks() {
    if (!apiBaseUrl) return;
    setLoading(true);
    setListError("");
    try {
      const q = activeProjectId
        ? `?project_id=${encodeURIComponent(activeProjectId)}`
        : "";
      const res = await fetch(`${apiBaseUrl}/api/v1/tasks${q}`);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setTasks(list as Task[]);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "Task 목록을 불러오지 못했습니다.",
      );
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const text = title.trim();
    if (!text || !apiBaseUrl) return;
    setCreating(true);
    setCreateError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: text,
          ...(activeProjectId ? { project_id: activeProjectId } : {}),
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setTasks((prev) => [body as Task, ...prev]);
      setTitle("");
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Task 생성에 실패했습니다.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleStatusChange(task: Task, status: string) {
    if (!apiBaseUrl || status === task.status) return;
    setUpdatingId(task.id);
    setUpdateError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/tasks/${encodeURIComponent(task.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const updated = body as Task;
      setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)));
    } catch (err) {
      setUpdateError(
        err instanceof Error ? err.message : "Task 상태 변경에 실패했습니다.",
      );
    } finally {
      setUpdatingId(null);
    }
  }

  return (
    <details
      className="border-t border-zinc-200 p-4 dark:border-zinc-800"
      onToggle={(e) => {
        if (e.currentTarget.open && !loaded) void loadTasks();
      }}
    >
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        Task
      </summary>

      <form onSubmit={handleCreate} className="mt-3 flex gap-1">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="새 Task 제목"
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={creating || !title.trim()}
          className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
        >
          추가
        </button>
      </form>
      {createError && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">{createError}</p>
      )}

      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {loading ? "불러오는 중..." : `${tasks.length}개`}
        </span>
        <button
          onClick={() => void loadTasks()}
          disabled={loading}
          className="text-xs font-medium text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
        >
          새로고침
        </button>
      </div>

      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}
      {updateError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{updateError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {tasks.map((task) => {
          const options = STATUS_OPTIONS.includes(task.status)
            ? STATUS_OPTIONS
            : [task.status, ...STATUS_OPTIONS];
          return (
            <li
              key={task.id}
              className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
            >
              <p className="text-zinc-700 dark:text-zinc-200">{task.title}</p>
              {task.description && (
                <p className="mt-1 text-zinc-500 dark:text-zinc-400">{task.description}</p>
              )}
              <div className="mt-1 flex items-center justify-between">
                <select
                  value={task.status}
                  onChange={(e) => handleStatusChange(task, e.target.value)}
                  disabled={updatingId === task.id}
                  className="rounded border border-zinc-300 bg-white px-1 py-0.5 text-xs disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                {task.due_at && (
                  <span className="text-zinc-400 dark:text-zinc-500">{task.due_at}</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
