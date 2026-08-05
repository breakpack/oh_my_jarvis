import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "111")

from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings


def _update(user_id: int | None) -> Any:
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(effective_user=user)


def _context(allowed_user_id: int) -> Any:
    settings = Settings(telegram_bot_token="test-token", telegram_allowed_user_id=allowed_user_id)
    return SimpleNamespace(bot_data={"settings": settings})


@pytest.mark.asyncio
async def test_authorized_user_reaches_handler() -> None:
    handler = AsyncMock()
    wrapped = require_authorized(handler)
    update = _update(111)
    context = _context(111)

    await wrapped(update, context)

    handler.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
async def test_unauthorized_user_is_rejected() -> None:
    handler = AsyncMock()
    wrapped = require_authorized(handler)

    await wrapped(_update(999), _context(111))

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_user_is_rejected() -> None:
    handler = AsyncMock()
    wrapped = require_authorized(handler)

    await wrapped(_update(None), _context(111))

    handler.assert_not_awaited()
