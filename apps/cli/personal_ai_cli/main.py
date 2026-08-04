"""`pai` CLI entrypoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
import typer
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.table import Table
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

app = typer.Typer(name="pai", help="Personal AI OS command-line interface")
console = Console()
err_console = Console(stderr=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_ai"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434"
    api_base_url: str = "http://localhost:8000"


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


CHAT_ENDPOINT = "/api/v1/chat"


class ChatError(RuntimeError):
    """Raised when the chat backend reports an error or a bad HTTP status."""


@dataclass
class SSEEvent:
    event: str
    data: dict[str, Any]


def parse_sse_lines(lines: Iterable[str]) -> Iterator[SSEEvent]:
    """Parse Server-Sent Events out of a line iterator (no network I/O)."""
    event_type = "message"
    data_lines: list[str] = []

    def _flush() -> SSEEvent | None:
        if not data_lines:
            return None
        payload = "\n".join(data_lines)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        return SSEEvent(event_type, data)

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line == "":
            event = _flush()
            event_type = "message"
            data_lines = []
            if event is not None:
                yield event
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())

    event = _flush()
    if event is not None:
        yield event


def _extract_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("detail") or body)
    return str(body)


def stream_chat_response(
    client: httpx.Client,
    base_url: str,
    conversation_id: str | None,
    message: str,
    local_only: bool | None,
    project_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """POST to the chat endpoint, print tokens as they arrive, return (full text, done payload)."""
    payload: dict[str, Any] = {"conversation_id": conversation_id, "message": message}
    if local_only is not None:
        payload["local_only"] = local_only
    if project_id is not None:
        payload["project_id"] = project_id

    chunks: list[str] = []
    done_payload: dict[str, Any] = {}
    url = f"{base_url.rstrip('/')}{CHAT_ENDPOINT}"
    with client.stream("POST", url, json=payload) as response:
        if response.status_code >= 400:
            response.read()
            raise ChatError(_extract_error_message(response))
        for event in parse_sse_lines(response.iter_lines()):
            if event.event == "token":
                delta = event.data.get("delta", "")
                console.print(delta, end="", markup=False, highlight=False)
                chunks.append(delta)
            elif event.event == "done":
                done_payload = event.data
            elif event.event == "error":
                raise ChatError(event.data.get("error", "unknown error"))
    console.print()
    return "".join(chunks), done_payload


def _resolve_local_only(local: bool, cloud: bool) -> bool | None:
    if local:
        return True
    if cloud:
        return False
    return None


def _validate_local_cloud(local: bool, cloud: bool) -> None:
    if local and cloud:
        err_console.print("--local and --cloud cannot be used together")
        raise typer.Exit(code=1)


@app.command()
def ask(
    prompt: str,
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", help="Continue an existing conversation"
    ),
    local: bool = typer.Option(False, "--local", help="Force local-only processing"),
    cloud: bool = typer.Option(
        False, "--cloud", help="Request cloud processing (not available in this phase)"
    ),
    project: str | None = typer.Option(None, "--project", help="Scope the request to a project"),
) -> None:
    """Ask a one-off question and stream the reply."""
    _validate_local_cloud(local, cloud)
    local_only = _resolve_local_only(local, cloud)
    settings = Settings()
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, read=120.0)) as client:
            _, done = stream_chat_response(
                client, settings.api_base_url, conversation_id, prompt, local_only, project
            )
    except ChatError as e:
        err_console.print(f"error: {e}")
        raise typer.Exit(code=1) from e
    except httpx.HTTPError as e:
        err_console.print(f"connection failed: {e}")
        raise typer.Exit(code=1) from e

    model = done.get("model")
    if model:
        console.print(f"[dim]({model})[/dim]")


@app.command()
def chat(
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", help="Resume an existing conversation"
    ),
    local: bool = typer.Option(False, "--local", help="Force local-only processing"),
    cloud: bool = typer.Option(
        False, "--cloud", help="Request cloud processing (not available in this phase)"
    ),
    project: str | None = typer.Option(None, "--project", help="Scope the session to a project"),
) -> None:
    """Interactive chat REPL. Type /exit or press Ctrl+D to quit."""
    _validate_local_cloud(local, cloud)
    local_only = _resolve_local_only(local, cloud)
    settings = Settings()
    active_conversation_id = conversation_id

    console.print("[dim]pai chat -- type /exit or press Ctrl+D to quit[/dim]")
    with httpx.Client(timeout=httpx.Timeout(10.0, read=120.0)) as client:
        while True:
            try:
                message = input("you> ")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if message.strip() in {"/exit", "/quit"}:
                break
            if not message.strip():
                continue

            try:
                _, done = stream_chat_response(
                    client,
                    settings.api_base_url,
                    active_conversation_id,
                    message,
                    local_only,
                    project,
                )
            except ChatError as e:
                err_console.print(f"error: {e}")
                continue
            except httpx.HTTPError as e:
                err_console.print(f"connection failed: {e}")
                continue

            active_conversation_id = done.get("conversation_id", active_conversation_id)
            model = done.get("model")
            if model:
                console.print(f"[dim]({model})[/dim]")


class ApiError(RuntimeError):
    """Raised when a REST call to the API backend fails."""


def _api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    response = client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise ApiError(_extract_error_message(response))
    if not response.content:
        return None
    return response.json()


def _run_api_call(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except ApiError as e:
        err_console.print(f"error: {e}")
        raise typer.Exit(code=1) from e
    except httpx.HTTPError as e:
        err_console.print(f"connection failed: {e}")
        raise typer.Exit(code=1) from e


def fetch_projects(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    return _request_json(client, "GET", _api_url(base_url, "/api/v1/projects"))


def create_project(
    client: httpx.Client, base_url: str, name: str, description: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if description is not None:
        payload["description"] = description
    return _request_json(client, "POST", _api_url(base_url, "/api/v1/projects"), json=payload)


def search_memories(
    client: httpx.Client, base_url: str, query: str, project_id: str | None
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"query": query}
    if project_id is not None:
        payload["project_id"] = project_id
    return _request_json(
        client, "POST", _api_url(base_url, "/api/v1/memories/search"), json=payload
    )


def list_memories(
    client: httpx.Client, base_url: str, project_id: str | None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if project_id is not None:
        params["project_id"] = project_id
    return _request_json(client, "GET", _api_url(base_url, "/api/v1/memories"), params=params)


def forget_memory(client: httpx.Client, base_url: str, memory_id: str) -> None:
    _request_json(client, "DELETE", _api_url(base_url, f"/api/v1/memories/{memory_id}"))


def build_projects_table(projects: list[dict[str, Any]]) -> Table:
    table = Table(title="Projects")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Created")
    for project in projects:
        table.add_row(
            str(project.get("id", "")),
            str(project.get("name", "")),
            str(project.get("status", "")),
            str(project.get("created_at", "")),
        )
    return table


def _truncate(text_value: str, limit: int = 80) -> str:
    return text_value if len(text_value) <= limit else text_value[: limit - 3] + "..."


def build_memories_table(memories: list[dict[str, Any]]) -> Table:
    table = Table(title="Memories")
    table.add_column("ID")
    table.add_column("Content")
    table.add_column("Source")
    table.add_column("Confidence")
    table.add_column("Valid Until")
    for memory in memories:
        table.add_row(
            str(memory.get("id", "")),
            _truncate(str(memory.get("content", ""))),
            str(memory.get("source", "")),
            str(memory.get("confidence", "")),
            str(memory.get("valid_until", "")),
        )
    return table


project_app = typer.Typer(help="Manage projects")
app.add_typer(project_app, name="project")


@project_app.command("list")
def project_list() -> None:
    """List all projects."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        projects = _run_api_call(lambda: fetch_projects(client, settings.api_base_url))
    console.print(build_projects_table(projects or []))


