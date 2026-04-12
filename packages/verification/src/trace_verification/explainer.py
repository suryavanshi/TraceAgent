from __future__ import annotations


def explain_finding(finding: dict) -> str:
    details = finding.get("details", {}) if isinstance(finding.get("details"), dict) else {}
    severity = str(details.get("severity", "info")).upper()
    code = str(finding.get("code", "ERC"))
    message = str(finding.get("message", "Electrical rule issue detected."))
    cause = str(details.get("probable_cause", "Unknown cause."))
    nets = details.get("affected_nets", []) or []
    components = details.get("affected_components", []) or []
    fixes = details.get("suggested_fixes", []) or []

    scope_parts: list[str] = []
    if nets:
        scope_parts.append(f"nets: {', '.join(str(net) for net in nets)}")
    if components:
        scope_parts.append(f"components: {', '.join(str(comp) for comp in components)}")
    scope = "; ".join(scope_parts) if scope_parts else "scope not identified"

    fix_text = " ".join(f"Try: {fix}" for fix in fixes) if fixes else "Review the schematic around the ERC marker."
    return f"[{severity}] {code}: {message} Likely cause: {cause}. Affected {scope}. {fix_text}".strip()
