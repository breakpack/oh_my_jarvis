from personal_ai_cli.main import CheckResult, CheckStatus, build_table, failed, ok, summarize


def test_ok_result_is_ok() -> None:
    result = ok("PostgreSQL", "connected")
    assert result.status is CheckStatus.OK
    assert result.is_ok is True
    assert result.detail == "connected"


def test_failed_result_is_not_ok_and_captures_error() -> None:
    result = failed("Redis", ConnectionError("refused"))
    assert result.status is CheckStatus.FAIL
    assert result.is_ok is False
    assert "ConnectionError" in result.detail
    assert "refused" in result.detail


def test_summarize_all_ok() -> None:
    results = [ok("PostgreSQL"), ok("Redis")]
    message = summarize(results)
    assert "OK" in message
    assert "FAIL" not in message


def test_summarize_lists_failed_checks() -> None:
    results = [
        ok("PostgreSQL"),
        failed("Redis", RuntimeError("down")),
        failed("Ollama", RuntimeError("down")),
    ]
    message = summarize(results)
    assert "FAIL" in message
    assert "Redis" in message
    assert "Ollama" in message


def test_build_table_has_one_row_per_check() -> None:
    results = [ok("PostgreSQL"), failed("Redis", RuntimeError("down"))]
    table = build_table(results)
    assert table.row_count == len(results)


def test_check_result_is_ok_property_matches_status() -> None:
    assert CheckResult("X", CheckStatus.OK, "").is_ok is True
    assert CheckResult("X", CheckStatus.FAIL, "").is_ok is False
