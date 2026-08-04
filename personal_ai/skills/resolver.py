"""Skill Resolver (SPEC.md §6.6): ranks candidate skills for a user query.

Pure string-token overlap — SPEC §6.6 only calls for "비교" (comparison)
against description/tags, not semantic search, so there's no embedding or
model call here.
"""

from __future__ import annotations

import re

from personal_ai.skills.registry import LoadedSkill

_TOKEN_RE = re.compile(r"[a-z0-9가-힣]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class SkillResolver:
    def resolve(self, skills: list[LoadedSkill], query: str, top_k: int = 3) -> list[LoadedSkill]:
        query_tokens = _tokenize(query)

        def score(skill: LoadedSkill) -> int:
            metadata = skill.manifest.metadata
            haystack = " ".join(
                [
                    metadata.description,
                    " ".join(metadata.tags),
                    skill.skill_md.get("Trigger Conditions", ""),
                ]
            )
            return len(query_tokens & _tokenize(haystack))

        # Stable sort on (-score, original index) ranks by score while
        # keeping manifest order for ties, per SPEC.
        ranked = sorted(enumerate(skills), key=lambda pair: (-score(pair[1]), pair[0]))
        return [skill for _, skill in ranked[:top_k]]
