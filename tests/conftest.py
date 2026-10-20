"""Shared pytest configuration."""

import os
import tempfile

import pytest

# Point OPENOSINT_HOME at a throwaway directory BEFORE any openosint module is
# imported: openosint.env loads (and may migrate a legacy .env into) the data
# directory's config.env at import time, and session_history resolves its
# directory at import time. Without this, a test run would read and write the
# developer's real ~/.openosint.
os.environ["OPENOSINT_HOME"] = tempfile.mkdtemp(prefix="openosint-test-home-")


@pytest.fixture(autouse=True)
def _isolated_openosint_home(tmp_path, monkeypatch):
    """Each test gets its own empty data directory."""
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "openosint-home"))

@pytest.fixture(autouse=True)
def _active_tools_for_legacy_tests(request, monkeypatch):
    """Passive mode is the product default. Tests written before it exist exercise the
    tools themselves, so they run with active tools on; test_passive_*.py runs on the
    real default (env unset) and opts in explicitly where it needs to."""
    if request.path.name.startswith("test_passive"):
        monkeypatch.delenv("OPENOSINT_ALLOW_ACTIVE", raising=False)
    else:
        monkeypatch.setenv("OPENOSINT_ALLOW_ACTIVE", "1")


# Test modules whose subjects are still `raise NotImplementedError` stubs in
# openosint/graph (see each function's docstring). Marked xfail, not skipped,
# so they start reporting XPASS once the phase is implemented.
# Remove an entry when its phase lands.
_UNIMPLEMENTED_GRAPH_STUBS = {
    "test_graph_names.py": "Phase 1 stub: extract_whois_registrant_name not implemented",
    "test_graph_dedup_candidates.py": "Phase 3 stub: dedup block_candidates not implemented",
    "test_graph_store_neighbors.py": "Phase 2 stub: rank_neighbors_for_truncation not implemented",
}
_STUB_TEST_CLASSES = {
    "TestExtractWhoisRegistrantName",
    "TestBlockCandidates",
    "TestRankNeighborsForTruncation",
}


def pytest_collection_modifyitems(items):
    for item in items:
        reason = _UNIMPLEMENTED_GRAPH_STUBS.get(item.path.name)
        if reason and item.cls is not None and item.cls.__name__ in _STUB_TEST_CLASSES:
            item.add_marker(pytest.mark.xfail(reason=reason, strict=False))


@pytest.fixture
def world(monkeypatch):
    """A perfectly configured domain. Tests mutate `w` to break one thing at a time."""
    # Imported here: openosint modules must not load before the OPENOSINT_HOME setup above.
    import ssl

    from openosint.exposure import email_check, headers_check, registration_check, tls_check
    from tests.exposure_helpers import GOOD_DMARC, GOOD_HEADERS, GOOD_SPF, make_cert, rdap_body

    w = {
        "txt": {"example.com": [GOOD_SPF], "_dmarc.example.com": [GOOD_DMARC]},
        "mx": ["10 mail.example.com."],
        "dkim": (["google: v=DKIM1; p=abc"], False),
        "bootstrap": {"com": ["https://rdap.example/"]},
        "rdap": rdap_body(),
        "tls": {"example.com": (make_cert(), "TLSv1.3"), "www.example.com": (make_cert(), "TLSv1.3")},
        "headers": dict(GOOD_HEADERS),
    }

    monkeypatch.setattr(email_check, "_txt", lambda name, zone=None: w["txt"].get(name, []))
    monkeypatch.setattr(email_check, "_mx", lambda domain, zone=None: w["mx"])
    monkeypatch.setattr(email_check, "_probe_dkim", lambda domain, zone=None: (*w["dkim"], w.get("dkim_unknown", [])))
    monkeypatch.setattr(registration_check, "_bootstrap", lambda: w["bootstrap"])
    w["rdap_queried"] = []
    w["tls_hosts"] = []
    monkeypatch.setattr(registration_check, "_rdap", lambda domain, bootstrap: w["rdap_queried"].append(domain) or w["rdap"])

    def connect(host, verify):
        w["tls_hosts"].append(host)
        entry = w["tls"][host]
        if isinstance(entry, Exception):
            if verify or not isinstance(entry, ssl.SSLError) or host not in w["tls_unverified"]:
                raise entry
            return w["tls_unverified"][host]
        return entry

    w["tls_unverified"] = {}
    monkeypatch.setattr(tls_check, "_connect", connect)
    monkeypatch.setattr(headers_check, "_get", lambda url: w["headers"])
    return w
