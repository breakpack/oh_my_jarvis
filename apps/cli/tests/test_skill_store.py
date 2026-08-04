import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_audit_findings_table,
    build_skill_versions_table,
    fetch_skill_versions,
    install_skill,
    remove_skill_store,
    render_install_result,
    rollback_skill,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


PASSED_AUDIT = {
    "passed": True,
    "findings": [],
    "file_hash": "sha256:abc123",
    "permissions_preview": {"risk_level": "read", "scopes": ["github.read"]},
}

INSTALL_SUCCESS_BODY = {
    "skill": {"name": "github-issues-lookup", "version": "0.1.0", "risk_level": "read"},
    "audit": PASSED_AUDIT,
}

BLOCKED_AUDIT = {
    "passed": False,
    "findings": [
        {"check": "dangerous_import", "severity": "high", "message": "imports subprocess"},
    ],
    "file_hash": "sha256:def456",
    "permissions_preview": {"risk_level": "high", "scopes": ["shell.execute"]},
}

INSTALL_BLOCKED_BODY = {"skill": None, "audit": BLOCKED_AUDIT}


def test_install_skill_sends_source_path_and_returns_success_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, content=json.dumps(INSTALL_SUCCESS_BODY).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = install_skill(client, "http://testserver", "/local/skills/github-issues-lookup")
    finally:
        client.close()

    assert result == INSTALL_SUCCESS_BODY
    assert captured["path"] == "/api/v1/skills/install"
    assert captured["body"] == {"source_path": "/local/skills/github-issues-lookup"}


def test_install_skill_returns_body_on_422_blocked_instead_of_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, content=json.dumps(INSTALL_BLOCKED_BODY).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = install_skill(client, "http://testserver", "/local/skills/evil-skill")
    finally:
        client.close()

    assert result == INSTALL_BLOCKED_BODY


def test_install_skill_raises_api_error_on_other_failures() -> None:
    client = _client(500, {"detail": "registry unavailable"})
    try:
        with pytest.raises(ApiError, match="registry unavailable"):
            install_skill(client, "http://testserver", "/local/skills/x")
    finally:
        client.close()


def test_render_install_result_returns_true_and_shows_permissions_on_success() -> None:
    passed = render_install_result(INSTALL_SUCCESS_BODY, "설치")
    assert passed is True


def test_render_install_result_returns_false_and_shows_findings_when_blocked() -> None:
    passed = render_install_result(INSTALL_BLOCKED_BODY, "설치")
    assert passed is False


def test_build_audit_findings_table_has_a_row_per_finding() -> None:
    findings = BLOCKED_AUDIT["findings"]
    assert isinstance(findings, list)
    table = build_audit_findings_table(findings)
    assert table.row_count == 1


def test_fetch_skill_versions_returns_list() -> None:
    versions = [
        {"version": "0.2.0", "created_at": "2026-08-04T00:00:00Z"},
        {"version": "0.1.0", "created_at": "2026-08-01T00:00:00Z"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/skills/github-issues-lookup/versions"
        return httpx.Response(200, content=json.dumps(versions).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_skill_versions(client, "http://testserver", "github-issues-lookup")
    finally:
        client.close()

    assert result == versions
    table = build_skill_versions_table(result)
    assert table.row_count == 2


def test_fetch_skill_versions_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            fetch_skill_versions(client, "http://testserver", "missing-skill")
    finally:
        client.close()


def test_rollback_skill_sends_version() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"name": "x", "version": "0.1.0"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = rollback_skill(client, "http://testserver", "github-issues-lookup", "0.1.0")
    finally:
        client.close()

    assert result == {"name": "x", "version": "0.1.0"}
    assert captured["path"] == "/api/v1/skills/github-issues-lookup/rollback"
    assert captured["body"] == {"version": "0.1.0"}


def test_rollback_skill_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "version not found"})
    try:
        with pytest.raises(ApiError, match="version not found"):
            rollback_skill(client, "http://testserver", "missing-skill", "9.9.9")
    finally:
        client.close()


def test_remove_skill_store_sends_delete() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(204, content=b"")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        remove_skill_store(client, "http://testserver", "github-issues-lookup")
    finally:
        client.close()

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/skills/github-issues-lookup/store"


def test_remove_skill_store_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill not found"})
    try:
        with pytest.raises(ApiError, match="skill not found"):
            remove_skill_store(client, "http://testserver", "missing-skill")
    finally:
        client.close()
