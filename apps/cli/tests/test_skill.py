import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_skill_audit_table,
    build_skills_table,
    disable_skill,
    enable_skill,
    fetch_skill_audit,
    fetch_skills,
    inspect_skill,
    render_skill_detail,
    render_skill_result,
    run_skill,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


SKILL = {
    "name": "daily-planning",
    "display_name": "Daily Planning",
    "version": "0.1.0",
    "description": "Plan the day from tasks and calendar.",
    "tags": ["productivity"],
    "risk_level": "read",
    "enabled": True,
}


def test_fetch_skills_sends_query_param() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps({"skills": [SKILL], "invalid": []}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_skills(client, "http://testserver", "planning")
    finally:
        client.close()

    assert result == {"skills": [SKILL], "invalid": []}
    assert captured["params"] == {"query": "planning"}


def test_fetch_skills_omits_query_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps({"skills": [], "invalid": []}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        fetch_skills(client, "http://testserver", None)
    finally:
        client.close()

    assert captured["params"] == {}


def test_build_skills_table_marks_enabled_and_disabled_rows() -> None:
    disabled = {**SKILL, "name": "bug-investigation", "enabled": False}
    table = build_skills_table([SKILL, disabled])
    assert table.row_count == 2


def test_fetch_skills_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "registry unavailable"})
    try:
        with pytest.raises(ApiError, match="registry unavailable"):
            fetch_skills(client, "http://testserver", None)
    finally:
        client.close()


def test_inspect_skill_returns_detail_and_renders_without_error() -> None:
    detail = {
        **SKILL,
        "skill_md": "# Purpose\n\nPlan the day.",
        "manifest": {"api_version": "personal-ai-os/v1", "kind": "Skill"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(detail).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = inspect_skill(client, "http://testserver", "daily-planning")
    finally:
        client.close()

    assert result == detail
    render_skill_detail(result)


def test_inspect_skill_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            inspect_skill(client, "http://testserver", "missing-skill")
    finally:
        client.close()


def test_enable_skill_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/skills/daily-planning/enable"
        return httpx.Response(200, content=json.dumps({**SKILL, "enabled": True}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        enable_skill(client, "http://testserver", "daily-planning")
    finally:
        client.close()


def test_disable_skill_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            disable_skill(client, "http://testserver", "missing-skill")
    finally:
        client.close()


def test_run_skill_sends_arguments_and_project_id() -> None:
    captured: dict[str, object] = {}
    result_body = {
        "success": True,
        "summary": "Plan created",
        "data": {"tasks": 3},
        "evidence": [{"source_type": "task", "source_id": "t1"}],
        "artifacts": [],
        "rollback_token": None,
        "error": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps(result_body).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = run_skill(
            client, "http://testserver", "daily-planning", {"date": "2026-08-04"}, "p1"
        )
    finally:
        client.close()

    assert result == result_body
    assert captured["body"] == {"arguments": {"date": "2026-08-04"}, "project_id": "p1"}
    render_skill_result(result)


def test_run_skill_omits_project_id_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"success": True, "summary": "ok"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        run_skill(client, "http://testserver", "daily-planning", {}, None)
    finally:
        client.close()

    assert captured["body"] == {"arguments": {}}


def test_run_skill_raises_api_error_on_404_not_found() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            run_skill(client, "http://testserver", "missing-skill", {}, None)
    finally:
        client.close()


def test_run_skill_raises_api_error_on_409_conflict() -> None:
    client = _client(409, {"detail": "skill is disabled"})
    try:
        with pytest.raises(ApiError, match="skill is disabled"):
            run_skill(client, "http://testserver", "daily-planning", {}, None)
    finally:
        client.close()


def test_run_skill_raises_api_error_on_501_not_implemented() -> None:
    client = _client(501, {"detail": "skill execution not implemented"})
    try:
        with pytest.raises(ApiError, match="skill execution not implemented"):
            run_skill(client, "http://testserver", "daily-planning", {}, None)
    finally:
        client.close()


def test_run_skill_renders_failed_result_with_error() -> None:
    failed_result = {
        "success": False,
        "summary": "Could not create plan",
        "data": None,
        "evidence": [],
        "artifacts": [],
        "rollback_token": None,
        "error": "calendar unavailable",
    }
    render_skill_result(failed_result)


def test_fetch_skill_audit_returns_entries() -> None:
    entries = [
        {
            "id": "a1",
            "action": "run",
            "result": "success",
            "risk_level": "read",
            "created_at": "2026-08-04T00:00:00Z",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/skills/daily-planning/audit"
        return httpx.Response(200, content=json.dumps(entries).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_skill_audit(client, "http://testserver", "daily-planning")
    finally:
        client.close()

    assert result == entries
    table = build_skill_audit_table(result)
    assert table.row_count == 1


def test_fetch_skill_audit_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            fetch_skill_audit(client, "http://testserver", "missing-skill")
    finally:
        client.close()
