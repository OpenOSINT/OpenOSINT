"""Scoring for the exposure report.

This 0-100 score is separate from the cap-based email grade used by search_dns and
Domain Recon; the two are not comparable.

score = max(0, round(100 - sum of per-category penalties)), where a finding's penalty is
severity_penalty[severity] x category_multiplier[category] and each category's total is
limited by category_penalty_cap. Tune everything in SCORING_WEIGHTS and SEVERITY_BY_ID.
"""

from __future__ import annotations

from openosint.exposure.models import STATUS_OK, CheckResult, Data, Finding, data

SCORING_WEIGHTS = {
    # Points deducted per finding of that severity (before the category multiplier).
    "severity_penalty": {"critical": 40, "high": 20, "medium": 10, "low": 4, "info": 0},
    # Email spoofing and certificate problems matter most to an insurer (1.0); registration
    # hygiene matters a bit less (0.75); missing HTTP headers are a minor signal (0.5).
    "category_multiplier": {"email": 1.0, "tls": 1.0, "registration": 0.75, "http_headers": 0.5},
    # Max total penalty per category, so one weak low-weight area cannot dominate the score.
    # Email and TLS are deliberately uncapped.
    "category_penalty_cap": {"http_headers": 10, "registration": 20},
    # Minimum score per grade, checked top-down; below the last floor is F.
    "grade_floor": (("A", 90), ("B", 80), ("C", 65), ("D", 50)),
    # Any critical finding caps the grade at this letter, whatever the numeric score.
    "critical_grade_ceiling": "D",
}

# Checks without which no letter grade is given ("incomplete"). Registration and HTTP
# headers may be missing: the grade is still given and they are listed as excluded.
REQUIRED_CHECKS = ("email", "tls")
INCOMPLETE = "incomplete"

# The single severity table. Add new ids only with a comment saying why.
SEVERITY_BY_ID = {
    # email
    "spf_plus_all": "critical",
    "spf_missing": "high",
    "spf_too_many_lookups": "high",  # > 10 DNS lookups, RFC 7208 4.6.4
    "spf_softfail": "low",
    "spf_neutral": "medium",
    "dmarc_missing": "high",
    "dmarc_policy_none": "medium",
    "dmarc_pct_below_100": "low",
    "dmarc_no_rua": "low",
    "mx_missing": "info",  # the domain may simply not receive mail
    "dkim_not_found_common_selectors": "info",  # best-effort, not conclusive
    "dkim_unverified": "info",  # added: some selectors timed out/SERVFAILed twice and none was found; a timeout never means "absent"
    # tls (apex and www evaluated separately)
    "tls_cert_expired": "critical",
    "tls_hostname_mismatch": "critical",
    "tls_cert_invalid_chain": "high",
    "tls_cert_expires_lt_14d": "high",
    "tls_cert_expires_lt_30d": "medium",
    "tls_version_below_1_2": "high",
    "tls_handshake_failed": "high",  # added: TCP 443 connects but no TLS handshake succeeds (e.g. only legacy TLS)
    "tls_unreachable_443": "info",  # no HTTPS service is not itself a finding
    # registration
    "domain_expired": "critical",  # added: expiry date already passed (days < 0); lt_30d/lt_60d fire only for 0 <= days
    "domain_expires_lt_30d": "high",
    "domain_expires_lt_60d": "medium",
    "dnssec_not_enabled": "low",  # very common, especially on .it; do not over-penalise
    "domain_age": "info",  # never penalised: age matters for supplier checks, not own exposure
    # http headers
    "hsts_missing": "low",
    "csp_missing": "low",
    "x_content_type_options_missing": "low",
    "frame_protection_missing": "low",
    "referrer_policy_missing": "info",
    # lookalikes: an external threat, NOT scored (assess() only sees the four scored checks)
    "lookalike_with_mx": "medium",  # added: a registered near-copy of the name that can send/receive email (invoice fraud)
    "lookalike_registered": "low",  # added: registered near-copy without MX; still usable on a website
    "lookalikes_none_found": "info",  # added: nothing registered among the variants checked
}

_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


def finding(
    id: str,
    category: str,
    title: str,
    evidence: str,
    recommendation: str,
    days_left: int | None = None,
    ev: tuple[str, Data] | None = None,
) -> Finding:
    """Build a Finding; severity always comes from SEVERITY_BY_ID. `ev` = (template id, data) for the report."""
    ev_id, ev_data = ev or (None, ())
    return Finding(id, category, SEVERITY_BY_ID[id], title, evidence, recommendation, days_left, ev_id, ev_data)


def ev(id: str, **values: object) -> tuple[str, Data]:
    return id, data(**values)


def _grade_for(score: int) -> str:
    return next((g for g, floor in SCORING_WEIGHTS["grade_floor"] if score >= floor), "F")


def assess(checks: tuple[CheckResult, ...]) -> tuple[int | None, str | None, bool]:
    """Return (score, grade, capped_by_critical). Only checks with status ok are scored.

    Grade is "incomplete" when a REQUIRED_CHECKS check is not ok (score is then partial).
    No completed check at all gives (None, "incomplete", False): never a free A.
    """
    done = [c for c in checks if c.status == STATUS_OK]
    if not done:
        return None, INCOMPLETE, False
    w = SCORING_WEIGHTS
    totals: dict[str, float] = {}
    for f in (f for c in done for f in c.findings):
        penalty = w["severity_penalty"][f.severity] * w["category_multiplier"].get(f.category, 1.0)
        totals[f.category] = totals.get(f.category, 0.0) + penalty
    penalty = sum(min(t, w["category_penalty_cap"].get(cat, t)) for cat, t in totals.items())
    score = max(0, round(100 - penalty))

    if {c.name for c in done} >= set(REQUIRED_CHECKS):
        grade = _grade_for(score)
    else:
        return score, INCOMPLETE, False
    has_critical = any(f.severity == "critical" for c in done for f in c.findings)
    ceiling = w["critical_grade_ceiling"]
    capped = has_critical and _GRADE_RANK[grade] < _GRADE_RANK[ceiling]
    return score, ceiling if capped else grade, capped
