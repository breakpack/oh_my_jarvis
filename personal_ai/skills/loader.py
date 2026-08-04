"""SKILL.md and manifest.yaml loading (SPEC.md §6.3, §6.4).

Both formats are simple enough that a hand-rolled parser is less code and
fewer moving parts than pulling in a markdown/frontmatter library.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from personal_ai.skills.sdk import SkillManifest

_HEADING_RE = re.compile(r"^#{1,2}\s+(.*)$")


def load_skill_md(path: Path) -> dict:
    """Parse a SKILL.md file (SPEC §6.3) into
    {"frontmatter": {...}, "<Section Heading>": "<body text>", ...}.
    """
    text = Path(path).read_text(encoding="utf-8")

    frontmatter: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            _, frontmatter_text, body = parts
            frontmatter = yaml.safe_load(frontmatter_text) or {}

    sections: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if heading is not None:
                sections[heading] = "\n".join(buffer).strip()
            heading = match.group(1).strip()
            buffer = []
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        sections[heading] = "\n".join(buffer).strip()

    return {"frontmatter": frontmatter, **sections}


def load_manifest(path: Path) -> SkillManifest:
    """Load and validate manifest.yaml (SPEC §6.4). Raises ValueError with
    the offending field(s) named (via the wrapped pydantic ValidationError)
    when the manifest is malformed."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return SkillManifest(**(data or {}))
    except ValidationError as exc:
        raise ValueError(f"Invalid skill manifest at {path}: {exc}") from exc
