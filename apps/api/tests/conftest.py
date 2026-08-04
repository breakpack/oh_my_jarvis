import sys
from pathlib import Path

# Make the repo-root `personal_ai` package importable before test modules
# (some of which import it directly) get collected. Same fix as
# migrations/env.py and personal_ai_api/__init__.py for the same reason.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
