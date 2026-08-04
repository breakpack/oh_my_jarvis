"""`pai` CLI entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

import httpx
import typer
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.table import Table
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

app = typer.Typer(name="pai", help="Personal AI OS command-line interface")
console = Console()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_ai"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434"


class CheckStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str

    @property
    def is_ok(self) -> bool:
        return self.status is CheckStatus.OK


def ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, CheckStatus.OK, detail)


def failed(name: str, error: Exception) -> CheckResult:
    return CheckResult(name, CheckStatus.FAIL, f"{type(error).__name__}: {error}")


async def check_postgres(settings: Settings) -> CheckResult:
    try:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()
        return ok("PostgreSQL", "connected")
    except Exception as e:  # noqa: BLE001 - each check must survive any backend failure
        return failed("PostgreSQL", e)


async def check_redis(settings: Settings) -> CheckResult:
    try:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return ok("Redis", "connected")
    except Exception as e:  # noqa: BLE001
        return failed("Redis", e)


async def check_ollama(settings: Settings) -> CheckResult:
    try:
        url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
        return ok("Ollama", url)
    except Exception as e:  # noqa: BLE001
        return failed("Ollama", e)


async def check_migrations(settings: Settings) -> CheckResult:
    try:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
                exists = result.scalar() is not None
        finally:
            await engine.dispose()
        if not exists:
            return failed("Migrations", RuntimeError("alembic_version table not found"))
        return ok("Migrations", "alembic_version present")
    except Exception as e:  # noqa: BLE001
        return failed("Migrations", e)


async def run_checks(settings: Settings) -> list[CheckResult]:
    return [
        await check_postgres(settings),
        await check_redis(settings),
        await check_ollama(settings),
        await check_migrations(settings),
    ]


def build_table(results: list[CheckResult]) -> Table:
    table = Table(title="pai doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for result in results:
        style = "green" if result.is_ok else "red"
        table.add_row(result.name, f"[{style}]{result.status.value}[/{style}]", result.detail)
    return table


def summarize(results: list[CheckResult]) -> str:
    failures = [r.name for r in results if not r.is_ok]
    if not failures:
        return "[green]OK[/green] all checks passed"
    return f"[red]FAIL[/red] failed checks: {', '.join(failures)}"


@app.command()
def doctor() -> None:
    """Check PostgreSQL, Redis, Ollama, and migration status."""
    settings = Settings()
    results = asyncio.run(run_checks(settings))
    console.print(build_table(results))
    console.print(summarize(results))
    if not all(r.is_ok for r in results):
        raise typer.Exit(code=1)


@app.command()
def chat() -> None:
    """Start an interactive chat session (Phase 1)."""
    console.print("[yellow]pai chat is not implemented in Phase 0[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def ask(prompt: str) -> None:
    """Ask a one-off question (Phase 1)."""
    console.print("[yellow]pai ask is not implemented in Phase 0[/yellow]")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
