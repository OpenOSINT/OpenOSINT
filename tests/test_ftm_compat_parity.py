"""The vendored FtM primitives must produce ids byte-identical to followthemoney's.

CI's graph-parity job installs the `graph` extra and sets REQUIRE_FTM=1, which
turns the skip below into a failure — a silently skipped parity test would
defeat its purpose.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal

import pytest

if os.environ.get("REQUIRE_FTM") == "1":
    import followthemoney  # noqa: F401  (hard failure if the extra is missing)
else:
    pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from followthemoney import model  # noqa: E402
from followthemoney.statement import Statement as RealStatement  # noqa: E402
from followthemoney.statement.util import get_prop_type as real_get_prop_type  # noqa: E402
from followthemoney.util import make_entity_id as real_make_entity_id  # noqa: E402

from openosint.graph import ftm_compat as compat  # noqa: E402
from openosint.graph.ftm_prop_types import PROP_TYPES  # noqa: E402

ID_CASES = [
    (("github", "octocat"), "UserAccount"),
    (("whois-registrant", "example.com"), "LegalEntity"),
    (("email-owner", "jane@example.com"), "LegalEntity"),
    (("a", "b", "c"), None),
    (("  padded  ", "x"), "Person"),
    (("ünïcode", "日本語", "🙂"), "Organization"),
    (("", "only-second"), "Person"),
    (("",), "Person"),
    ((), "Person"),
    ((None, "x"), "Person"),
    ((b"raw-bytes", "x"), "Person"),
    ((12, 1.5, 2.0, Decimal("3.10")), "Membership"),
    ((date(2026, 1, 2), datetime(2026, 1, 2, 3, 4, 5)), "Person"),
    (("x",), ""),
]


@pytest.mark.parametrize(("parts", "prefix"), ID_CASES)
def test_make_entity_id_matches_followthemoney(parts, prefix):
    assert compat._vendored_make_entity_id(*parts, key_prefix=prefix) == real_make_entity_id(
        *parts, key_prefix=prefix
    )


def _statement_kwargs(**overrides):
    base = {
        "entity_id": "abc123",
        "prop": "name",
        "schema": "Person",
        "value": "Jane Doe",
        "dataset": "github",
    }
    return {**base, **overrides}


STATEMENT_VARIANTS = [
    {},
    {"lang": "eng"},
    {"external": True},
    {"lang": "eng", "external": True},
    {"prop": "email", "schema": "LegalEntity", "value": "jane@example.com", "lang": "eng"},
    {"prop": "name", "value": "Ünïcode 日本語"},
    {"origin": "tool", "first_seen": "2026-01-01T00:00:00+00:00"},
]


@pytest.mark.parametrize("overrides", STATEMENT_VARIANTS)
def test_statement_matches_followthemoney(overrides):
    kwargs = _statement_kwargs(**overrides)
    real = RealStatement(**kwargs)
    vendored = compat._VendoredStatement(**kwargs)
    assert vendored.id == real.id
    assert vendored.lang == real.lang
    assert vendored.prop_type == real.prop_type
    assert vendored.canonical_id == real.canonical_id
    assert vendored.last_seen == real.last_seen


def test_statement_with_stored_id_keeps_it():
    stored = RealStatement(**_statement_kwargs()).id
    assert compat._VendoredStatement(**_statement_kwargs(id=stored)).id == stored


def test_prop_type_table_matches_the_real_model():
    assert set(PROP_TYPES) == set(compat.VENDORED_SCHEMAS)
    for schema_name, props in PROP_TYPES.items():
        schema = model.get(schema_name)
        assert props == {p: schema.get(p).type.name for p in schema.properties}


def test_vendored_prop_type_matches_real_for_every_table_entry():
    for schema_name, props in PROP_TYPES.items():
        for prop in props:
            assert compat._vendored_get_prop_type(schema_name, prop) == real_get_prop_type(
                schema_name, prop
            )
    assert compat._vendored_get_prop_type("Person", "id") == real_get_prop_type("Person", "id")


def test_unknown_schema_asks_for_the_graph_extra():
    with pytest.raises(ImportError, match="graph"):
        compat._vendored_get_prop_type("Vessel", "name")


def test_mapping_layer_only_emits_vendored_schemas():
    from openosint.graph import mapping

    source = open(mapping.__file__).read()
    import re

    emitted = set(re.findall(r'schema="([A-Za-z]+)"', source))
    assert emitted <= compat.VENDORED_SCHEMAS
