from __future__ import annotations

from collections.abc import Iterable

SEVERITY_MAP = {
    "note": "info",
    "info": "info",
    "warning": "warning",
    "warn": "warning",
    "error": "error",
    "err": "error",
    "critical": "critical",
    "fatal": "critical",
}


def _normalize_severity(value: str | None) -> str:
    if not value:
        return "info"
    return SEVERITY_MAP.get(value.strip().lower(), "info")


def _extract_nets(message: str) -> list[str]:
    nets: list[str] = []
    for token in message.replace(",", " ").split():
        if token.startswith("Net-") or token.startswith("N$") or token.startswith("/"):
            nets.append(token.strip("[]()"))
    return sorted(set(nets))


def _extract_components(message: str) -> list[str]:
    components: list[str] = []
    for token in message.replace(",", " ").split():
        candidate = token.strip("[]():")
        if len(candidate) >= 2 and candidate[0] in {"R", "C", "L", "U", "D", "Q", "J", "TP"} and any(
            c.isdigit() for c in candidate
        ):
            components.append(candidate)
    return sorted(set(components))


def _suggested_fixes(message: str) -> list[str]:
    lower = message.lower()
    suggestions: list[str] = []
    if "unconnected" in lower:
        suggestions.append("Connect the floating pin to a valid net or mark it as no-connect.")
    if "power" in lower and "driven" in lower:
        suggestions.append("Add a power flag or regulator source to drive the power net.")
    if "multiple drivers" in lower:
        suggestions.append("Split outputs with buffering or correct pin electrical types.")
    if not suggestions:
        suggestions.append("Open the schematic at the affected objects and review ERC marker details.")
    return suggestions


def _probable_cause(message: str) -> str:
    lower = message.lower()
    if "unconnected" in lower:
        return "Pin was left floating after placement or refactoring."
    if "multiple drivers" in lower:
        return "Two output-class pins are tied on the same net."
    if "power" in lower and "driven" in lower:
        return "Power net has no explicit source or power flag."
    return "Electrical rule mismatch detected by ERC."


def normalize_report(report: dict) -> dict:
    tool = str(report.get("tool", "kicad-erc"))
    raw_issues = report.get("issues", [])
    issues: Iterable[dict] = raw_issues if isinstance(raw_issues, list) else []
    findings: list[dict] = []
    report_severity = "info"
    affected_objects: set[str] = set()
    suggested_fixes: set[str] = set()

    for index, issue in enumerate(issues):
        severity = _normalize_severity(str(issue.get("severity", "")))
        if ["info", "warning", "error", "critical"].index(severity) > ["info", "warning", "error", "critical"].index(
            report_severity
        ):
            report_severity = severity
        message = str(issue.get("message") or issue.get("description") or "Unknown ERC finding").strip()
        code = str(issue.get("code") or issue.get("id") or f"ERC_{index + 1}")
        nets = issue.get("affected_nets") or _extract_nets(message)
        components = issue.get("affected_components") or _extract_components(message)
        cause = str(issue.get("probable_cause") or _probable_cause(message))
        fixes = issue.get("suggested_fixes") or _suggested_fixes(message)
        finding = {
            "code": code,
            "message": message,
            "details": {
                "severity": severity,
                "probable_cause": cause,
                "affected_nets": nets,
                "affected_components": components,
                "suggested_fixes": fixes,
            },
        }
        findings.append(finding)
        for net in nets:
            affected_objects.add(str(net))
        for component in components:
            affected_objects.add(str(component))
        for fix in fixes:
            suggested_fixes.add(str(fix))

    return {
        "schema_version": "1.0.0",
        "tool": tool,
        "severity": report_severity,
        "findings": findings,
        "affected_objects": sorted(affected_objects),
        "suggested_fixes": sorted(suggested_fixes),
    }
