"""Rolling conversation summary (SPEC.md §2.1 "오래된 대화 자동 요약", §8.5).

Keeps the context sent to Ollama bounded: once a conversation grows past
SUMMARY_TRIGGER_MESSAGE_COUNT messages, everything except the most recent
KEEP_RECENT_MESSAGES is compacted into one summary row that chat.py folds
back in as a system message on future turns.
"""

from __future__ import annotations

import logging

from personal_ai.models.providers import ModelProvider, ModelRequest
from personal_ai_api.chat_repository import ChatRepository

logger = logging.getLogger(__name__)

SUMMARY_TRIGGER_MESSAGE_COUNT = 20
KEEP_RECENT_MESSAGES = 6
SUMMARY_WORD_LIMIT = 200


async def maybe_summarize_conversation(
    repository: ChatRepository, provider: ModelProvider, conversation_id: str
) -> None:
    messages = await repository.list_messages(conversation_id)
    if len(messages) <= SUMMARY_TRIGGER_MESSAGE_COUNT:
        return

    to_summarize = messages[:-KEEP_RECENT_MESSAGES]
    transcript = "\n".join(f"{m.role}: {m.content}" for m in to_summarize)
    prompt = (
        f"다음 대화를 한국어로 {SUMMARY_WORD_LIMIT}단어 이내로 요약해줘. "
        "이후 대화를 이어가는 데 필요한 사실, 결정, 선호만 남겨줘.\n\n" + transcript
    )

    try:
        response = await provider.generate(
            ModelRequest(messages=[{"role": "user", "content": prompt}])
        )
    except Exception:
        # Summaries are a convenience on top of the chat contract, not part of
        # it — a failed summary must never break a chat turn that already
        # succeeded, so log and move on.
        logger.warning(
            "Conversation summary generation failed for %s", conversation_id, exc_info=True
        )
        return

    await repository.upsert_conversation_summary(conversation_id, response.content)