@project_app.command("create")
def project_create(
    name: str,
    description: str | None = typer.Option(None, "--description", help="Project description"),
) -> None:
    """Create a new project."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        project = _run_api_call(
            lambda: create_project(client, settings.api_base_url, name, description)
        )
    console.print(str(project.get("id", "")))


memory_app = typer.Typer(help="Search and manage memories")
app.add_typer(memory_app, name="memory")


@memory_app.command("search")
def memory_search(
    query: str,
    project: str | None = typer.Option(None, "--project", help="Scope to a project id"),
) -> None:
    """Search memories."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        memories = _run_api_call(
            lambda: search_memories(client, settings.api_base_url, query, project)
        )
    console.print(build_memories_table(memories or []))


@memory_app.command("list")
def memory_list(
    project: str | None = typer.Option(None, "--project", help="Scope to a project id"),
) -> None:
    """List memories."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        memories = _run_api_call(lambda: list_memories(client, settings.api_base_url, project))
    console.print(build_memories_table(memories or []))


@memory_app.command("forget")
def memory_forget(memory_id: str) -> None:
    """Delete a memory by id."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        _run_api_call(lambda: forget_memory(client, settings.api_base_url, memory_id))
    console.print(f"[green]forgotten:[/green] {memory_id}")


if __name__ == "__main__":
    app()
