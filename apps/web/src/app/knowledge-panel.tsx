"use client";

import { useEffect, useRef, useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Document = {
  id: string;
  title: string;
  source_type: string;
  status?: string;
  chunk_count?: number;
};

type SearchResult = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  content: string;
  page?: number | null;
  section?: string | null;
  score: number;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function KnowledgePanel({
  activeProjectId,
}: {
  activeProjectId: string | null;
}) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [listError, setListError] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    if (!apiBaseUrl) return;
    const q = activeProjectId
      ? `?project_id=${encodeURIComponent(activeProjectId)}`
      : "";
    fetch(`${apiBaseUrl}/api/v1/documents${q}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const list = Array.isArray(data)
          ? data
          : ((data as { items?: unknown[] })?.items ?? []);
        setDocuments(list as Document[]);
        setListError("");
      })
      .catch((err) => {
        setListError(
          err instanceof Error ? err.message : "문서 목록을 불러오지 못했습니다.",
        );
      });
  }, [activeProjectId]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !apiBaseUrl) return;
    setUploading(true);
    setUploadError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (title.trim()) formData.append("title", title.trim());
      if (activeProjectId) formData.append("project_id", activeProjectId);

      const res = await fetch(`${apiBaseUrl}/api/v1/documents`, {
        method: "POST",
        body: formData,
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));

      setDocuments((prev) => [body as Document, ...prev]);
      setTitle("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "업로드에 실패했습니다.",
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!apiBaseUrl) return;
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/documents/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "문서 삭제에 실패했습니다.",
      );
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || !apiBaseUrl) return;
    setSearching(true);
    setSearchError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/knowledge/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: q,
          ...(activeProjectId ? { project_id: activeProjectId } : {}),
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setResults(list as SearchResult[]);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "검색에 실패했습니다.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <details className="border-t border-zinc-200 p-4 dark:border-zinc-800">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        지식 문서
      </summary>

      {!activeProjectId && (
        <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">
          프로젝트를 선택하면 문서를 프로젝트별로 관리할 수 있습니다.
        </p>
      )}

      <form onSubmit={handleUpload} className="mt-3 flex flex-col gap-1.5">
        <input
          ref={fileInputRef}
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-xs text-zinc-600 dark:text-zinc-300"
        />
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="제목 (선택)"
          className="w-full rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={uploading || !file}
          className="self-start rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
        >
          {uploading ? "업로드 중..." : "업로드"}
        </button>
        {uploadError && (
          <p className="text-xs text-red-600 dark:text-red-400">{uploadError}</p>
        )}
      </form>

      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {documents.map((d) => (
          <li
            key={d.id}
            className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
          >
            <p className="text-zinc-700 dark:text-zinc-200">{d.title}</p>
            <div className="mt-1 flex items-center justify-between text-zinc-400 dark:text-zinc-500">
              <span>
                {d.source_type}
                {typeof d.chunk_count === "number" ? ` · 청크 ${d.chunk_count}` : ""}
              </span>
              <button
                onClick={() => handleDelete(d.id)}
                className="text-red-500 hover:underline dark:text-red-400"
              >
                삭제
              </button>
            </div>
          </li>
        ))}
      </ul>

      <form onSubmit={handleSearch} className="mt-4 flex gap-1">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="문서 검색"
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={searching || !query.trim()}
          className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
        >
          검색
        </button>
      </form>
      {searchError && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">{searchError}</p>
      )}

      <ul className="mt-2 flex flex-col gap-2">
        {results.map((r) => (
          <li
            key={r.chunk_id}
            className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
          >
            <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400">
              <span className="font-medium">{r.document_title}</span>
              <span>{r.score.toFixed(2)}</span>
            </div>
            {typeof r.page === "number" && (
              <span className="text-zinc-400 dark:text-zinc-500">
                p.{r.page}
                {r.section ? ` · ${r.section}` : ""}
              </span>
            )}
            <p className="mt-1 whitespace-pre-wrap text-zinc-700 dark:text-zinc-200">
              {r.content}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}
