"""Settings for the Telegram bot (SPEC.md §20.2 Secret policy: token/user id
come from .env only, never hardcoded or logged)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_allowed_user_id: int
    api_base_url: str = "http://localhost:8010"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/personal_ai"
