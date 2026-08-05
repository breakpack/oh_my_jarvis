"use client";

import { useEffect, useRef, useState } from "react";

type Evidence = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  page?: number | null;
  score?: number;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  provider?: string;
  error?: string;
  evidence?: Evidence[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

function parseSseEvent(rawEvent: string): { event: string; data: string } {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of rawEvent.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  return { event, data: dataLines.join("\n") };
}

type ChatViewProps = {
  activeProjectId: string | null;
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
};

export function ChatView({
  activeProjectId,
  conversationId,
  onConversationCreated,
}: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [restoreError, setRestoreError] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const loadedIdRef = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    if (!apiBaseUrl) return;
    fetch(`${apiBaseUrl}/api/v1/models`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: unknown) => {
        const list = Array.isArray(data) ? data : [];
        setModels(
          (list as Array<Record<string, unknown>>)
            .map((m) => String(m.name ?? ""))
            .filter(Boolean),
        );
      })
      .catch(() => setModels([]));
  }, []);

  useEffect(() => {
    if (conversationId === loadedIdRef.current) return;
    loadedIdRef.current = conversationId;

    if (!conversationId) {
      queueMicrotask(() => {
        setMessages([]);
        setSummary(null);
        setRestoreError("");
      });
      return;
    }
    if (!apiBaseUrl) return;

    fetch(`${apiBaseUrl}/api/v1/conversations/${conversationId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        const list = Array.isArray(data)
          ? data
          : ((data as { messages?: unknown[] })?.messages ?? []);
        const summaryValue = Array.isArray(data)
          ? null
          : ((data as { summary?: string | null })?.summary ?? null);
        setMessages(
          (list as Array<Record<string, unknown>>).map((m) => ({
            id: String(m.id),
            role: m.role === "assistant" ? "assistant" : "user",
            content: String(m.content ?? ""),
          })),
        );
        setSummary(summaryValue);
        setRestoreError("");
      })
      .catch(() => {
        setRestoreError("이전 대화를 불러오지 못했습니다.");
      });
  }, [conversationId]);

  function updateAssistant(id: string, patch: Partial<Message>) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    const assistantId = crypto.randomUUID();
    const assistantMessage: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setSending(true);

    try {
      if (!apiBaseUrl) throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");

      const res = await fetch(`${apiBaseUrl}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          message: text,
          ...(activeProjectId ? { project_id: activeProjectId } : {}),
          ...(selectedModel ? { model: selectedModel } : {}),
        }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamError = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

        let sepIndex;
        while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + 2);
          if (!rawEvent.trim()) continue;

          const { event, data } = parseSseEvent(rawEvent);
          if (!data) continue;
          const parsed = JSON.parse(data);

          if (event === "token") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + parsed.delta }
                  : m,
              ),
            );
          } else if (event === "done") {
            updateAssistant(assistantId, {
              model: parsed.model,
              provider: parsed.provider,
              evidence: Array.isArray(parsed.evidence)
                ? parsed.evidence
                : undefined,
            });
            if (parsed.conversation_id) {
              loadedIdRef.current = parsed.conversation_id;
              onConversationCreated(parsed.conversation_id);
            }
          } else if (event === "error") {
            streamError = parsed.error ?? "알 수 없는 오류가 발생했습니다.";
          }
        }
      }

      if (streamError) updateAssistant(assistantId, { error: streamError });
    } catch (err) {
      updateAssistant(assistantId, {
        error: err instanceof Error ? err.message : "네트워크 오류가 발생했습니다.",
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {restoreError && (
        <p className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          {restoreError}
        </p>
      )}

      <div ref={listRef} className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {summary && (
            <details className="rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
              <summary className="cursor-pointer font-medium text-zinc-600 dark:text-zinc-300">
                대화 요약
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-zinc-500 dark:text-zinc-400">
                {summary}
              </p>
            </details>
          )}
          {messages.length === 0 && (
            <p className="mt-12 text-center text-sm text-zinc-400 dark:text-zinc-500">
              메시지를 입력해 대화를 시작하세요.
            </p>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2 whitespace-pre-wrap ${
                  m.role === "user"
                    ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                    : "bg-zinc-100 text-black dark:bg-zinc-800 dark:text-zinc-50"
                }`}
              >
                {m.content || (m.role === "assistant" && sending ? "…" : "")}
              </div>
              {m.error && (
                <span className="mt-1 text-xs text-red-600 dark:text-red-400">
                  {m.error}
                </span>
              )}
              {m.model && (
                <span className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
                  {m.model}
                  {m.provider ? ` · ${m.provider}` : ""}
                </span>
              )}
              {m.evidence && m.evidence.length > 0 && (
                <div className="mt-1 flex flex-col gap-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                  <span className="font-medium text-zinc-500 dark:text-zinc-400">
                    출처
                  </span>
                  {m.evidence.map((ev) => (
                    <span key={ev.chunk_id}>
                      {ev.document_title}
                      {typeof ev.page === "number" ? ` p.${ev.page}` : ""}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-zinc-200 px-6 py-4 dark:border-zinc-800"
      >
        <div className="mx-auto flex max-w-2xl flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-zinc-400 dark:text-zinc-500">
              팁: <code>/remember 내용</code> · <code>/forget 검색어</code> ·{" "}
              <code>/no-memory 메시지</code>
            </p>
            {models.length > 0 && (
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-600 outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
              >
                <option value="">서버 기본값</option>
                {models.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder="메시지를 입력하세요..."
              rows={1}
              className="flex-1 resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-black outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
            >
              전송
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
