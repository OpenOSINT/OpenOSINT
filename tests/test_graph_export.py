# tests/test_graph_export.py
"""Tests for openosint.graph.export — streaming FtM entity export.

No Python 3.11 / nomenklatura guard: export_entities only needs
followthemoney (the `graph` extra), same as entity_proxy.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.correlation import EntityType, make_entity
from openosint.graph.export import export_entities
from openosint.graph.mapping import map_breach, map_github
from openosint.graph.store import GraphStore

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def _profile(login: str, name: str, email: str) -> str:
    return f"[GitHub] Login: {login}\n[GitHub] Name: {name}\n[GitHub] Email (profile): {email}\n"


class TestExportEntities:
    def test_exports_one_entity_per_entity_id(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.USERNAME, "janedoe1", 1.0)
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                seed,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        entities = list(export_entities(store))
        assert len(entities) == 2  # UserAccount + Person
        schemas = {e["schema"] for e in entities}
        assert schemas == {"UserAccount", "Person"}
        store.close()

    def test_entity_dict_has_ftm_shape(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.USERNAME, "janedoe1", 1.0)
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                seed,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        person = next(e for e in export_entities(store) if e["schema"] == "Person")
        assert set(person) == {"id", "schema", "properties"}
        assert person["properties"]["name"] == ["Jane Doe"]
        store.close()

    def test_empty_store_yields_nothing(self):
        store = GraphStore(":memory:")
        assert list(export_entities(store)) == []
        store.close()


class TestExcludeDatasets:
    def test_excluding_a_dataset_drops_entities_with_no_other_statements(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)
        store.append(map_breach("[+] Adobe (2013-10-04)", seed, run_id="run-1", collected_at=_NOW))
        assert list(export_entities(store)) != []

        excluded = list(export_entities(store, exclude_datasets=frozenset({"openosint:hibp"})))
        assert excluded == []
        store.close()

    def test_excluding_a_dataset_does_not_affect_entities_from_other_datasets(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.USERNAME, "janedoe1", 1.0)
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                seed,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        entities = list(export_entities(store, exclude_datasets=frozenset({"openosint:hibp"})))
        assert len(entities) == 2
        store.close()


class TestBreachNoteMaterialization:
    def test_breach_names_are_materialized_into_notes(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)
        raw = "[+] Adobe (2013-10-04)\n[+] LinkedIn (2012-05-05)"
        store.append(map_breach(raw, seed, run_id="run-1", collected_at=_NOW))

        entity = next(iter(export_entities(store)))
        notes = entity["properties"]["notes"][0]
        assert "Adobe" in notes
        assert "LinkedIn" in notes
        store.close()

    def test_no_notes_property_when_there_is_no_breach_provenance(self):
        store = GraphStore(":memory:")
        seed = make_entity(EntityType.USERNAME, "janedoe1", 1.0)
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                seed,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        for entity in export_entities(store):
            assert "notes" not in entity["properties"]
        store.close()
