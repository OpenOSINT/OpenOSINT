# tests/test_graph_dedup_cache_mitigation.py
"""Tests for the nomenklatura lru_cache staleness mitigation (Phase 4, item 4).

See openosint/graph/dedup/scoring.py's module docstring and
clear_stale_name_cache()'s docstring for the bug: LogicV2's internal
entity_names() memoizes per entity id (functools.lru_cache), and the cache
key ignores the entity's actual property values. run_crossref() now calls
clear_stale_name_cache() at the start of every pass; this file asserts that
mitigation actually works — a second run_crossref() call, after an entity's
name changed, must score it using the NEW name, not a name analysis cached
from the first call.
"""

from __future__ import annotations

import sys

import pytest

if sys.version_info < (3, 11):
    pytest.skip("requires Python >= 3.11 (graph-dedup extra)", allow_module_level=True)

pytest.importorskip("nomenklatura", reason="requires the 'graph-dedup' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.correlation import EntityType, make_entity  # noqa: E402
from openosint.graph.dedup import run_crossref  # noqa: E402
from openosint.graph.dedup.scoring import algorithm_identity, clear_stale_name_cache  # noqa: E402
from openosint.graph.identity import entity_id_for  # noqa: E402
from openosint.graph.mapping import map_github  # noqa: E402
from openosint.graph.store import GraphStore  # noqa: E402

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def _profile(login: str, name: str, email: str) -> str:
    return f"[GitHub] Login: {login}\n[GitHub] Name: {name}\n[GitHub] Email (profile): {email}\n"


class TestClearStaleNameCacheIsSafe:
    def test_calling_it_never_raises_even_if_nomenklatura_internals_moved(self):
        clear_stale_name_cache()  # must not raise under normal conditions

    def test_a_bogus_internal_path_degrades_silently(self, monkeypatch):
        import openosint.graph.dedup.scoring as scoring_mod

        # Simulate nomenklatura renaming/removing the internal cached function:
        # importing a nonexistent module path must raise ImportError, which
        # clear_stale_name_cache() must swallow, not propagate.
        original_import = __import__

        def _boom(name, *args, **kwargs):
            if name == "nomenklatura.matching.logic_v2.names.analysis":
                raise ImportError("simulated: nomenklatura moved this module")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _boom)
        scoring_mod.clear_stale_name_cache()  # must not raise


class TestAlgorithmIdentity:
    def test_returns_name_and_version(self):
        from nomenklatura.matching import LogicV2

        identity = algorithm_identity(LogicV2)
        assert identity["name"] == "logic-v2"
        assert identity["version"]  # non-empty, whatever the installed version is


class TestSecondCrossrefUsesTheNewName:
    def test_a_second_run_after_a_name_change_matches_on_the_new_name(self):
        store = GraphStore(":memory:")

        # First scan: two unrelated people. Scoring this pair warms
        # nomenklatura's internal name-analysis cache for both entity ids
        # under their OLD names.
        login = "driftuser"
        other_login = "unrelatedxyz"
        store.append(
            map_github(
                _profile(login, "Wendover Quillfeather", "x@example.com"),
                make_entity(EntityType.USERNAME, login, 1.0),
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        store.append(
            map_github(
                _profile(other_login, "Nobody Elsewise", "y@example.com"),
                make_entity(EntityType.USERNAME, other_login, 1.0),
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.99)

        # Second scan of the SAME login discovers a new, distinctive name —
        # entity_id_for() is keyed on (service, login), so this lands on the
        # SAME Person entity id, just with an additional `name` statement.
        person_id = entity_id_for("Person", "github", login)
        store.append(
            map_github(
                _profile(login, "Zoraline Vesperbrook", "x@example.com"),
                make_entity(EntityType.USERNAME, login, 1.0),
                run_id="run-2",
                collected_at=_NOW,
            )
        )

        # A third entity whose name matches the NEW name closely.
        third_login = "zoralinev"
        store.append(
            map_github(
                _profile(third_login, "Zoraline Vesperbrook", "z@example.com"),
                make_entity(EntityType.USERNAME, third_login, 1.0),
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        third_person_id = entity_id_for("Person", "github", third_login)

        # Without the cache-clear mitigation, this second run_crossref() call
        # could score person_id using its stale, cached OLD-name analysis and
        # miss this match entirely.
        suggested = run_crossref(store, run_id="crossref-2", decided_at=_NOW, min_threshold=0.5)
        matched_pairs = {frozenset({c.entity_id_a, c.entity_id_b}) for c in suggested}
        assert frozenset({person_id, third_person_id}) in matched_pairs
        store.close()
