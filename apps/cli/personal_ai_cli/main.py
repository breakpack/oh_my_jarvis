"""`pai` CLI entrypoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import typer
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.markdown import Markdown
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


def ingest_document(
    client: httpx.Client,
    base_url: str,
    file_path: Path,
    project_id: str | None,
    title: str | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if project_id is not None:
        data["project_id"] = project_id
    if title is not None:
        data["title"] = title
    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f)}
        return _request_json(
            client,
            "POST",
            _api_url(base_url, "/api/v1/documents"),
            data=data,
            files=files,
        )


def search_knowledge(
    client: httpx.Client,
    base_url: str,
    query: str,
    project_id: str | None,
    top_k: int | None,
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"query": query}
    if project_id is not None:
        payload["project_id"] = project_id
    if top_k is not None:
        payload["top_k"] = top_k
    return _request_json(
        client, "POST", _api_url(base_url, "/api/v1/knowledge/search"), json=payload
    )


def build_knowledge_table(results: list[dict[str, Any]]) -> Table:
    table = Table(title="Knowledge")
    table.add_column("Title")
    table.add_column("Page")
    table.add_column("Score")
    table.add_column("Snippet")
    for item in results:
        table.add_row(
            str(item.get("document_title", "")),
            str(item.get("page", "")),
            str(item.get("score", "")),
            _truncate(str(item.get("content", ""))),
        )
    return table


knowledge_app = typer.Typer(help="Ingest and search the knowledge base")
app.add_typer(knowledge_app, name="knowledge")


@knowledge_app.command("ingest")
def knowledge_ingest(
    path: Path,
    project: str | None = typer.Option(None, "--project", help="Attach to a project id"),
    title: str | None = typer.Option(None, "--title", help="Document title"),
) -> None:
    """Ingest a local file into the knowledge base."""
    if not path.is_file():
        err_console.print(f"error: file not found: {path}")
        raise typer.Exit(code=1)
    settings = Settings()
    with httpx.Client(timeout=60.0) as client:
        document = _run_api_call(
            lambda: ingest_document(client, settings.api_base_url, path, project, title)
        )
    doc_id = document.get("id", "")
    chunk_count = document.get("chunk_count", "?")
    console.print(f"[green]ingested:[/green] {doc_id} ({chunk_count} chunks)")


@knowledge_app.command("search")
def knowledge_search(
    query: str,
    project: str | None = typer.Option(None, "--project", help="Scope to a project id"),
    top_k: int | None = typer.Option(None, "--top-k", help="Maximum number of results"),
) -> None:
    """Search the knowledge base."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        results = _run_api_call(
            lambda: search_knowledge(client, settings.api_base_url, query, project, top_k)
        )
    console.print(build_knowledge_table(results or []))


SKILLS_ENDPOINT = "/api/v1/skills"


