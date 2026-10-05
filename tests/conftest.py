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
