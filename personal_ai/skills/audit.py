"""Skill supply-chain security audit (SPEC.md §6.9, §25 DoD "악성 Skill
차단 테스트", "권한 Preview").

Every check here is static — audit_skill never imports or executes any
code from the skill it's auditing, only reads files and pattern-matches
text. That's what makes it safe to run against an arbitrary,
not-yet-trusted skill directory before install (SPEC §6.5
Discover -> Validate).

Signature verification is explicitly out of scope for this version (SPEC
§6.9 lists it as optional) — permissions_preview always states
"signed": false so callers never mistake "not blocked" for "verified".
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel

from personal_ai.skills.loader import load_manifest, load_skill_md

_DANGEROUS_CODE_PATTERNS = ("shell=True", "os.system(", "eval(", "exec(")

_SECRET_LIKE_NAME_KEYWORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")

_PROMPT_INJECTION_PHRASES = (
    "ignore previous instructions",
    "이전 지시를 무시",
    "reveal system prompt",
    "시스템 프롬프트를 출력",
)

# os.environ["X"], os.environ.get("X"), and bare getenv("X") (covers both
# `os.getenv(...)` and `from os import getenv; getenv(...)`).
_ENV_ACCESS_PATTERNS = (
    re.compile(r"os\.environ\s*\[\s*[\"']([A-Za-z0-9_]+)[\"']\s*\]"),
    re.compile(r"os\.environ\.get\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']"),
    re.compile(r"getenv\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']"),
)


class AuditFinding(BaseModel):
    check: str
    severity: str  # "info" | "warning" | "blocking"
    message: str


class AuditReport(BaseModel):
    passed: bool
    findings: list[AuditFinding]
    file_hash: str
    permissions_preview: dict


def audit_skill(skill_dir: Path) -> AuditReport:
    skill_dir = Path(skill_dir)
    findings: list[AuditFinding] = []
    permissions_preview: dict = {"signed": False}

    manifest = None
    try:
        manifest = load_manifest(skill_dir / "manifest.yaml")
    except Exception as exc:
        findings.append(
            AuditFinding(check="manifest", severity="blocking", message=f"invalid manifest: {exc}")
        )

    skill_md_text = ""
    try:
        load_skill_md(skill_dir / "SKILL.md")
        skill_md_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except Exception as exc:
        findings.append(
            AuditFinding(check="skill_md", severity="blocking", message=f"invalid SKILL.md: {exc}")
        )

    if manifest is not None:
        permissions_preview.update(manifest.permissions.model_dump())

        if not manifest.metadata.license.strip():
            findings.append(
                AuditFinding(check="license", severity="warning", message="license is empty")
            )

        if manifest.runtime.network_access != "allowlist":
            findings.append(
                AuditFinding(
                    check="network_access",
                    severity="warning",
                    message=(
                        f"network_access is '{manifest.runtime.network_access}', not 'allowlist'"
                    ),
                )
            )

    findings.extend(_scan_workflow_source(skill_dir / "workflow.py"))

    if skill_md_text and _contains_prompt_injection(skill_md_text):
        findings.append(
            AuditFinding(
                check="prompt_injection",
                severity="blocking",
                message="prompt injection instructions found in SKILL.md",
            )
        )

    if not _has_tests(skill_dir):
        findings.append(AuditFinding(check="tests", severity="warning", message="no tests found"))

    passed = not any(finding.severity == "blocking" for finding in findings)
    return AuditReport(
        passed=passed,
        findings=findings,
        file_hash=_hash_directory(skill_dir),
        permissions_preview=permissions_preview,
    )


def _scan_workflow_source(workflow_path: Path) -> list[AuditFinding]:
    if not workflow_path.is_file():
        return []
    source = workflow_path.read_text(encoding="utf-8")

    findings: list[AuditFinding] = []
    for pattern in _DANGEROUS_CODE_PATTERNS:
        if pattern in source:
            findings.append(
                AuditFinding(
                    check="dangerous_code",
                    severity="blocking",
                    message=f"dangerous code pattern: {pattern}",
                )
            )

    secret_like_names: set[str] = set()
    for regex in _ENV_ACCESS_PATTERNS:
        for match in regex.finditer(source):
            name = match.group(1)
            if any(keyword in name.upper() for keyword in _SECRET_LIKE_NAME_KEYWORDS):
                secret_like_names.add(name)
    for name in sorted(secret_like_names):
        findings.append(
            AuditFinding(
                check="env_secret",
                severity="warning",
                message=f"uses environment secret-like variable: {name}",
            )
        )

    return findings


def _contains_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in _PROMPT_INJECTION_PHRASES)


def _has_tests(skill_dir: Path) -> bool:
    if (skill_dir / "tests").is_dir():
        return True
    return any(skill_dir.rglob("test_*.py"))


def _hash_directory(skill_dir: Path) -> str:
    digest = hashlib.sha256()
    if skill_dir.is_dir():
        for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
            digest.update(path.read_bytes())
    return digest.hexdigest()
