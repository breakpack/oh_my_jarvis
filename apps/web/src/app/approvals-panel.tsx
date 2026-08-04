"use client";

import { useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Approval = {
  id: string;
  action: string;
  target: string;
  risk_level: string;
  preview?: string;
  expected_effects?: string[];
  rollback_available?: boolean;
  status: string;
  expires_at?: string | null;
  created_at?: string;
};

type ActionResult = {
  action: "approved" | "rejected";
  success?: boolean;
  summary?: string;
  error?: string | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function ApprovalsPanel() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [listError, setListError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ActionResult>>({});

  async function loadApprovals() {
    if (!apiBaseUrl) return;
    setLoading(true);
    setListError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/approvals?status=pending`);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setApprovals(list as Approval[]);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "승인 목록을 불러오지 못했습니다.",
      );
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }

  async function handleApprove(approval: Approval) {
    if (!apiBaseUrl) return;
    setActingOn(approval.id);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/approvals/${encodeURIComponent(approval.id)}/approve`,
        { method: "POST" },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setResults((prev) => ({
          ...prev,
          [approval.id]: {
            action: "approved",
            success: false,
            error: extractErrorMessage(body, `HTTP ${res.status}`),
          },
        }));
        return;
      }
      const result = (body ?? {}) as { success?: boolean; summary?: string; error?: string | null };
      setResults((prev) => ({
        ...prev,
        [approval.id]: {
          action: "approved",
          success: result.success ?? true,
          summary: result.summary,
          error: result.error,
        },
      }));
    } catch (err) {
      setResults((prev) => ({
        ...prev,
        [approval.id]: {
          action: "approved",
          success: false,
          error: err instanceof Error ? err.message : "승인 처리에 실패했습니다.",
        },
      }));
    } finally {
      setActingOn(null);
    }
  }

  async function handleReject(approval: Approval) {
    if (!apiBaseUrl) return;
    setActingOn(approval.id);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/approvals/${encodeURIComponent(approval.id)}/reject`,
        { method: "POST" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setResults((prev) => ({
          ...prev,
          [approval.id]: {
            action: "rejected",
            success: false,
            error: extractErrorMessage(body, `HTTP ${res.status}`),
          },
        }));
        return;
      }
      setResults((prev) => ({
        ...prev,
        [approval.id]: { action: "rejected", success: true },
      }));
    } catch (err) {
      setResults((prev) => ({
        ...prev,
        [approval.id]: {
          action: "rejected",
          success: false,
          error: err instanceof Error ? err.message : "거부 처리에 실패했습니다.",
        },
      }));
    } finally {
      setActingOn(null);
    }
  }

  return (
    <details
      className="border-t border-zinc-200 p-4 dark:border-zinc-800"
      onToggle={(e) => {
        if (e.currentTarget.open && !loaded) void loadApprovals();
      }}
    >
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        승인 대기
      </summary>

      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {loading ? "불러오는 중..." : `${approvals.length}건 대기 중`}
        </span>
        <button
          onClick={() => void loadApprovals()}
          disabled={loading}
          className="text-xs font-medium text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
        >
          새로고침
        </button>
      </div>

      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {approvals.map((approval) => {
          const result = results[approval.id];
          return (
            <li
              key={approval.id}
              className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-zinc-700 dark:text-zinc-200">
                  {approval.action}
                </span>
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  {approval.risk_level}
                </span>
              </div>
              <p className="mt-1 break-all text-zinc-500 dark:text-zinc-400">
                {approval.target}
              </p>
              {approval.preview && (
                <p className="mt-1 whitespace-pre-wrap text-zinc-600 dark:text-zinc-300">
                  {approval.preview}
                </p>
              )}
              {Array.isArray(approval.expected_effects) &&
                approval.expected_effects.length > 0 && (
                  <div className="mt-1 text-zinc-500 dark:text-zinc-400">
                    <span className="font-medium">예상 효과:</span>
                    <ul className="ml-3 list-disc">
                      {approval.expected_effects.map((effect, i) => (
                        <li key={i}>{effect}</li>
                      ))}
                    </ul>
                  </div>
                )}
              <div className="mt-1 flex items-center justify-between text-zinc-400 dark:text-zinc-500">
                <span>
                  {approval.rollback_available ? "rollback 가능" : "rollback 불가"}
                </span>
                {approval.expires_at && <span>만료: {approval.expires_at}</span>}
              </div>

              {result ? (
                <div
                  className={`mt-2 rounded-lg border p-2 ${
                    result.success
                      ? "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950"
                      : "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950"
                  }`}
                >
                  <p
                    className={
                      result.success
                        ? "font-medium text-green-800 dark:text-green-200"
                        : "font-medium text-red-800 dark:text-red-200"
                    }
                  >
                    {result.action === "approved" ? "승인됨" : "거부됨"}
                    {result.success === false ? " (실패)" : ""}
                    {result.summary ? `: ${result.summary}` : ""}
                  </p>
                  {result.error && (
                    <p className="mt-1 text-red-700 dark:text-red-300">{result.error}</p>
                  )}
                </div>
              ) : (
                <div className="mt-2 flex gap-1.5">
                  <button
                    onClick={() => handleApprove(approval)}
                    disabled={actingOn === approval.id}
                    className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
                  >
                    {actingOn === approval.id ? "처리 중..." : "승인"}
                  </button>
                  <button
                    onClick={() => handleReject(approval)}
                    disabled={actingOn === approval.id}
                    className="rounded-lg border border-zinc-300 px-2 py-1 text-xs font-medium text-zinc-700 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-200"
                  >
                    거부
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
