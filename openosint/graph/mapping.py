# openosint/graph/mapping.py
"""
Tool output -> FtM Statement mapping. The core of Phase 1.

Scope (Q1, approved): only identity-bearing findings become FtM entities —
Person, LegalEntity, Organization, UserAccount, and their Membership edges.
Infrastructure (domain/IP/hash/ASN/bare URL) never becomes an FtM node; it
either becomes a property on an identity entity (with a BridgeLink recording
where it came from) or is left out of this layer entirely, staying only in
the existing openosint.correlation.EntityGraph.

Each map_* function corresponds to one tool's raw output and reuses that
tool's existing extractor from openosint.extractors.EXTRACTOR_REGISTRY rather
than re-parsing the raw string — the entity/relationship parsing already
exists and is tested; this layer only decides what FtM schema/property those
parsed findings become, and how they are relinked to structured entity ids.

Entity id discipline (see identity.py): every entity_id_for() call here is
keyed on a structured identifier (domain, email, (service, username)) — NEVER
on a free-text name. Names only ever become a `name` property value on an
entity keyed some other way. This is what keeps Phase 1 from silently
pre-merging two different people who happen to share a name before
nomenklatura's Phase 3 gets a chance to score the match.

All confidence values fed into ProvenanceRecord here are extractor_confidence
— ordinal heuristics from extractors.py, not calibrated probabilities. See
provenance.py's module docstring for why the two scales must never mix.

Pure functions only: no I/O, no network, no DB. Callers supply run_id and
collected_at; nothing in this module reads the clock or touches a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from followthemoney.statement import Statement

from openosint.correlation import Entity
from openosint.extractors import EXTRACTOR_REGISTRY
from openosint.graph.bridge import BridgeLink
from openosint.graph.datasets import dataset_for_tool
from openosint.graph.denylist import is_privacy_masked
from openosint.graph.identity import entity_id_for
from openosint.graph.names import extract_github_name
from openosint.graph.provenance import ProvenanceRecord, make_provenance

_PLACEHOLDER = frozenset({"", "n/a", "none", "null"})

# extractor_confidence constants, chosen to match the judgment calls already
# encoded in extractors.py's per-relationship confidence scores for the same
# fields — this layer doesn't invent a new scale, it reuses the existing one.
_CONF_STRUCTURAL = 0.95  # fields the API guarantees (login, username, service)
_CONF_PROFILE_TEXT = 0.85  # self-reported profile text (name, profile email)
_CONF_COMMIT_EMAIL = 0.85  # matches extractors._extract_github's own 0.85
_CONF_COMPANY = 0.7  # matches extractors._extract_github's own 0.7
_CONF_WHOIS_EMAIL = 0.9  # matches extractors._extract_whois's own 0.9
_CONF_WHOIS_ORG = 0.8  # matches extractors._extract_whois's own 0.8
_CONF_BREACH_FINDING = 0.9  # matches extractors._extract_breach's own 0.9


@dataclass(frozen=True)
class EmissionResult:
    """Everything one map_* call produced: statements, their provenance, and bridges.

    Tuples, not lists — a caller that wants to build a batch across multiple
    tool calls concatenates these, it never mutates one result in place.
    """

    statements: tuple[Statement, ...]
    provenance: tuple[ProvenanceRecord, ...]
    bridge_links: tuple[BridgeLink, ...]


_EMPTY = EmissionResult(statements=(), provenance=(), bridge_links=())


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return None if v.lower() in _PLACEHOLDER else v


def _profile_field(raw: str, label: str) -> str | None:
    """Read one `[GitHub] {label}: value` line from search_github.py output."""
    prefix = f"[GitHub] {label}:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            return _clean(line[len(prefix) :])
    return None


class _Batch:
    """Accumulates statements/provenance/bridges for one map_* call.

    WHY a small stateful helper instead of a pure function per statement:
    every emitted statement needs the same (dataset, run_id, collected_at)
    context and the same Statement.id auto-generation. Building each
    Statement + ProvenanceRecord pair here keeps that repetition in one
    place; the public map_* functions stay declarative call sequences.

    WHY emit() deduplicates on statement id: two emit() calls can legitimately
    describe the SAME statement observed twice in one batch — e.g. two
    breaches both confirming the same email property (correction 1), or two
    GitHub fields happening to carry an identical email address. Each call is
    still a real, distinct OBSERVATION and gets its own ProvenanceRecord, but
    the Statement itself must appear at most once in the result — FtM's
    Statement.id is content-derived, so a second Statement object with the
    same id is not a second fact, it is the same fact re-asserted.
    """

    def __init__(self, dataset: str, run_id: str, collected_at: datetime) -> None:
        self._dataset = dataset
        self._run_id = run_id
        self._collected_at = collected_at
        self._statements: list[Statement] = []
        self._seen_statement_ids: set[str] = set()
        self._provenance: list[ProvenanceRecord] = []
        self._bridge_links: list[BridgeLink] = []

    def emit(
        self,
        *,
        entity_id: str,
        schema: str,
        prop: str,
        value: str,
        method: str,
        extractor_confidence: float,
        origin: str | None = None,
        breach_name: str | None = None,
    ) -> None:
        iso_now = self._collected_at.isoformat()
        stmt = Statement(
            entity_id=entity_id,
            prop=prop,
            schema=schema,
            value=value,
            dataset=self._dataset,
            origin=origin,
            first_seen=iso_now,
            last_seen=iso_now,
        )
        if stmt.id not in self._seen_statement_ids:
            self._seen_statement_ids.add(stmt.id)
            self._statements.append(stmt)
        self._provenance.append(
            make_provenance(
                statement_id=stmt.id,
                run_id=self._run_id,
                collection_method=method,
                extractor_confidence=extractor_confidence,
                collected_at=self._collected_at,
                breach_name=breach_name,
            )
        )

    def bridge(self, ftm_entity_id: str, seed: Entity, relation: str) -> None:
        self._bridge_links.append(
            BridgeLink(
                ftm_entity_id=ftm_entity_id,
                graph_entity_type=seed.type,
                graph_entity_normalized=seed.normalized,
                relation=relation,
            )
        )

    def result(self) -> EmissionResult:
        if not self._statements:
            return _EMPTY
        return EmissionResult(
            statements=tuple(self._statements),
            provenance=tuple(self._provenance),
            bridge_links=tuple(self._bridge_links),
        )


# ---------------------------------------------------------------------------
# search_github
# ---------------------------------------------------------------------------


def map_github(raw: str, seed: Entity, *, run_id: str, collected_at: datetime) -> EmissionResult:
    """Map one search_github raw output into FtM statements.

    Only handles the exact-username profile shape (search_github.py's
    _format_profile output, identified by the `[GitHub] Login:` line). A
    keyword search-results listing has no identity fields to map and yields
    an empty result — that's correct, not a missing-field bug.

    Entity id discipline (correction 2): the Person id is
    entity_id_for("Person", "github", login) — keyed on the GitHub login
    only. The free-text `name` field is never a key part, only a property
    VALUE written onto that already-keyed entity. Two different GitHub
    accounts that happen to share a display name get two distinct Person
    ids; see tests/test_graph_mapping_github.py for the assertion.
    """
    login = _profile_field(raw, "Login")
    if not login:
        return _EMPTY

    batch = _Batch(dataset_for_tool("search_github"), run_id, collected_at)
    account_id = entity_id_for("UserAccount", "github", login)
    batch.bridge(account_id, seed, "derived_from")

    batch.emit(
        entity_id=account_id,
        schema="UserAccount",
        prop="username",
        value=login,
        method="map_github:username",
        extractor_confidence=_CONF_STRUCTURAL,
    )
    batch.emit(
        entity_id=account_id,
        schema="UserAccount",
        prop="service",
        value="github",
        method="map_github:service",
        extractor_confidence=_CONF_STRUCTURAL,
    )

    profile_url = _profile_field(raw, "Profile URL")
    if profile_url and profile_url.startswith("http"):
        batch.emit(
            entity_id=account_id,
            schema="UserAccount",
            prop="sourceUrl",
            value=profile_url,
            method="map_github:sourceUrl",
            extractor_confidence=_CONF_STRUCTURAL,
        )

    name = extract_github_name(raw)
    person_id: str | None = None
    if name:
        # Keyed on (service, login) ONLY — never on `name`. See docstring.
        person_id = entity_id_for("Person", "github", login)
        batch.emit(
            entity_id=person_id,
            schema="Person",
            prop="name",
            value=name,
            method="extract_github_name",
            extractor_confidence=_CONF_PROFILE_TEXT,
        )
        batch.emit(
            entity_id=account_id,
            schema="UserAccount",
            prop="owner",
            value=person_id,
            method="map_github:owner",
            extractor_confidence=_CONF_PROFILE_TEXT,
        )

    profile_email = _profile_field(raw, "Email (profile)")
    if profile_email:
        batch.emit(
            entity_id=account_id,
            schema="UserAccount",
            prop="email",
            value=profile_email,
            method="map_github:email_profile",
            extractor_confidence=_CONF_PROFILE_TEXT,
        )

    for line in raw.splitlines():
        if "Emails found in commits:" in line:
            _, _, emails_part = line.partition("Emails found in commits:")
            for raw_email in emails_part.split(","):
                email = raw_email.strip()
                if email:
                    batch.emit(
                        entity_id=account_id,
                        schema="UserAccount",
                        prop="email",
                        value=email,
                        method="map_github:email_commit",
                        extractor_confidence=_CONF_COMMIT_EMAIL,
                    )

    company = _profile_field(raw, "Company")
    if company:
        company = company.lstrip("@").strip()
    if company:
        org_id = entity_id_for("Organization", "github-company", company.lower())
        batch.emit(
            entity_id=org_id,
            schema="Organization",
            prop="name",
            value=company,
            method="map_github:company",
            extractor_confidence=_CONF_COMPANY,
        )
        if person_id:
            membership_id = entity_id_for("Membership", person_id, org_id)
            batch.emit(
                entity_id=membership_id,
                schema="Membership",
                prop="member",
                value=person_id,
                method="map_github:membership",
                extractor_confidence=_CONF_COMPANY,
            )
            batch.emit(
                entity_id=membership_id,
                schema="Membership",
                prop="organization",
                value=org_id,
                method="map_github:membership",
                extractor_confidence=_CONF_COMPANY,
            )

    return batch.result()


# ---------------------------------------------------------------------------
# search_whois
# ---------------------------------------------------------------------------


def map_whois(raw: str, seed: Entity, *, run_id: str, collected_at: datetime) -> EmissionResult:
    """Map one search_whois raw output into FtM statements.

    The domain itself never becomes an FtM node (Q1 — infra stays in
    EntityGraph). A synthetic LegalEntity represents "whoever WHOIS says
    controls this domain", keyed on the domain so repeat lookups land on the
    same entity. Org/Name values that match the privacy-proxy denylist (Q2)
    are dropped before emission — never turned into a name statement.
    Nameservers are intentionally excluded: they belong to the DNS/registrar
    infrastructure, not to the registrant's identity.
    """
    _entities, relationships = EXTRACTOR_REGISTRY["search_whois"](raw, seed)
    if not relationships:
        return _EMPTY

    batch = _Batch(dataset_for_tool("search_whois"), run_id, collected_at)
    registrant_id = entity_id_for("LegalEntity", "whois-registrant", seed.normalized)
    emitted_any = False

    for rel in relationships:
        if rel.kind == "registrant_email":
            batch.emit(
                entity_id=registrant_id,
                schema="LegalEntity",
                prop="email",
                value=rel.target.value,
                method="map_whois:email",
                extractor_confidence=_CONF_WHOIS_EMAIL,
            )
            emitted_any = True
        elif rel.kind == "registrant_org":
            org_value = rel.target.value
            if not is_privacy_masked(org_value):
                batch.emit(
                    entity_id=registrant_id,
                    schema="LegalEntity",
                    prop="name",
                    value=org_value,
                    method="map_whois:name_org",
                    extractor_confidence=_CONF_WHOIS_ORG,
                )
                emitted_any = True
        # "nameserver" kind: deliberately not mapped — see docstring.

    if not emitted_any:
        return _EMPTY

    batch.bridge(registrant_id, seed, "derived_from")
    return batch.result()


# ---------------------------------------------------------------------------
# search_breach
# ---------------------------------------------------------------------------


def map_breach(raw: str, seed: Entity, *, run_id: str, collected_at: datetime) -> EmissionResult:
    """Map one search_breach raw output into FtM statements.

    Decision A, refined per correction 1: a breach is provenance, not an
    entity — no synthetic breach node, no `notes` string-hack. Every breach
    found is a separate OBSERVATION of the same `email` statement (this HIBP
    query independently confirms the email exists, once per breach it
    appears in) — not a separate statement. N breaches found -> ONE
    Statement + N ProvenanceRecords, each carrying its own breach_name. The
    sidecar is the source of truth for "which breaches"; a `notes` property
    is only ever synthesized from it at .ftm export time (see
    materialize.breach_notes_for_statement), since the sidecar has no
    equivalent in the exported FtM format.
    """
    _entities, relationships = EXTRACTOR_REGISTRY["search_breach"](raw, seed)
    breach_names = [rel.target.value for rel in relationships if rel.kind == "found_in_breach"]
    if not breach_names:
        return _EMPTY

    batch = _Batch(dataset_for_tool("search_breach"), run_id, collected_at)
    owner_id = entity_id_for("LegalEntity", "email-owner", seed.normalized)

    for breach_name in breach_names:
        batch.emit(
            entity_id=owner_id,
            schema="LegalEntity",
            prop="email",
            value=seed.value,
            method="map_breach:email",
            extractor_confidence=_CONF_BREACH_FINDING,
            breach_name=breach_name,
        )

    batch.bridge(owner_id, seed, "derived_from")
    return batch.result()
