"use client";

import { useState } from "react";
import { extractErrorMessage } from "./memory-panel";

type Skill = {
  name: string;
  display_name?: string;
  version?: string;
  description?: string;
  tags?: string[];
  risk_level?: string;
  enabled?: boolean;
};

type InvalidSkill = {
  path: string;
  error: string;
};

type SkillsResponse = {
  skills?: Skill[];
  invalid?: InvalidSkill[];
};

type SkillDetail = Skill & {
  skill_md?: string;
  manifest?: Record<string, unknown>;
};

type SkillResult = {
  success?: boolean;
  summary?: string;
  data?: unknown;
  evidence?: unknown[];
  artifacts?: unknown[];
  rollback_token?: string | null;
  error?: string | null;
};

type PendingApproval = {
  status: "pending_approval";
  approval_id: string;
};

type SkillRunResponse = SkillResult | PendingApproval;

function isPendingApproval(result: SkillRunResponse): result is PendingApproval {
  return (result as PendingApproval).status === "pending_approval";
}

type AuditFinding = {
  check?: string;
  severity?: string;
  message?: string;
};

type InstallAudit = {
  passed?: boolean;
  findings?: AuditFinding[];
  file_hash?: string;
  permissions_preview?: { risk_level?: string; scopes?: string[] };
};

type InstallResponse = {
  skill?: Skill | null;
  audit?: InstallAudit;
};

