"""Immutable data model for the exposure report. The JSON shape is built by to_dict()."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from openosint.exposure.dns_auth import Lookup

STATUS_OK, STATUS_ERROR, STATUS_SKIPPED = "ok", "error", "skipped"
_REPORT_ONLY = ("days_left", "ev_id", "ev_data")  # Finding fields kept out of --json


# Stable codes for why a check errored or was skipped. Each needs IT and EN text in the report
# catalogs (a test enforces it); the raw English detail stays in --json only.
REASON_CODES = (
    "no_rdap_for_tld",
    "tls_verification_failed",
    "www_not_in_dns",
    "timeout",
    "dns_error",
    "unreachable",
    "name_not_resolved",
    "rdap_error",
    "unexpected_error",
    "check_failed",
    "non_public_target",  # --public-only: the host resolves to a non-public address
    "redirect_blocked",  # --public-only: a redirect left https on port 443
    "recursive_fallback",  # note only: the zone's own nameservers did not answer
)


def _checked_code(code: str) -> str:
    if code not in REASON_CODES:
        raise ValueError(f"unknown reason code: {code}")
    return code


class CheckError(Exception):
    """A check could not complete; reported as status=error and excluded from the score."""

    def __init__(self, message: str, code: str = "check_failed") -> None:
        super().__init__(message)
        self.code = _checked_code(code)


class DomainNotRegistered(ValueError):
    """The registrable domain does not exist (RDAP 404): the whole report would be meaningless."""


class CheckSkipped(Exception):
    """A check does not apply (e.g. TLD without RDAP); reported as status=skipped."""

    def __init__(self, message: str, code: str = "check_failed") -> None:
        super().__init__(message)
        self.code = _checked_code(code)


Data = tuple[tuple[str, "str | None"], ...]  # template values; None renders as "unknown"


def data(**values: object) -> Data:
    return tuple((k, None if v is None else str(v)) for k, v in values.items())


@dataclass(frozen=True)
class Passed:
    """A check that came out fine. `id` keys a catalog template filled with `data`."""

    id: str
    data: Data = ()


@dataclass(frozen=True)
class Finding:
    id: str  # stable snake_case, see scoring.SEVERITY_BY_ID
    category: str  # email | registration | tls | http_headers
    severity: str  # critical | high | medium | low | info
    title: str
    evidence: str  # the raw value observed
    recommendation: str  # one sentence
    days_left: int | None = None  # expiry findings only; used by the HTML report, not in --json
    ev_id: str | None = None  # catalog evidence template for the HTML report; not in --json
    ev_data: Data = ()


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # ok | error | skipped
    noise: str  # tool_policy.Noise value: "passive" (DNS/registry only) or "touches target"
    reason: str | None = None  # short human reason for error / skipped (<= 80 chars)
    detail: str | None = None  # full technical message; only in --json
    reason_code: str | None = None  # one of REASON_CODES; drives the translated report text
    findings: tuple[Finding, ...] = ()
    passed: tuple[Passed, ...] = ()
    notes: tuple[str, ...] = ()  # non-finding remarks, e.g. "www has no DNS record"
    note_codes: tuple[str, ...] = ()  # REASON_CODES entries parallel to notes, for the report
    dns_lookups: tuple[Lookup, ...] = ()  # where each scored in-zone DNS lookup was answered; JSON only


@dataclass(frozen=True)
class Lookalike:
    domain: str  # ASCII/punycode only, never the Unicode form
    technique: str
    state: str  # registered | not_registered | unknown
    has_mx: bool = False  # a real MX exists (the null MX "0 ." of RFC 7505 does not count)
    has_a: bool = False  # an A or AAAA answer exists; no web server is ever contacted
    unknown_reason: str | None = None  # wildcard_tld | dns_error | deadline


@dataclass(frozen=True)
class LookalikeScan:
    """Result of the opt-in --lookalikes step. A separate category: never part of score or grade."""

    status: str  # ok | error
    generated: int  # valid candidates before the cap
    skipped_over_cap: int
    results: tuple[Lookalike, ...] = ()  # every candidate that was checked
    findings: tuple[Finding, ...] = ()
    reason_code: str | None = None  # set when status is error
    noise: str = "passive"  # DNS only

    def count(self, state: str, reason: str | None = None) -> int:
        return sum(1 for r in self.results if r.state == state and (reason is None or r.unknown_reason == reason))

    def to_dict(self) -> dict:
        return {
            "scoring": "excluded",  # the grade measures the company's own configuration
            "dns_only": True,
            "noise": self.noise,
            "status": self.status,
            "reason_code": self.reason_code,
            "generated": self.generated,
            "checked": len(self.results),
            "skipped_over_cap": self.skipped_over_cap,
            "counts": {
                "registered": self.count("registered"),
                "not_registered": self.count("not_registered"),
                "unknown_wildcard_tld": self.count("unknown", "wildcard_tld"),
                "unknown_deadline": self.count("unknown", "deadline"),
                "unknown_dns_error": self.count("unknown", "dns_error"),
            },
            "candidates": [asdict(r) for r in self.results if r.state != "not_registered"],
            "findings": [{k: v for k, v in asdict(f).items() if k not in _REPORT_ONLY} for f in self.findings],
        }


@dataclass(frozen=True)
class ExposureReport:
    domain: str  # the host as given
    registrable_domain: str  # eTLD+1, used for RDAP and DMARC organizational fallback
    checked_at: str  # UTC ISO 8601
    duration_ms: int
    checks: tuple[CheckResult, ...]
    score: int | None  # None when no check completed, or when `checks=` selected only some
    grade: str | None  # A-F, "incomplete" (email or TLS missing), or None (also for a selection)
    score_is_partial: bool  # True when grade is "incomplete"
    grade_capped_by_critical: bool
    excluded_checks: tuple[str, ...]  # every check with status error/skipped
    findings: tuple[Finding, ...]
    lookalikes: LookalikeScan | None = None  # None unless --lookalikes was given
    not_run: tuple[str, ...] = ()  # checks left out by `checks=`; non-empty means the report is not graded

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "registrable_domain": self.registrable_domain,
            "checked_at": self.checked_at,
            "duration_ms": self.duration_ms,
            "grade": self.grade,
            "score": self.score,
            "score_is_partial": self.score_is_partial,
            "grade_capped_by_critical": self.grade_capped_by_critical,
            "excluded_checks": list(self.excluded_checks),
            "not_run": list(self.not_run),
            "checks": {
                c.name: {"status": c.status, "reason": c.reason, "reason_code": c.reason_code, "detail": c.detail, "noise": c.noise, "notes": list(c.notes), "dns_lookups": [{"name": lk.name, "type": lk.rtype, "dns_source": lk.dns_source, "ns_ip": lk.ns_ip} for lk in c.dns_lookups], "passed": [{"id": p.id, "data": dict(p.data)} for p in c.passed]}
                for c in self.checks
            },
            "findings": [{k: v for k, v in asdict(f).items() if k not in _REPORT_ONLY} for f in self.findings],
            "lookalikes": self.lookalikes.to_dict() if self.lookalikes else None,
        }
