"""TELEGRAM_ALLOWED_USER_ID authorization gate.

This bot exposes the full read/write/approval-gated surface of the API
(SPEC.md "Core owns security" — the client is not trusted). Every handler
must be wrapped with `require_authorized` before it can act.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.config import Settings

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


def require_authorized(handler: Handler) -> Handler:
    @functools.wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        settings: Settings = context.bot_data["settings"]
        user = update.effective_user
        if user is None or user.id != settings.telegram_allowed_user_id:
            logger.warning(
                "rejected update from unauthorized user_id=%s", user.id if user else None
            )
            return
        await handler(update, context)

    return wrapped
