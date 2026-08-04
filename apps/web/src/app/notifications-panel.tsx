"use client";

import { useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Notification = {
  id: string;
  source_type: string;
  title: string;
  body?: string;
  priority: string;
  status: string;
  created_at?: string;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

function priorityBadgeClass(priority: string): string {
  if (priority === "high") {
    return "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300";
  }
  if (priority === "medium") {
    return "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300";
  }
  return "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400";
}

function cardClass(priority: string): string {
  if (priority === "high") {
    return "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40";
  }
  return "border-zinc-200 dark:border-zinc-800";
}

export function NotificationsPanel() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [listError, setListError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [checkingNow, setCheckingNow] = useState(false);
  const [checkNowMessage, setCheckNowMessage] = useState("");

  async function loadNotifications() {
    if (!apiBaseUrl) return;
    setLoading(true);
    setListError("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/notifications`);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setNotifications(list as Notification[]);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "알림 목록을 불러오지 못했습니다.",
      );
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }

  async function handleAction(notification: Notification, action: "seen" | "dismiss") {
    if (!apiBaseUrl) return;
    setActingOn(notification.id);
    setListError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/notifications/${encodeURIComponent(notification.id)}/${action}`,
        { method: "POST" },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setNotifications((prev) => prev.filter((n) => n.id !== notification.id));
    } catch (err) {
      setListError(
        err instanceof Error
          ? err.message
          : action === "seen"
            ? "읽음 처리에 실패했습니다."
            : "알림 제거에 실패했습니다.",
      );
    } finally {
      setActingOn(null);
    }
  }

  async function handleCheckNow() {
    if (!apiBaseUrl) return;
    setCheckingNow(true);
    setListError("");
    setCheckNowMessage("");
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/notifications/check-now`, {
        method: "POST",
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setCheckNowMessage(`${list.length}건의 새 알림`);
      await loadNotifications();
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "알림 확인에 실패했습니다.",
      );
    } finally {
      setCheckingNow(false);
    }
  }

  return (
    <details
      className="border-t border-zinc-200 p-4 dark:border-zinc-800"
      onToggle={(e) => {
        if (e.currentTarget.open && !loaded) void loadNotifications();
      }}
    >
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        알림
      </summary>

      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {loading ? "불러오는 중..." : `${notifications.length}건`}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => void loadNotifications()}
            disabled={loading}
            className="text-xs font-medium text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
          >
            새로고침
          </button>
          <button
            onClick={() => void handleCheckNow()}
            disabled={checkingNow}
            className="text-xs font-medium text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
          >
            {checkingNow ? "확인 중..." : "지금 확인"}
          </button>
        </div>
      </div>

      {checkNowMessage && (
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">{checkNowMessage}</p>
      )}
      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {notifications.map((notification) => (
          <li
            key={notification.id}
            className={`rounded-lg border p-2 text-xs ${cardClass(notification.priority)}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-zinc-700 dark:text-zinc-200">
                {notification.title}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 ${priorityBadgeClass(notification.priority)}`}
              >
                {notification.priority}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-zinc-400 dark:text-zinc-500">
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                {notification.source_type}
              </span>
              {notification.created_at && <span>{notification.created_at}</span>}
            </div>
            {notification.body && (
              <p className="mt-1 whitespace-pre-wrap text-zinc-600 dark:text-zinc-300">
                {notification.body}
              </p>
            )}
            <div className="mt-2 flex gap-1.5">
              <button
                onClick={() => handleAction(notification, "seen")}
                disabled={actingOn === notification.id}
                className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
              >
                {actingOn === notification.id ? "처리 중..." : "읽음"}
              </button>
              <button
                onClick={() => handleAction(notification, "dismiss")}
                disabled={actingOn === notification.id}
                className="rounded-lg border border-zinc-300 px-2 py-1 text-xs font-medium text-zinc-700 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-200"
              >
                제거
              </button>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
