from __future__ import annotations


def explain_finding(finding: dict) -> str:
    details = finding.get("details", {}) if isinstance(finding.get("details"), dict) else {}
    severity = str(details.get("severity", "info")).upper()
    code = str(finding.get("code", "VERIFICATION"))
    message = str(finding.get("message", "Verification issue detected."))
    cause = str(details.get("probable_cause", "Unknown cause."))
    plain_english = str(details.get("plain_english", ""))
    check = str(details.get("check", "verification")).upper()
    source_kind = str(details.get("source_kind", "formal"))
    nets = details.get("affected_nets", []) or []
    components = details.get("affected_components", []) or []
    fixes = details.get("suggested_fixes", []) or []

    scope_parts: list[str] = []
    if nets:
        scope_parts.append(f"nets: {', '.join(str(net) for net in nets)}")
    if components:
        scope_parts.append(f"components: {', '.join(str(comp) for comp in components)}")
    scope = "; ".join(scope_parts) if scope_parts else "scope not identified"

    fix_text = " ".join(f"Try: {fix}" for fix in fixes) if fixes else "Review the board around the marked objects."
    suffix = f" {plain_english}" if plain_english else ""
    return (
        f"[{severity}] [{check}/{source_kind}] {code}: {message} "
        f"Likely cause: {cause}. Affected {scope}.{suffix} {fix_text}"
    ).strip()
