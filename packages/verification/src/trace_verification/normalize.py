def normalize_report(report: dict[str, str]) -> dict[str, str]:
    severity = report.get("severity", "info").lower()
    message = report.get("message", "")
    return {"severity": severity, "message": message.strip()}
