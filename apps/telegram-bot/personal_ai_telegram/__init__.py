"""Telegram bot client for the Personal AI OS (SPEC.md §4 Clients)."""

import sys
from pathlib import Path

# apps/telegram-bot runs in its own uv workspace-member venv, so the repo-root
# `personal_ai` package (not installed as a dependency) needs to be on
# sys.path. Same fix as apps/api/personal_ai_api/__init__.py and
# migrations/env.py for the same reason.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
