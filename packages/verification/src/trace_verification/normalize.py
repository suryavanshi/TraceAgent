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
SEVERITY_ORDER = ["info", "warning", "error", "critical"]


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


def _suggested_fixes(message: str, *, check: str) -> list[str]:
    lower = message.lower()
    suggestions: list[str] = []
    if "unconnected" in lower:
        suggestions.append("Connect the floating pin/track to a valid net or mark it as no-connect.")
    if "power" in lower and "driven" in lower:
        suggestions.append("Add a power flag or regulator source to drive the power net.")
    if "multiple drivers" in lower:
        suggestions.append("Split outputs with buffering or correct pin electrical types.")
    if "courtyard" in lower or "overlap" in lower:
        suggestions.append("Move the overlapping footprints or adjust courtyard rules.")
    if "silkscreen" in lower:
        suggestions.append("Move silkscreen text/graphics away from pads and soldermask openings.")
    if check == "manufacturability" and not suggestions:
        suggestions.append("Review board-level manufacturability constraints and update placement/rules.")
    if not suggestions:
        suggestions.append("Open the affected object in KiCad and review the rule marker details.")
    return suggestions


def _probable_cause(message: str, *, check: str) -> str:
    lower = message.lower()
    if "unconnected" in lower:
        return "A connection was left open after placement or routing changes."
    if "multiple drivers" in lower:
        return "Two output-class pins are tied on the same net."
    if "power" in lower and "driven" in lower:
        return "Power net has no explicit source or power flag."
    if "courtyard" in lower or "overlap" in lower:
        return "Footprints are too close for assembly courtyard limits."
    if check == "manufacturability":
        return "Board geometry/routing likely violates fabrication-friendly heuristics."
    return "Rule mismatch reported by verification tooling."


def _board_level_explanation(message: str, *, check: str) -> str:
    lower = message.lower()
    if check == "manufacturability" and "trace width" in lower:
        return "Some copper traces may run hotter than desired at the requested current, risking voltage drop or reliability loss."
    if check == "manufacturability" and "testpoints" in lower:
        return "There may not be enough probe access for factory test and bring-up debugging."
    if "edge" in lower:
        return "Parts appear close to the board edge, increasing depanelization and mechanical damage risk."
    if "silkscreen" in lower:
        return "Silkscreen artwork may get clipped or printed on solderable regions."
    if "courtyard" in lower:
        return "Component bodies likely intrude on each other’s keepout envelope during assembly."
    return "This issue can affect board-level functionality, assembly yield, or testability if not resolved."


def _worse(current: str, candidate: str) -> str:
    return candidate if SEVERITY_ORDER.index(candidate) > SEVERITY_ORDER.index(current) else current


def normalize_report(report: dict) -> dict:
    return normalize_verification_suite({"erc": report})


def normalize_verification_suite(report_bundle: dict) -> dict:
    findings: list[dict] = []
    affected_objects: set[str] = set()
    suggested_fixes: set[str] = set()
    report_severity = "info"

    checks: dict[str, dict] = {}
    pipelines = [
        ("erc", report_bundle.get("erc"), "formal"),
        ("drc", report_bundle.get("drc"), "formal"),
        ("manufacturability", report_bundle.get("manufacturability"), "heuristic"),
    ]

    for check_name, report, source_kind in pipelines:
        if not isinstance(report, dict):
            checks[check_name] = {"status": "not_run", "tool": check_name, "severity": "info", "finding_count": 0}
            continue
        tool = str(report.get("tool", f"kicad-{check_name}"))
        status = str(report.get("status", "unknown"))
        raw_issues = report.get("issues", [])
        issues: Iterable[dict] = raw_issues if isinstance(raw_issues, list) else []

        check_severity = "info"
        start_len = len(findings)
        for index, issue in enumerate(issues):
            severity = _normalize_severity(str(issue.get("severity", "")))
            check_severity = _worse(check_severity, severity)
            report_severity = _worse(report_severity, severity)
            message = str(issue.get("message") or issue.get("description") or f"Unknown {check_name.upper()} finding").strip()
            code = str(issue.get("code") or issue.get("id") or f"{check_name.upper()}_{index + 1}")
            nets = issue.get("affected_nets") or _extract_nets(message)
            components = issue.get("affected_components") or _extract_components(message)
            fixes = issue.get("suggested_fixes") or _suggested_fixes(message, check=check_name)

            finding = {
                "code": code,
                "message": message,
                "details": {
                    "severity": severity,
                    "check": check_name,
                    "source_kind": source_kind,
                    "probable_cause": str(issue.get("probable_cause") or _probable_cause(message, check=check_name)),
                    "plain_english": _board_level_explanation(message, check=check_name),
                    "affected_nets": nets,
                    "affected_components": components,
                    "suggested_fixes": fixes,
                    "evidence": {
                        "tool": tool,
                        "raw_issue": issue,
                        "source_report": check_name,
                    },
                },
            }
            findings.append(finding)
            for net in nets:
                affected_objects.add(str(net))
            for component in components:
                affected_objects.add(str(component))
            for fix in fixes:
                suggested_fixes.add(str(fix))

        checks[check_name] = {
            "status": status,
            "tool": tool,
            "severity": check_severity,
            "finding_count": len(findings) - start_len,
        }

    return {
        "schema_version": "1.0.0",
        "tool": "verification-suite",
        "severity": report_severity,
        "findings": findings,
        "affected_objects": sorted(affected_objects),
        "suggested_fixes": sorted(suggested_fixes),
        "checks": checks,
    }