def fetch_skills(client: httpx.Client, base_url: str, query: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if query is not None:
        params["query"] = query
    return _request_json(client, "GET", _api_url(base_url, SKILLS_ENDPOINT), params=params)


def inspect_skill(client: httpx.Client, base_url: str, name: str) -> dict[str, Any]:
    return _request_json(client, "GET", _api_url(base_url, f"{SKILLS_ENDPOINT}/{name}"))


def enable_skill(client: httpx.Client, base_url: str, name: str) -> Any:
    return _request_json(client, "POST", _api_url(base_url, f"{SKILLS_ENDPOINT}/{name}/enable"))


def disable_skill(client: httpx.Client, base_url: str, name: str) -> Any:
    return _request_json(client, "POST", _api_url(base_url, f"{SKILLS_ENDPOINT}/{name}/disable"))


def run_skill(
    client: httpx.Client,
    base_url: str,
    name: str,
    arguments: dict[str, Any],
    project_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"arguments": arguments}
    if project_id is not None:
        payload["project_id"] = project_id
    return _request_json(
        client, "POST", _api_url(base_url, f"{SKILLS_ENDPOINT}/{name}/run"), json=payload
    )


def fetch_skill_audit(client: httpx.Client, base_url: str, name: str) -> list[dict[str, Any]]:
    return _request_json(client, "GET", _api_url(base_url, f"{SKILLS_ENDPOINT}/{name}/audit"))


def build_skills_table(skills: list[dict[str, Any]]) -> Table:
    table = Table(title="Skills")
    table.add_column("Name")
    table.add_column("Display Name")
    table.add_column("Version")
    table.add_column("Risk Level")
    table.add_column("Enabled")
    for skill in skills:
        enabled_text = "[green]yes[/green]" if skill.get("enabled") else "[dim]no[/dim]"
        table.add_row(
            str(skill.get("name", "")),
            str(skill.get("display_name", "")),
            str(skill.get("version", "")),
            str(skill.get("risk_level", "")),
            enabled_text,
        )
    return table


def print_invalid_skills(invalid: list[dict[str, Any]]) -> None:
    if not invalid:
        return
    console.print("[yellow]invalid skills (failed to load):[/yellow]")
    for item in invalid:
        path = item.get("path", "")
        error = item.get("error", "")
        console.print(f"  [yellow]- {path}: {error}[/yellow]")


def render_skill_detail(detail: dict[str, Any]) -> None:
    name = detail.get("name", "")
    display_name = detail.get("display_name") or name
    version = detail.get("version", "")
    risk_level = detail.get("risk_level", "")
    enabled = detail.get("enabled")
    description = detail.get("description", "")
    tags = detail.get("tags") or []

    console.print(f"[bold]{display_name}[/bold] ({name}) v{version}")
    console.print(f"risk_level={risk_level}  enabled={'yes' if enabled else 'no'}")
    if tags:
        console.print(f"tags: {', '.join(str(t) for t in tags)}")
    if description:
        console.print(description)

    skill_md = detail.get("skill_md")
    if skill_md:
        console.print()
        console.print(Markdown(str(skill_md)))

    manifest = detail.get("manifest")
    if manifest:
        console.print()
        console.print("[dim]manifest:[/dim]")
        console.print(json.dumps(manifest, indent=2, ensure_ascii=False))


def render_skill_result(result: dict[str, Any]) -> None:
    success = bool(result.get("success"))
    color = "green" if success else "red"
    status_text = "SUCCESS" if success else "FAILED"
    console.print(f"[{color}]{status_text}[/{color}] {result.get('summary', '')}")

    error = result.get("error")
    if error:
        err_console.print(f"[red]error:[/red] {error}")

    for label, key in (("evidence", "evidence"), ("artifacts", "artifacts")):
        items = result.get(key) or []
        if items:
            console.print(f"[dim]{label}:[/dim]")
            for item in items:
                console.print(f"  - {item}")

    rollback_token = result.get("rollback_token")
    if rollback_token:
        console.print(f"[dim]rollback token: {rollback_token}[/dim]")


def build_skill_audit_table(entries: list[dict[str, Any]]) -> Table:
    table = Table(title="Skill Audit Log")
    table.add_column("ID")
    table.add_column("Action")
    table.add_column("Result")
    table.add_column("Risk")
    table.add_column("Created")
    for entry in entries:
        result_value = entry.get("result", entry.get("status", ""))
        table.add_row(
            str(entry.get("id", "")),
            str(entry.get("action", "")),
            str(result_value),
            str(entry.get("risk_level", "")),
            str(entry.get("created_at", "")),
        )
    return table


skill_app = typer.Typer(help="Discover, inspect, and run skills")
app.add_typer(skill_app, name="skill")


@skill_app.command("list")
def skill_list(
    query: str | None = typer.Option(
        None, "--query", help="Filter skills by name, description, or tag"
    ),
) -> None:
    """List installed skills."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        result = _run_api_call(lambda: fetch_skills(client, settings.api_base_url, query))
    result = result or {}
    console.print(build_skills_table(result.get("skills") or []))
    print_invalid_skills(result.get("invalid") or [])


@skill_app.command("inspect")
def skill_inspect(name: str) -> None:
    """Show manifest and SKILL.md details for a skill."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        detail = _run_api_call(lambda: inspect_skill(client, settings.api_base_url, name))
    render_skill_detail(detail or {})


@skill_app.command("enable")
def skill_enable(name: str) -> None:
    """Enable a skill."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        _run_api_call(lambda: enable_skill(client, settings.api_base_url, name))
    console.print(f"[green]enabled:[/green] {name}")


@skill_app.command("disable")
def skill_disable(name: str) -> None:
    """Disable a skill."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        _run_api_call(lambda: disable_skill(client, settings.api_base_url, name))
    console.print(f"[yellow]disabled:[/yellow] {name}")


@skill_app.command("run")
def skill_run(
    name: str,
    input_json: str = typer.Option(..., "--input", help="JSON-encoded arguments object"),
    project: str | None = typer.Option(None, "--project", help="Scope execution to a project"),
) -> None:
    """Run a skill with the given arguments."""
    try:
        arguments = json.loads(input_json)
    except json.JSONDecodeError as e:
        err_console.print(f"error: --input is not valid JSON: {e}")
        raise typer.Exit(code=1) from e
    if not isinstance(arguments, dict):
        err_console.print("error: --input must decode to a JSON object")
        raise typer.Exit(code=1)

    settings = Settings()
    with httpx.Client(timeout=60.0) as client:
        result = _run_api_call(
            lambda: run_skill(client, settings.api_base_url, name, arguments, project)
        )
    result = result or {}
    if result.get("status") == "pending_approval":
        approval_id = result.get("approval_id", "")
        console.print(
            f"[yellow]승인 대기 중[/yellow] (approval id: {approval_id})  "
            f"'pai approval approve {approval_id}'로 승인하세요"
        )
        return
    render_skill_result(result)
    if not result.get("success", False):
        raise typer.Exit(code=1)


@skill_app.command("audit")
def skill_audit(name: str) -> None:
    """Show recent audit log entries for a skill."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        entries = _run_api_call(lambda: fetch_skill_audit(client, settings.api_base_url, name))
    console.print(build_skill_audit_table(entries or []))


APPROVALS_ENDPOINT = "/api/v1/approvals"


def fetch_approvals(
    client: httpx.Client, base_url: str, status: str | None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if status is not None:
        params["status"] = status
    return _request_json(client, "GET", _api_url(base_url, APPROVALS_ENDPOINT), params=params)


def approve_approval(client: httpx.Client, base_url: str, approval_id: str) -> Any:
    return _request_json(
        client, "POST", _api_url(base_url, f"{APPROVALS_ENDPOINT}/{approval_id}/approve")
    )


def reject_approval(client: httpx.Client, base_url: str, approval_id: str) -> None:
    _request_json(client, "POST", _api_url(base_url, f"{APPROVALS_ENDPOINT}/{approval_id}/reject"))


def build_approvals_table(approvals: list[dict[str, Any]]) -> Table:
    table = Table(title="Approvals")
    table.add_column("ID")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column("Risk Level")
    table.add_column("Status")
    table.add_column("Expires At")
    for approval in approvals:
        table.add_row(
            str(approval.get("id", "")),
            str(approval.get("action", "")),
            str(approval.get("target", "")),
            str(approval.get("risk_level", "")),
            str(approval.get("status", "")),
            str(approval.get("expires_at", "")),
        )
    return table


def render_approval_detail(approval: dict[str, Any]) -> None:
    preview = approval.get("preview")
    if preview:
        console.print(f"[dim]preview:[/dim] {preview}")
    expected_effects = approval.get("expected_effects") or []
    if expected_effects:
        console.print("[dim]expected effects:[/dim]")
        for effect in expected_effects:
            console.print(f"  - {effect}")
    if approval.get("rollback_available"):
        console.print("[dim]rollback available[/dim]")


def render_approval_result(result: Any) -> None:
    if isinstance(result, dict) and "success" in result:
        render_skill_result(result)
    elif isinstance(result, dict):
        console.print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result is not None:
        console.print(str(result))


approval_app = typer.Typer(help="Review and act on pending approvals")
app.add_typer(approval_app, name="approval")


@approval_app.command("list")
def approval_list(
    status: str | None = typer.Option(None, "--status", help="Filter by approval status"),
) -> None:
    """List approvals."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        approvals = _run_api_call(lambda: fetch_approvals(client, settings.api_base_url, status))
    approvals = approvals or []
    console.print(build_approvals_table(approvals))
    for approval in approvals:
        render_approval_detail(approval)


@approval_app.command("approve")
def approval_approve(approval_id: str) -> None:
    """Approve a pending approval and execute the underlying action."""
    settings = Settings()
    with httpx.Client(timeout=60.0) as client:
        result = _run_api_call(lambda: approve_approval(client, settings.api_base_url, approval_id))
    console.print(f"[green]approved:[/green] {approval_id}")
    render_approval_result(result)


@approval_app.command("reject")
def approval_reject(approval_id: str) -> None:
    """Reject a pending approval."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        _run_api_call(lambda: reject_approval(client, settings.api_base_url, approval_id))
    console.print(f"[yellow]rejected:[/yellow] {approval_id}")


TASKS_ENDPOINT = "/api/v1/tasks"


def fetch_tasks(
    client: httpx.Client, base_url: str, project_id: str | None, status: str | None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if project_id is not None:
        params["project_id"] = project_id
    if status is not None:
        params["status"] = status
    return _request_json(client, "GET", _api_url(base_url, TASKS_ENDPOINT), params=params)


def create_task(
    client: httpx.Client,
    base_url: str,
    title: str,
    description: str | None,
    project_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title}
    if description is not None:
        payload["description"] = description
    if project_id is not None:
        payload["project_id"] = project_id
    return _request_json(client, "POST", _api_url(base_url, TASKS_ENDPOINT), json=payload)


def update_task(
    client: httpx.Client, base_url: str, task_id: str, status: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    return _request_json(
        client, "PATCH", _api_url(base_url, f"{TASKS_ENDPOINT}/{task_id}"), json=payload
    )


def build_tasks_table(tasks: list[dict[str, Any]]) -> Table:
    table = Table(title="Tasks")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Project")
    table.add_column("Due")
    for task in tasks:
        table.add_row(
            str(task.get("id", "")),
            str(task.get("title", "")),
            str(task.get("status", "")),
            str(task.get("project_id", "")),
            str(task.get("due_at", "")),
        )
    return table


task_app = typer.Typer(help="Manage tasks")
app.add_typer(task_app, name="task")


@task_app.command("list")
def task_list(
    project: str | None = typer.Option(None, "--project", help="Filter by project id"),
    status: str | None = typer.Option(None, "--status", help="Filter by task status"),
) -> None:
    """List tasks."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        tasks = _run_api_call(lambda: fetch_tasks(client, settings.api_base_url, project, status))
    console.print(build_tasks_table(tasks or []))


@task_app.command("create")
def task_create(
    title: str,
    description: str | None = typer.Option(None, "--description", help="Task description"),
    project: str | None = typer.Option(None, "--project", help="Attach to a project id"),
) -> None:
    """Create a new task."""
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        task = _run_api_call(
            lambda: create_task(client, settings.api_base_url, title, description, project)
        )
    task = task or {}
    console.print(f"[green]created:[/green] {task.get('id', '')}")


@task_app.command("update")
def task_update(
    task_id: str,
    status: str | None = typer.Option(None, "--status", help="New task status"),
) -> None:
    """Update a task's status."""
    if status is None:
        err_console.print("error: nothing to update, pass --status")
        raise typer.Exit(code=1)
    settings = Settings()
    with httpx.Client(timeout=10.0) as client:
        task = _run_api_call(lambda: update_task(client, settings.api_base_url, task_id, status))
    task = task or {}
    console.print(
        f"[green]updated:[/green] {task.get('id', task_id)} -> {task.get('status', status)}"
    )


if __name__ == "__main__":
    app()
