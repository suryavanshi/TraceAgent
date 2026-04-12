from trace_verification.normalize import normalize_report


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
    assert result["tool"] == "kicad-erc"
    assert result["severity"] == "warning"
    assert result["findings"][0]["details"]["severity"] == "warning"
    assert "probable_cause" in result["findings"][0]["details"]
