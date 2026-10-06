"""FollowTheMoney primitives that work with or without followthemoney installed.

followthemoney -> normality -> PyICU, and PyICU is source-only (needs libicu and
a compiler), so `uvx openosint web` could not start the graph store on a clean
machine. The graph store only needs three small things from followthemoney —
`make_entity_id`, `Statement` and `get_prop_type` — all of which are a SHA1 over
a few strings. When the real library imports, this module re-exports it
unchanged (the `[graph]` extra stays the source of truth). When it does not, the
vendored versions below produce byte-identical ids.

That identity is what lets a graph.db written with one be read with the other,
and is enforced by tests/test_ftm_compat_parity.py, which CI runs against the
real library (REQUIRE_FTM=1 turns a skip into a failure).

Features that need the real FtM model or matching (`.ftm` export, dedup) keep
importing followthemoney directly and report "needs openosint[graph]".
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Schemas OpenOSINT's mapping layer emits; ftm_prop_types.py covers exactly these.
VENDORED_SCHEMAS = frozenset({"LegalEntity", "Membership", "Organization", "Person", "UserAccount"})

_ENCODING = "utf-8"
_BASE_ID = "id"
# followthemoney.statement.statement.NON_LANG_TYPE_NAMES
_NON_LANG_TYPES = frozenset(
    {
        "entity",
        "topic",
        "url",
        "language",
        "id",
        "date",
        "mimetype",
        "country",
        "ip",
        "checksum",
        "email",
        "phone",
        "gender",
    }
)


class GraphExtraRequired(ImportError):
    """Raised when an operation needs the real followthemoney (the `graph` extra).

    Subclasses ImportError so the web and MCP layers' existing
    `except ImportError` handlers turn it into the standard "needs the 'graph'
    extra" message.
    """


def _stringify(value: Any) -> str | None:
    """normality.stringify, minus the bytes branch (handled by _key_bytes)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (date, datetime)):
        text = value.isoformat()
    elif isinstance(value, float):
        text = format(value, ".3f").rstrip("0").rstrip(".")
    elif isinstance(value, Decimal):
        text = value.to_eng_string()
    else:
        text = str(value)
    text = text.strip()
    return text or None


def _key_bytes(part: Any) -> bytes:
    if isinstance(part, bytes):
        return part
    text = _stringify(part)
    return b"" if text is None else text.encode(_ENCODING)


def _vendored_make_entity_id(*parts: Any, key_prefix: str | None = None) -> str | None:
    digest = hashlib.sha1()
    if key_prefix:
        digest.update(_key_bytes(key_prefix))
    base = digest.digest()
    for part in parts:
        digest.update(_key_bytes(part))
    if digest.digest() == base:
        return None
    return digest.hexdigest()


def _vendored_get_prop_type(schema: str, prop: str) -> str:
    if prop == _BASE_ID:
        return _BASE_ID
    from openosint.graph.ftm_prop_types import PROP_TYPES

    props = PROP_TYPES.get(schema)
    if props is None:
        raise GraphExtraRequired(
            f"Schema {schema!r} is outside the built-in graph model; "
            "install the 'graph' extra: pip install 'openosint[graph]'"
        )
    prop_type = props.get(prop)
    if prop_type is None:
        raise TypeError(f"Property not found: {prop}")
    return prop_type


class _VendoredStatement:
    """The subset of followthemoney.statement.Statement the graph store uses."""

    __slots__ = (
        "_dataset",
        "_entity_id",
        "_external",
        "_lang",
        "_prop",
        "_schema",
        "_value",
        "canonical_id",
        "first_seen",
        "id",
        "last_seen",
        "original_value",
        "origin",
        "prop_type",
    )

    def __init__(
        self,
        entity_id: str,
        prop: str,
        schema: str,
        value: str,
        dataset: str,
        lang: str | None = None,
        original_value: str | None = None,
        first_seen: str | None = None,
        external: bool = False,
        id: str | None = None,
        canonical_id: str | None = None,
        last_seen: str | None = None,
        origin: str | None = None,
    ):
        self._entity_id = entity_id
        self.canonical_id = canonical_id or entity_id
        self._prop = prop
        self._schema = schema
        self.prop_type = _vendored_get_prop_type(schema, prop)
        self._value = value
        self._dataset = dataset
        if lang is not None and self.prop_type in _NON_LANG_TYPES:
            lang = None
        self._lang = lang
        self.original_value = original_value
        self.first_seen = first_seen
        self.last_seen = last_seen or first_seen
        self._external = external
        self.origin = origin
        self.id = id if id is not None else self.generate_key()

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def prop(self) -> str:
        return self._prop

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def value(self) -> str:
        return self._value

    @property
    def dataset(self) -> str:
        return self._dataset

    @property
    def lang(self) -> str | None:
        return self._lang

    @property
    def external(self) -> bool:
        return self._external

    @classmethod
    def make_key(
        cls,
        dataset: str,
        entity_id: str,
        prop: str,
        value: str,
        external: bool | None,
        lang: str | None = None,
    ) -> str | None:
        if prop is None or value is None:
            return None
        key = f"{dataset}.{entity_id}.{prop}.{value}"
        if lang is not None:
            key = f"{key}@{lang}"
        if external:
            key = f"{key}.ext"
        return hashlib.sha1(key.encode(_ENCODING)).hexdigest()

    def generate_key(self) -> str | None:
        return self.make_key(
            self._dataset, self._entity_id, self._prop, self._value, self._external, lang=self._lang
        )

    def __eq__(self, other: Any) -> bool:
        return self.id == getattr(other, "id", None)

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<Statement({self._entity_id!r}, {self._prop!r}, {self._value!r})>"


try:
    from followthemoney.statement import Statement
    from followthemoney.statement.util import get_prop_type
    from followthemoney.util import make_entity_id

    HAS_FTM = True
except ImportError:  # no followthemoney, or PyICU present but unloadable
    Statement = _VendoredStatement  # type: ignore[misc,assignment]
    get_prop_type = _vendored_get_prop_type
    make_entity_id = _vendored_make_entity_id
    HAS_FTM = False

__all__ = [
    "HAS_FTM",
    "VENDORED_SCHEMAS",
    "GraphExtraRequired",
    "Statement",
    "get_prop_type",
    "make_entity_id",
]
