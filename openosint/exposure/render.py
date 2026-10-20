"""Plain-text terminal summary of an ExposureReport."""

from __future__ import annotations

from openosint.exposure.models import ExposureReport, LookalikeScan

_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def render(rep: ExposureReport) -> str:
    lines = [f"External exposure report: {rep.domain}", f"Registrable domain: {rep.registrable_domain}", f"Checked {rep.checked_at} ({rep.duration_ms} ms)", ""]
    if rep.not_run:
        lines.append(f"Not graded: only some checks were selected (not run: {', '.join(rep.not_run)}).")
    elif rep.grade == "incomplete":
        missing = [c for c in rep.excluded_checks if c in ("email", "tls")]
        score = f"partial score {rep.score}/100" if rep.score is not None else "no score"
        lines.append(f"Grade: INCOMPLETE ({score}). Required checks did not complete: {', '.join(missing)}")
    else:
        cap = " (capped at D: critical finding)" if rep.grade_capped_by_critical else ""
        lines.append(f"Grade: {rep.grade}  Score: {rep.score}/100{cap}")
    lines.append("Note: this 0-100 score is separate from the cap-based email grade used by search_dns and Domain Recon.")
    lines += ["", "Checks:"]
    for c in rep.checks:
        detail = f" - {c.reason}" if c.reason else ""
        lines.append(f"  {c.name:<13} {c.status.upper():<8} [{c.noise}]{detail}")
        lines += [f"    note: {n}" for n in c.notes]
    optional = [n for n in rep.excluded_checks if n not in ("email", "tls")]
    if optional:
        lines.append(f"Excluded from the score: {', '.join(optional)} (check did not complete).")
    lines += ["", "Findings:"]
    ordered = sorted(rep.findings, key=lambda f: _SEVERITY_ORDER.index(f.severity))
    for f in ordered or []:
        lines += [f"  [{f.severity.upper()}] {f.title} ({f.id})", f"      evidence: {f.evidence}", f"      fix: {f.recommendation}"]
    if not ordered:
        lines.append("  none")
    if rep.lookalikes:
        lines += _lookalike_lines(rep.lookalikes)
    return "\n".join(lines)


def _lookalike_lines(scan: LookalikeScan) -> list[str]:
    lines = ["", "Lookalike domains (DNS only; NOT part of the score or grade):"]
    if scan.status != "ok":
        return lines + [f"  check failed ({scan.reason_code}); no lookalike result."]
    c = scan.to_dict()["counts"]
    unknown = c["unknown_wildcard_tld"] + c["unknown_deadline"] + c["unknown_dns_error"]
    lines.append(
        f"  checked {len(scan.results)} of {scan.generated} variants; registered {c['registered']}; "
        f"unknown {unknown} (wildcard TLD {c['unknown_wildcard_tld']}, time limit {c['unknown_deadline']}, "
        f"DNS error {c['unknown_dns_error']}); skipped over the cap {scan.skipped_over_cap}"
    )
    for f in sorted(scan.findings, key=lambda f: _SEVERITY_ORDER.index(f.severity)):
        lines += [f"  [{f.severity.upper()}] {f.title} ({f.id})", f"      evidence: {f.evidence}", f"      fix: {f.recommendation}"]
    return lines
