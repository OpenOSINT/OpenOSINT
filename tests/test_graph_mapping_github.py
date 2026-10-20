# tests/test_graph_mapping_github.py
"""Tests for openosint.graph.mapping.map_github."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.correlation import EntityType, make_entity  # noqa: E402
from openosint.graph.identity import entity_id_for  # noqa: E402
from openosint.graph.mapping import map_github  # noqa: E402

_SEED = make_entity(EntityType.USERNAME, "octocat", 1.0)
_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)

_FULL_PROFILE = (
    "[GitHub] Login: octocat\n"
    "[GitHub] Name: The Octocat\n"
    "[GitHub] Bio: N/A\n"
    "[GitHub] Location: San Francisco\n"
    "[GitHub] Company: @GitHub\n"
    "[GitHub] Email (profile): octocat@github.com\n"
    "[GitHub] Followers: 100  |  Following: 9\n"
    "[GitHub] Public repos: 8  |  Gists: 8\n"
    "[GitHub] Account type: User\n"
    "[GitHub] Created: 2011-01-25T18:44:36Z\n"
    "[GitHub] Profile URL: https://github.com/octocat\n"
    "[GitHub] Emails found in commits: commit1@example.com, commit2@example.com\n"
)


def _prop_values(result, entity_id, prop):
    return [s.value for s in result.statements if s.entity_id == entity_id and s.prop == prop]


class TestMapGithubFullProfile:
    def test_useraccount_structural_fields(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        account_id = entity_id_for("UserAccount", "github", "octocat")
        assert _prop_values(result, account_id, "username") == ["octocat"]
        assert _prop_values(result, account_id, "service") == ["github"]
        assert _prop_values(result, account_id, "sourceUrl") == ["https://github.com/octocat"]

    def test_person_and_owner_link(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        account_id = entity_id_for("UserAccount", "github", "octocat")
        person_id = entity_id_for("Person", "github", "octocat")
        assert _prop_values(result, person_id, "name") == ["The Octocat"]
        assert _prop_values(result, account_id, "owner") == [person_id]

    def test_both_profile_and_commit_emails_survive(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        account_id = entity_id_for("UserAccount", "github", "octocat")
        emails = _prop_values(result, account_id, "email")
        assert set(emails) == {"octocat@github.com", "commit1@example.com", "commit2@example.com"}
        # three distinct values -> three distinct statement ids, none collapsed
        assert len({s.id for s in result.statements if s.prop == "email"}) == 3

    def test_company_becomes_organization_with_membership(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        org_id = entity_id_for("Organization", "github-company", "github")
        person_id = entity_id_for("Person", "github", "octocat")
        membership_id = entity_id_for("Membership", person_id, org_id)
        assert _prop_values(result, org_id, "name") == ["GitHub"]
        assert _prop_values(result, membership_id, "member") == [person_id]
        assert _prop_values(result, membership_id, "organization") == [org_id]

    def test_provenance_is_one_to_one_with_statements(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        assert len(result.provenance) == len(result.statements)
        assert {p.statement_id for p in result.provenance} == {s.id for s in result.statements}

    def test_bridge_link_points_back_to_seed_username(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        account_id = entity_id_for("UserAccount", "github", "octocat")
        assert len(result.bridge_links) == 1
        link = result.bridge_links[0]
        assert link.ftm_entity_id == account_id
        assert link.graph_entity_type == EntityType.USERNAME
        assert link.graph_entity_normalized == "octocat"
        assert link.relation == "derived_from"

    def test_collection_method_names_the_specific_mapper(self):
        result = map_github(_FULL_PROFILE, _SEED, run_id="run-1", collected_at=_NOW)
        methods = {p.collection_method for p in result.provenance}
        assert "extract_github_name" in methods
        assert "map_github:username" in methods


class TestMapGithubMissingFields:
    def test_login_only_yields_structural_fields_and_nothing_else(self):
        raw = "[GitHub] Login: octocat\n"
        result = map_github(raw, _SEED, run_id="run-1", collected_at=_NOW)
        account_id = entity_id_for("UserAccount", "github", "octocat")
        assert _prop_values(result, account_id, "username") == ["octocat"]
        assert not any(s.prop == "name" for s in result.statements)
        assert not any(s.schema == "Organization" for s in result.statements)

    def test_na_placeholders_are_skipped_not_emitted_as_values(self):
        raw = (
            "[GitHub] Login: octocat\n"
            "[GitHub] Name: N/A\n"
            "[GitHub] Company: N/A\n"
            "[GitHub] Email (profile): N/A\n"
        )
        result = map_github(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert not any(s.prop == "name" for s in result.statements)
        assert not any(s.prop == "email" for s in result.statements)


class TestMapGithubPersonIdDerivation:
    """Correction 2: Person id must derive from (service, login) only, never from `name`."""

    def test_two_accounts_with_identical_name_get_distinct_person_ids(self):
        octocat_profile = "[GitHub] Login: octocat\n[GitHub] Name: Ada Lovelace\n"
        other_profile = "[GitHub] Login: someoneelse\n[GitHub] Name: Ada Lovelace\n"
        other_seed = make_entity(EntityType.USERNAME, "someoneelse", 1.0)

        result_a = map_github(octocat_profile, _SEED, run_id="run-1", collected_at=_NOW)
        result_b = map_github(other_profile, other_seed, run_id="run-1", collected_at=_NOW)

        person_a = next(s.entity_id for s in result_a.statements if s.prop == "name")
        person_b = next(s.entity_id for s in result_b.statements if s.prop == "name")

        assert person_a != person_b
        assert person_a == entity_id_for("Person", "github", "octocat")
        assert person_b == entity_id_for("Person", "github", "someoneelse")

    def test_person_id_is_unaffected_by_a_changed_display_name(self):
        """Same login, name changes between runs -> the SAME Person id both times."""
        first_run = "[GitHub] Login: octocat\n[GitHub] Name: The Octocat\n"
        renamed = "[GitHub] Login: octocat\n[GitHub] Name: Mona Lisa\n"

        result_first = map_github(first_run, _SEED, run_id="run-1", collected_at=_NOW)
        result_renamed = map_github(renamed, _SEED, run_id="run-2", collected_at=_NOW)

        person_first = next(s.entity_id for s in result_first.statements if s.prop == "name")
        person_renamed = next(s.entity_id for s in result_renamed.statements if s.prop == "name")
        assert person_first == person_renamed == entity_id_for("Person", "github", "octocat")


class TestMapGithubMalformedInput:
    def test_empty_raw_returns_empty_result(self):
        result = map_github("", _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()
        assert result.provenance == ()
        assert result.bridge_links == ()

    def test_search_results_listing_has_no_login_line_and_yields_nothing(self):
        raw = (
            "[GitHub] Search results for 'octo' (2 match(es)):\n"
            "  • octocat — https://github.com/octocat (type: User)\n"
        )
        result = map_github(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()
