"""Skill discovery (SPEC.md §6.2 directory layout, §6.5 Discover→Validate).

A broken skill (bad manifest, missing SKILL.md, ...) must not take down
discovery for every other skill — it's skipped and recorded in
`SkillRegistry.errors` instead of raising.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from personal_ai.skills.loader import load_manifest, load_skill_md
from personal_ai.skills.sdk import SkillManifest

logger = logging.getLogger(__name__)


class LoadedSkill(BaseModel):
    name: str
    manifest: SkillManifest
    skill_md: dict
    path: str


class SkillRegistry:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def discover(self, skills_dir: Path) -> list[LoadedSkill]:
        self.errors = []
        skills_dir = Path(skills_dir)
        if not skills_dir.is_dir():
            return []

        loaded: list[LoadedSkill] = []
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                manifest = load_manifest(entry / "manifest.yaml")
                skill_md = load_skill_md(entry / "SKILL.md")
            except Exception as exc:
                logger.warning("Skipping skill '%s': %s", entry.name, exc)
                self.errors.append((entry.name, str(exc)))
                continue
            loaded.append(
                LoadedSkill(
                    name=manifest.metadata.name,
                    manifest=manifest,
                    skill_md=skill_md,
                    path=str(entry),
                )
            )
        return loaded
