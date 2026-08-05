"""Telegram bot entrypoint. Wires every handler module into a python-telegram-bot
Application so the full feature set of the Web UI / `pai` CLI is reachable from
Telegram (SPEC.md §4 Clients)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from personal_ai_telegram import (
    handlers_approval,
    handlers_core,
    handlers_knowledge,
    handlers_memory,
    handlers_notification,
    handlers_project,
    handlers_skill,
    handlers_task,
    handlers_workflow,
    handlers_workspace,
)
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import default_session_repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    application.bot_data["http_client"] = httpx.AsyncClient()
    application.bot_data["session_repository"] = default_session_repository
    # Not application.create_task(): the Application isn't marked "running" yet
    # at post_init time, so PTB would skip its own task bookkeeping (error
    # reporting, graceful cancellation) and warn. We track and cancel it
    # ourselves in _post_shutdown instead.
    application.bot_data["notification_poll_task"] = asyncio.create_task(
        handlers_notification.notification_poll_loop(application), name="notification-poll-loop"
    )
    logger.info("bot started; polling API at %s", settings.api_base_url)


async def _post_shutdown(application: Application) -> None:
    task: asyncio.Task | None = application.bot_data.get("notification_poll_task")
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    client: httpx.AsyncClient | None = application.bot_data.get("http_client")
    if client is not None:
        await client.aclose()


def build_application() -> Application:
    settings = Settings()  # type: ignore[call-arg]  # values come from .env, not kwargs
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings

    application.add_handler(CommandHandler("start", handlers_core.start))
    application.add_handler(CommandHandler("help", handlers_core.help_command))
    application.add_handler(CommandHandler("doctor", handlers_core.doctor))
    application.add_handler(CommandHandler("newconv", handlers_core.newconv))
    application.add_handler(CommandHandler("model", handlers_core.model_show_or_set))
    application.add_handler(CommandHandler("model_list", handlers_core.model_list))

    application.add_handler(CommandHandler("project_list", handlers_project.project_list))
    application.add_handler(CommandHandler("project_create", handlers_project.project_create))
    application.add_handler(CommandHandler("project_use", handlers_project.project_use))

    application.add_handler(CommandHandler("memory_search", handlers_memory.memory_search))
    application.add_handler(CommandHandler("memory_list", handlers_memory.memory_list))
    application.add_handler(CommandHandler("memory_forget", handlers_memory.memory_forget))

    application.add_handler(CommandHandler("knowledge_search", handlers_knowledge.knowledge_search))
    application.add_handler(
        MessageHandler(filters.Document.ALL, handlers_knowledge.knowledge_ingest_document)
    )

    application.add_handler(CommandHandler("skill_list", handlers_skill.skill_list))
    application.add_handler(CommandHandler("skill_inspect", handlers_skill.skill_inspect))
    application.add_handler(CommandHandler("skill_enable", handlers_skill.skill_enable))
    application.add_handler(CommandHandler("skill_disable", handlers_skill.skill_disable))
    application.add_handler(CommandHandler("skill_run", handlers_skill.skill_run))
    application.add_handler(CommandHandler("skill_audit", handlers_skill.skill_audit))
    application.add_handler(CommandHandler("skill_install", handlers_skill.skill_install))
    application.add_handler(CommandHandler("skill_update", handlers_skill.skill_update))
    application.add_handler(CommandHandler("skill_versions", handlers_skill.skill_versions))
    application.add_handler(CommandHandler("skill_rollback", handlers_skill.skill_rollback))
    application.add_handler(CommandHandler("skill_remove", handlers_skill.skill_remove))

    application.add_handler(CommandHandler("approval_list", handlers_approval.approval_list))
    application.add_handler(CommandHandler("approval_approve", handlers_approval.approval_approve))
    application.add_handler(CommandHandler("approval_reject", handlers_approval.approval_reject))
    application.add_handler(
        CallbackQueryHandler(handlers_approval.approval_button, pattern=r"^approval:")
    )

    application.add_handler(CommandHandler("task_list", handlers_task.task_list))
    application.add_handler(CommandHandler("task_create", handlers_task.task_create))
    application.add_handler(CommandHandler("task_update", handlers_task.task_update))

    application.add_handler(CommandHandler("workspace_create", handlers_workspace.workspace_create))
    application.add_handler(CommandHandler("workspace_run", handlers_workspace.workspace_run))
    application.add_handler(CommandHandler("workspace_diff", handlers_workspace.workspace_diff))
    application.add_handler(CommandHandler("workspace_commit", handlers_workspace.workspace_commit))
    application.add_handler(
        CommandHandler("workspace_destroy", handlers_workspace.workspace_destroy)
    )

    application.add_handler(CommandHandler("workflow_run", handlers_workflow.workflow_run))
    application.add_handler(CommandHandler("workflow_resume", handlers_workflow.workflow_resume))

    application.add_handler(
        CommandHandler("notification_list", handlers_notification.notification_list)
    )
    application.add_handler(
        CommandHandler("notification_seen", handlers_notification.notification_seen)
    )
    application.add_handler(
        CommandHandler("notification_dismiss", handlers_notification.notification_dismiss)
    )
    application.add_handler(
        CommandHandler("notification_checknow", handlers_notification.notification_checknow)
    )
    application.add_handler(
        CallbackQueryHandler(handlers_notification.notification_button, pattern=r"^notif:")
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_core.chat_message)
    )

    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
