"use client";

import { useEffect, useState } from "react";

type Memory = {
  id: string;
  content: string;
  project_id?: string | null;
  source?: string | null;
  confidence?: number | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      if (first && typeof first.msg === "string") return first.msg;
    }
  }
  return fallback;
}

export function MemoryPanel({
  activeProjectId,
}: {
  activeProjectId: string | null;
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [listError, setListError] = useState("");
  const [content, setContent] = useState("");
  const [confidence, setConfidence] = useState("0.8");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!apiBaseUrl) return;
    const query = activeProjectId
      ? `?project_id=${encodeURIComponent(activeProjectId)}`
      : "";
    fetch(`${apiBaseUrl}/api/v1/memories${query}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const list = Array.isArray(data)
          ? data
          : ((data as { items?: unknown[] })?.items ?? []);
        setMemories(list as Memory[]);
        setListError("");
      })
      .catch((err) => {
        setListError(
          err instanceof Error ? err.message : "메모리 목록을 불러오지 못했습니다.",
        );
      });
  }, [activeProjectId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const text = content.trim();
    if (!text || !apiBaseUrl) return;
    setSaving(true);
    setFormError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: text,
          project_id: activeProjectId ?? undefined,
          confidence: Number(confidence),
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setMemories((prev) => [body as Memory, ...prev]);
      setContent("");
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "메모리 저장에 실패했습니다.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!apiBaseUrl) return;
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/memories/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "메모리 삭제에 실패했습니다.",
      );
    }
  }

  return (
    <details className="border-t border-zinc-200 p-4 dark:border-zinc-800">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        메모리
      </summary>

      <form onSubmit={handleCreate} className="mt-3 flex flex-col gap-1.5">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="기억할 내용"
          rows={2}
          className="w-full resize-none rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500 dark:text-zinc-400">
            확신도
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="ml-1 w-16 rounded border border-zinc-300 bg-white px-1 py-0.5 text-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </label>
          <button
            type="submit"
            disabled={saving || !content.trim()}
            className="ml-auto rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
          >
            저장
          </button>
        </div>
        {formError && (
          <p className="text-xs text-red-600 dark:text-red-400">{formError}</p>
        )}
      </form>

      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {memories.map((m) => (
          <li
            key={m.id}
            className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
          >
            <p className="whitespace-pre-wrap text-zinc-700 dark:text-zinc-200">
              {m.content}
            </p>
            <div className="mt-1 flex items-center justify-between text-zinc-400 dark:text-zinc-500">
              <span>
                {typeof m.confidence === "number" ? `확신도 ${m.confidence}` : ""}
                {m.source ? ` · ${m.source}` : ""}
              </span>
              <button
                onClick={() => handleDelete(m.id)}
                className="text-red-500 hover:underline dark:text-red-400"
              >
                삭제
              </button>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
