"use client";

import { useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Workspace = {
  id: string;
  source_path?: string;
  workspace_dir?: string;
  status?: string;
  created_at?: string;
};

type RunResult = {
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  duration_ms?: number;
};

type CommitResponse = {
  status?: string;
  approval_id?: string;
};

function isPendingApproval(result: CommitResponse): boolean {
  return result.status === "pending_approval";
}

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function WorkspacesPanel() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [listError, setListError] = useState("");

  const [source, setSource] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [destroyingId, setDestroyingId] = useState<string | null>(null);

  const [commandInput, setCommandInput] = useState("");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState("");

  const [diff, setDiff] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState("");

  const [commitMessage, setCommitMessage] = useState("");
  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitResponse | null>(null);
  const [commitError, setCommitError] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const src = source.trim();
    if (!src || !apiBaseUrl) return;
    setCreating(true);
    setCreateError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/workspaces`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: src }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const workspace = body as Workspace;
      setWorkspaces((prev) => [workspace, ...prev]);
      setSource("");
      setSelectedId(workspace.id);
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "워크스페이스 생성에 실패했습니다.",
      );
    } finally {
      setCreating(false);
    }
  }

  function handleSelect(id: string) {
    const next = selectedId === id ? null : id;
    setSelectedId(next);
    setCommandInput("");
    setRunResult(null);
    setRunError("");
    setDiff(null);
    setDiffError("");
    setCommitMessage("");
    setCommitResult(null);
    setCommitError("");
  }

  async function handleRun(workspaceId: string) {
    if (!apiBaseUrl) return;
    const command = commandInput.trim().split(/\s+/).filter(Boolean);
    if (command.length === 0) return;
    setRunning(true);
    setRunError("");
    setRunResult(null);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command }),
        },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setRunResult(body as RunResult);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "명령 실행에 실패했습니다.");
    } finally {
      setRunning(false);
    }
  }

  async function handleDiff(workspaceId: string) {
    if (!apiBaseUrl) return;
    setDiffLoading(true);
    setDiffError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/diff`,
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setDiff((body as { diff?: string })?.diff ?? "");
    } catch (err) {
      setDiffError(err instanceof Error ? err.message : "diff를 불러오지 못했습니다.");
    } finally {
      setDiffLoading(false);
    }
  }

  async function handleCommit(workspaceId: string) {
    if (!apiBaseUrl) return;
    const message = commitMessage.trim();
    if (!message) return;
    setCommitting(true);
    setCommitError("");
    setCommitResult(null);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/commit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setCommitResult(body as CommitResponse);
    } catch (err) {
      setCommitError(err instanceof Error ? err.message : "커밋 요청에 실패했습니다.");
    } finally {
      setCommitting(false);
    }
  }

  async function handleDestroy(workspaceId: string) {
    if (!apiBaseUrl) return;
    setDestroyingId(workspaceId);
    setListError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/workspaces/${encodeURIComponent(workspaceId)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      }
      setWorkspaces((prev) => prev.filter((w) => w.id !== workspaceId));
      if (selectedId === workspaceId) setSelectedId(null);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "워크스페이스 삭제에 실패했습니다.",
      );
    } finally {
      setDestroyingId(null);
    }
  }

  return (
    <details className="border-t border-zinc-200 p-4 dark:border-zinc-800">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        워크스페이스
      </summary>

      <form onSubmit={handleCreate} className="mt-3 flex gap-1">
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="저장소 (owner/repo 또는 경로)"
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={creating || !source.trim()}
          className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
        >
          {creating ? "생성 중..." : "생성"}
        </button>
      </form>
      {createError && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">{createError}</p>
      )}
      {listError && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {workspaces.map((ws) => {
          const isSelected = selectedId === ws.id;
          return (
            <li
              key={ws.id}
              className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => handleSelect(ws.id)}
                  className="flex-1 truncate text-left font-medium text-zinc-700 hover:underline dark:text-zinc-200"
                  title={ws.id}
                >
                  {ws.source_path || ws.id}
                </button>
                <button
                  onClick={() => handleDestroy(ws.id)}
                  disabled={destroyingId === ws.id}
                  className="text-red-500 hover:underline disabled:opacity-40 dark:text-red-400"
                >
                  {destroyingId === ws.id ? "삭제 중..." : "삭제"}
                </button>
              </div>
              <div className="mt-1 flex items-center gap-2 text-zinc-400 dark:text-zinc-500">
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                  {ws.status ?? "unknown"}
                </span>
                <span className="truncate">{ws.id}</span>
              </div>

              {isSelected && (
                <div className="mt-2 flex flex-col gap-3 border-t border-zinc-200 pt-2 dark:border-zinc-800">
                  <div className="flex flex-col gap-1.5">
                    <span className="text-zinc-500 dark:text-zinc-400">명령 실행</span>
                    <div className="flex gap-1">
                      <input
                        value={commandInput}
                        onChange={(e) => setCommandInput(e.target.value)}
                        placeholder="예: npm test"
                        className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 font-mono text-[11px] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      />
                      <button
                        type="button"
                        onClick={() => handleRun(ws.id)}
                        disabled={running || !commandInput.trim()}
                        className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
                      >
                        {running ? "실행 중..." : "실행"}
                      </button>
                    </div>
                    {runError && (
                      <p className="text-red-600 dark:text-red-400">{runError}</p>
                    )}
                    {runResult && (
                      <div
                        className={`rounded-lg border p-2 ${
                          runResult.exit_code === 0
                            ? "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950"
                            : "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950"
                        }`}
                      >
                        <p className="font-medium text-zinc-700 dark:text-zinc-200">
                          exit_code={runResult.exit_code} ({runResult.duration_ms}ms)
                        </p>
                        {runResult.stdout && (
                          <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[11px] text-zinc-600 dark:text-zinc-300">
                            {runResult.stdout}
                          </pre>
                        )}
                        {runResult.stderr && (
                          <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[11px] text-red-700 dark:text-red-300">
                            {runResult.stderr}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-500 dark:text-zinc-400">Diff</span>
                      <button
                        type="button"
                        onClick={() => handleDiff(ws.id)}
                        disabled={diffLoading}
                        className="text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
                      >
                        {diffLoading ? "불러오는 중..." : "새로고침"}
                      </button>
                    </div>
                    {diffError && (
                      <p className="text-red-600 dark:text-red-400">{diffError}</p>
                    )}
                    {diff !== null && (
                      <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded bg-zinc-50 p-2 text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300">
                        {diff || "(변경 사항 없음)"}
                      </pre>
                    )}
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <span className="text-zinc-500 dark:text-zinc-400">커밋 요청</span>
                    <div className="flex gap-1">
                      <input
                        value={commitMessage}
                        onChange={(e) => setCommitMessage(e.target.value)}
                        placeholder="커밋 메시지"
                        className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-[11px] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      />
                      <button
                        type="button"
                        onClick={() => handleCommit(ws.id)}
                        disabled={committing || !commitMessage.trim()}
                        className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
                      >
                        {committing ? "요청 중..." : "커밋 요청"}
                      </button>
                    </div>
                    {commitError && (
                      <p className="text-red-600 dark:text-red-400">{commitError}</p>
                    )}
                    {commitResult && isPendingApproval(commitResult) && (
                      <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-2 dark:border-yellow-700 dark:bg-yellow-950">
                        <p className="font-medium text-yellow-800 dark:text-yellow-200">
                          승인 대기 중입니다 — Approvals 패널에서 승인하세요
                        </p>
                        <p className="mt-1 text-yellow-700 dark:text-yellow-300">
                          approval id: {commitResult.approval_id}
                        </p>
                      </div>
                    )}
                    {commitResult && !isPendingApproval(commitResult) && (
                      <pre className="whitespace-pre-wrap break-words rounded bg-zinc-50 p-2 text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300">
                        {JSON.stringify(commitResult, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
