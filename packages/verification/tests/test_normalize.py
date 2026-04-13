from trace_verification.normalize import normalize_report, normalize_verification_suite


def test_normalize_report() -> None:
    result = normalize_report(
        {
            "tool": "kicad-erc",
            "issues": [
                {
                    "id": "ERC_UNCONNECTED",
                    "severity": "WARNING",
                    "message": "Unconnected pin found on R1 at Net-/SENSE",
                }
            ],
        }
    )
    assert result["checks"]["erc"]["tool"] == "kicad-erc"
    assert result["severity"] == "warning"
    assert result["findings"][0]["details"]["severity"] == "warning"
    assert result["findings"][0]["details"]["source_kind"] == "formal"


def test_normalize_suite_distinguishes_formal_and_heuristic() -> None:
    result = normalize_verification_suite(
        {
            "erc": {"tool": "kicad-erc", "status": "completed", "issues": [{"id": "ERC_1", "severity": "error", "message": "power input not driven U1"}]},
            "drc": {"tool": "kicad-drc", "status": "completed", "issues": [{"id": "DRC_CRT", "severity": "warning", "message": "courtyard overlap U1 U2"}]},
            "manufacturability": {
                "tool": "manufacturability-heuristics",
                "status": "completed",
                "issues": [{"id": "MFG_TRACE_WIDTH", "severity": "warning", "message": "trace width below target"}],
            },
        }
    )
    assert result["checks"]["erc"]["finding_count"] == 1
    assert result["checks"]["drc"]["finding_count"] == 1
    assert result["checks"]["manufacturability"]["finding_count"] == 1
    assert {finding["details"]["source_kind"] for finding in result["findings"]} == {"formal", "heuristic"}
