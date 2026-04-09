from trace_verification.normalize import normalize_report


def test_normalize_report() -> None:
    result = normalize_report({"severity": "WARNING", "message": "  check net  "})
    assert result == {"severity": "warning", "message": "check net"}
