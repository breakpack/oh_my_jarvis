"use client";

import { useEffect, useState } from "react";

type Status = "loading" | "ok" | "error";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function HealthStatus() {
  const [status, setStatus] = useState<Status>(apiBaseUrl ? "loading" : "error");
  const [detail, setDetail] = useState(
    apiBaseUrl ? "" : "NEXT_PUBLIC_API_BASE_URL is not set",
  );

  useEffect(() => {
    if (!apiBaseUrl) return;

    fetch(`${apiBaseUrl}/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setStatus("ok");
        setDetail(apiBaseUrl);
      })
      .catch((err: Error) => {
        setStatus("error");
        setDetail(err.message);
      });
  }, []);

  const badge =
    status === "loading"
      ? "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
      : status === "ok"
        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
        : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300";

  const label =
    status === "loading" ? "Checking..." : status === "ok" ? "OK" : "Error";

  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-2 rounded-lg border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <span className="text-sm text-zinc-500 dark:text-zinc-400">
        API status
      </span>
      <span className={`rounded-full px-3 py-1 text-sm font-medium ${badge}`}>
        {label}
      </span>
      {detail && (
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {detail}
        </span>
      )}
    </div>
  );
}