type SkillVersion = {
  version: string;
  created_at?: string;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function SkillsPanel({
  activeProjectId,
}: {
  activeProjectId: string | null;
}) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [invalidSkills, setInvalidSkills] = useState<InvalidSkill[]>([]);
  const [listError, setListError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, SkillDetail>>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const [runInput, setRunInput] = useState("{}");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<SkillRunResponse | null>(null);
  const [runError, setRunError] = useState("");

  const [installSourcePath, setInstallSourcePath] = useState("");
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<InstallResponse | null>(null);
  const [installError, setInstallError] = useState("");

  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [versionsLoaded, setVersionsLoaded] = useState(false);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState("");
  const [rollingBackVersion, setRollingBackVersion] = useState<string | null>(null);
  const [rollbackMessage, setRollbackMessage] = useState("");
  const [rollbackError, setRollbackError] = useState("");
  const [removing, setRemoving] = useState(false);

  async function loadSkills(q: string) {
    if (!apiBaseUrl) return;
    setSearching(true);
    setListError("");
    try {
      const suffix = q.trim() ? `?query=${encodeURIComponent(q.trim())}` : "";
      const res = await fetch(`${apiBaseUrl}/api/v1/skills${suffix}`);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const data = (body ?? {}) as SkillsResponse;
      setSkills(data.skills ?? []);
      setInvalidSkills(data.invalid ?? []);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "스킬 목록을 불러오지 못했습니다.",
      );
    } finally {
      setSearching(false);
      setLoaded(true);
    }
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    void loadSkills(query);
  }

  async function handleToggleEnabled(skill: Skill) {
    if (!apiBaseUrl) return;
    const action = skill.enabled ? "disable" : "enable";
    setListError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(skill.name)}/${action}`,
        { method: "POST" },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setSkills((prev) =>
        prev.map((s) => (s.name === skill.name ? { ...s, enabled: !skill.enabled } : s)),
      );
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : `스킬 ${action}에 실패했습니다.`,
      );
    }
  }

  async function handleSelect(skill: Skill) {
    const nextSelected = selectedName === skill.name ? null : skill.name;
    setSelectedName(nextSelected);
    setRunInput("{}");
    setRunResult(null);
    setRunError("");
    setVersions([]);
    setVersionsLoaded(false);
    setVersionsError("");
    setRollbackMessage("");
    setRollbackError("");
    if (!nextSelected || details[nextSelected] || !apiBaseUrl) return;

    setDetailLoading(true);
    setDetailError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(nextSelected)}`,
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setDetails((prev) => ({ ...prev, [nextSelected]: body as SkillDetail }));
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "스킬 상세 정보를 불러오지 못했습니다.",
      );
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleRun(skill: Skill) {
    if (!apiBaseUrl) return;
    let parsedArguments: unknown;
    try {
      parsedArguments = runInput.trim() ? JSON.parse(runInput) : {};
    } catch {
      setRunError("arguments는 올바른 JSON이어야 합니다.");
      return;
    }
    setRunning(true);
    setRunError("");
    setRunResult(null);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(skill.name)}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            arguments: parsedArguments,
            ...(activeProjectId ? { project_id: activeProjectId } : {}),
          }),
        },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setRunResult(body as SkillRunResponse);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "스킬 실행에 실패했습니다.");
    } finally {
      setRunning(false);
    }
  }

  async function handleInstall(e: React.FormEvent) {
    e.preventDefault();
    const path = installSourcePath.trim();
    if (!path || !apiBaseUrl) return;
    setInstalling(true);
    setInstallError("");
    setInstallResult(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/skills/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_path: path }),
      });
      const body = await res.json().catch(() => null);
      // 201 (installed) and 422 (blocked by audit) both return the same
      // {skill, audit} shape — only other statuses are generic failures.
      if (!res.ok && res.status !== 422) {
        throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      }
      const result = (body ?? {}) as InstallResponse;
      setInstallResult(result);
      if (result.audit?.passed && result.skill) {
        const installedSkill = result.skill;
        setInstallSourcePath("");
        setSkills((prev) => {
          const exists = prev.some((s) => s.name === installedSkill.name);
          return exists
            ? prev.map((s) => (s.name === installedSkill.name ? { ...s, ...installedSkill } : s))
            : [...prev, installedSkill];
        });
      }
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : "설치에 실패했습니다.");
    } finally {
      setInstalling(false);
    }
  }

  async function handleLoadVersions(skill: Skill) {
    if (!apiBaseUrl) return;
    setVersionsLoading(true);
    setVersionsError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(skill.name)}/versions`,
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      const list = Array.isArray(body)
        ? body
        : ((body as { items?: unknown[] })?.items ?? []);
      setVersions(list as SkillVersion[]);
      setVersionsLoaded(true);
    } catch (err) {
      setVersionsError(
        err instanceof Error ? err.message : "버전 이력을 불러오지 못했습니다.",
      );
    } finally {
      setVersionsLoading(false);
    }
  }

  async function handleRollback(skill: Skill, version: string) {
    if (!apiBaseUrl) return;
    setRollingBackVersion(version);
    setRollbackError("");
    setRollbackMessage("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(skill.name)}/rollback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version }),
        },
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      setRollbackMessage(`롤백됨: ${skill.name} -> ${version}`);
    } catch (err) {
      setRollbackError(err instanceof Error ? err.message : "롤백에 실패했습니다.");
    } finally {
      setRollingBackVersion(null);
    }
  }

  async function handleRemove(skill: Skill) {
    if (!apiBaseUrl) return;
    setRemoving(true);
    setListError("");
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/v1/skills/${encodeURIComponent(skill.name)}/store`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(extractErrorMessage(body, `HTTP ${res.status}`));
      }
      setSkills((prev) => prev.filter((s) => s.name !== skill.name));
      if (selectedName === skill.name) setSelectedName(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "스킬 제거에 실패했습니다.");
    } finally {
      setRemoving(false);
    }
  }

  return (
    <details
      className="border-t border-zinc-200 p-4 dark:border-zinc-800"
      onToggle={(e) => {
        if (e.currentTarget.open && !loaded) void loadSkills(query);
      }}
    >
      <summary className="cursor-pointer text-xs font-semibold uppercase text-zinc-500 dark:text-zinc-400">
        스킬
      </summary>

      <form onSubmit={handleInstall} className="mt-3 flex flex-col gap-1.5">
        <span className="text-zinc-500 dark:text-zinc-400">Skill 설치</span>
        <div className="flex gap-1">
          <input
            value={installSourcePath}
            onChange={(e) => setInstallSourcePath(e.target.value)}
            placeholder="로컬 경로 (예: /skills/my-skill)"
            className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
          <button
            type="submit"
            disabled={installing || !installSourcePath.trim()}
            className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
          >
            {installing ? "설치 중..." : "설치"}
          </button>
        </div>
        {installError && (
          <p className="text-xs text-red-600 dark:text-red-400">{installError}</p>
        )}
        {installResult?.audit?.passed && installResult.skill && (
          <div className="rounded-lg border border-green-300 bg-green-50 p-2 text-xs dark:border-green-800 dark:bg-green-950">
            <p className="font-medium text-green-800 dark:text-green-200">
              설치됨: {installResult.skill.name} v{installResult.skill.version}
            </p>
            <p className="mt-1 text-green-700 dark:text-green-300">
              권한: risk_level={installResult.audit.permissions_preview?.risk_level} · scopes=
              {(installResult.audit.permissions_preview?.scopes ?? []).join(", ") || "(none)"}
            </p>
          </div>
        )}
        {installResult && !installResult.audit?.passed && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-2 text-xs dark:border-red-800 dark:bg-red-950">
            <p className="font-medium text-red-800 dark:text-red-200">
              설치가 거부됨 — 아래 검사 항목을 확인하세요
            </p>
            {(installResult.audit?.findings ?? []).map((finding, i) => (
              <p key={i} className="mt-1 text-red-700 dark:text-red-300">
                [{finding.severity}] {finding.check}: {finding.message}
              </p>
            ))}
          </div>
        )}
      </form>

      <form onSubmit={handleSearch} className="mt-3 flex gap-1">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="스킬 검색"
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
        >
          검색
        </button>
      </form>

      {listError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listError}</p>
      )}

      {invalidSkills.length > 0 && (
        <div className="mt-3 flex flex-col gap-1.5">
          {invalidSkills.map((item) => (
            <div
              key={item.path}
              className="rounded-lg border border-yellow-300 bg-yellow-50 p-2 text-xs text-yellow-800 dark:border-yellow-700 dark:bg-yellow-950 dark:text-yellow-200"
            >
              <p className="font-medium">잘못된 Manifest</p>
              <p className="mt-0.5 break-all">{item.path}</p>
              <p className="mt-0.5">{item.error}</p>
            </div>
          ))}
        </div>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {skills.map((skill) => {
          const isSelected = selectedName === skill.name;
          const detail = details[skill.name];
          const isReadOnly = (skill.risk_level ?? "read") === "read";
          return (
            <li
              key={skill.name}
              className="rounded-lg border border-zinc-200 p-2 text-xs dark:border-zinc-800"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => handleSelect(skill)}
                  className="flex-1 truncate text-left font-medium text-zinc-700 hover:underline dark:text-zinc-200"
                >
                  {skill.display_name || skill.name}
                </button>
                <button
                  type="button"
                  role="switch"
                  aria-checked={!!skill.enabled}
                  aria-label={skill.enabled ? "비활성화" : "활성화"}
                  onClick={() => handleToggleEnabled(skill)}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                    skill.enabled ? "bg-black dark:bg-zinc-50" : "bg-zinc-300 dark:bg-zinc-700"
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform dark:bg-black ${
                      skill.enabled ? "translate-x-4" : "translate-x-1"
                    }`}
                  />
                </button>
              </div>
              <div className="mt-1 flex items-center gap-2 text-zinc-400 dark:text-zinc-500">
                <span>{skill.version}</span>
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                  {skill.risk_level}
                </span>
              </div>
              {skill.description && (
                <p className="mt-1 text-zinc-500 dark:text-zinc-400">{skill.description}</p>
              )}

              {isSelected && (
                <div className="mt-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
                  {detailLoading && !detail && (
                    <p className="text-zinc-400 dark:text-zinc-500">불러오는 중...</p>
                  )}
                  {detailError && (
                    <p className="text-red-600 dark:text-red-400">{detailError}</p>
                  )}
                  {detail?.skill_md && (
                    <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-zinc-50 p-2 text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300">
                      {detail.skill_md}
                    </pre>
                  )}

                  <div className="mt-2 flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-500 dark:text-zinc-400">실행 (arguments JSON)</span>
                      {!isReadOnly && (
                        <span className="text-yellow-600 dark:text-yellow-400">
                          승인 필요할 수 있음
                        </span>
                      )}
                    </div>
                    <textarea
                      value={runInput}
                      onChange={(e) => setRunInput(e.target.value)}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-zinc-300 bg-white px-2 py-1 font-mono text-[11px] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    />
                    <button
                      type="button"
                      onClick={() => handleRun(skill)}
                      disabled={running}
                      className="self-start rounded-lg bg-black px-2 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-50 dark:text-black"
                    >
                      {running ? "실행 중..." : "실행"}
                    </button>
                    {runError && (
                      <p className="text-red-600 dark:text-red-400">{runError}</p>
                    )}
                    {runResult && isPendingApproval(runResult) && (
                      <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-2 dark:border-yellow-700 dark:bg-yellow-950">
                        <p className="font-medium text-yellow-800 dark:text-yellow-200">
                          승인 대기 중입니다 — Approvals 패널에서 승인하세요
                        </p>
                        <p className="mt-1 text-yellow-700 dark:text-yellow-300">
                          approval id: {runResult.approval_id}
                        </p>
                      </div>
                    )}
                    {runResult && !isPendingApproval(runResult) && (
                      <div
                        className={`rounded-lg border p-2 ${
                          runResult.success
                            ? "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950"
                            : "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950"
                        }`}
                      >
                        <p
                          className={
                            runResult.success
                              ? "font-medium text-green-800 dark:text-green-200"
                              : "font-medium text-red-800 dark:text-red-200"
                          }
                        >
                          {runResult.success ? "성공" : "실패"}
                          {runResult.summary ? `: ${runResult.summary}` : ""}
                        </p>
                        {runResult.error && (
                          <p className="mt-1 text-red-700 dark:text-red-300">
                            {runResult.error}
                          </p>
                        )}
                        {Array.isArray(runResult.evidence) && runResult.evidence.length > 0 && (
                          <div className="mt-1 text-zinc-600 dark:text-zinc-300">
                            <span className="font-medium">근거:</span>
                            <ul className="ml-3 list-disc">
                              {runResult.evidence.map((item, i) => (
                                <li key={i} className="break-words">
                                  {typeof item === "string" ? item : JSON.stringify(item)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="mt-2 flex flex-col gap-1.5 border-t border-zinc-200 pt-2 dark:border-zinc-800">
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-500 dark:text-zinc-400">버전 이력</span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleLoadVersions(skill)}
                          disabled={versionsLoading}
                          className="text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
                        >
                          {versionsLoading ? "불러오는 중..." : "보기"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRemove(skill)}
                          disabled={removing}
                          className="text-red-500 hover:underline disabled:opacity-40 dark:text-red-400"
                        >
                          {removing ? "제거 중..." : "제거"}
                        </button>
                      </div>
                    </div>
                    {versionsError && (
                      <p className="text-red-600 dark:text-red-400">{versionsError}</p>
                    )}
                    {rollbackError && (
                      <p className="text-red-600 dark:text-red-400">{rollbackError}</p>
                    )}
                    {rollbackMessage && (
                      <p className="text-green-600 dark:text-green-400">{rollbackMessage}</p>
                    )}
                    {versionsLoaded && (
                      <ul className="flex flex-col gap-1">
                        {versions.map((v) => (
                          <li
                            key={v.version}
                            className="flex items-center justify-between rounded bg-zinc-50 px-2 py-1 dark:bg-zinc-900"
                          >
                            <span className="text-zinc-600 dark:text-zinc-300">
                              {v.version}{" "}
                              {v.created_at && (
                                <span className="text-zinc-400 dark:text-zinc-500">
                                  ({v.created_at})
                                </span>
                              )}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleRollback(skill, v.version)}
                              disabled={rollingBackVersion === v.version}
                              className="text-zinc-600 hover:underline disabled:opacity-40 dark:text-zinc-300"
                            >
                              {rollingBackVersion === v.version ? "롤백 중..." : "롤백"}
                            </button>
                          </li>
                        ))}
                      </ul>
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
