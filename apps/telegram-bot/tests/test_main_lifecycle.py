import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "111")

from personal_ai_telegram import handlers_notification, main
from personal_ai_telegram.config import Settings


@pytest.mark.asyncio
async def test_post_init_task_is_cancelled_cleanly_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_poll_loop(application: Any) -> None:
        started.set()
        try:
            await asyncio.Event().wait()  # blocks until cancelled
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(handlers_notification, "notification_poll_loop", fake_poll_loop)

    application: Any = type("FakeApp", (), {"bot_data": {}})()
    application.bot_data["settings"] = Settings(
        telegram_bot_token="test-token", telegram_allowed_user_id=111
    )

    await main._post_init(application)
    await asyncio.wait_for(started.wait(), timeout=1)

    task = application.bot_data["notification_poll_task"]
    assert not task.done()

    application.bot_data["http_client"] = AsyncMock()
    await main._post_shutdown(application)

    assert cancelled.is_set()
    assert task.done()
