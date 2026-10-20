# openosint/pivot.py
"""
Auto-pivot investigation engine.

investigate_graph() performs a budget-bounded BFS starting from a seed value,
detects the seed's entity type, routes it to the appropriate OSINT tools,
extracts new entities from each result, and enqueues high-confidence discoveries
for further investigation — until depth, entity count, or tool-call budgets
are exhausted.

Budget caps are non-negotiable to prevent runaway cost / latency.
All tool calls are performed concurrently within each BFS depth layer.
Missing API keys skip tools gracefully; no exceptions propagate to the caller.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Any

from openosint.correlation import (
    Entity,
    EntityGraph,
    EntityType,
    Relationship,
    make_entity,
)
from openosint.extractors import EXTRACTOR_REGISTRY
from openosint.regexes import detect_entity_kind
from openosint.tool_policy import current_budget, is_tool_enabled

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PIVOT_MIN_CONFIDENCE: float = 0.6

_KIND_TO_ENTITY_TYPE: dict[str, EntityType] = {
    "email": EntityType.EMAIL,
    "url": EntityType.URL,
    "ip": EntityType.IP,
    "hash": EntityType.HASH,
    "phone": EntityType.PHONE,
    "domain": EntityType.DOMAIN,
    "username": EntityType.USERNAME,
    "person": EntityType.PERSON,
}


def _detect_entity_type(value: str) -> Entity:
    """Detect the entity type of *value* and return a seed Entity."""
    v = value.strip()
    entity_type = _KIND_TO_ENTITY_TYPE.get(detect_entity_kind(v), EntityType.USERNAME)
    return make_entity(entity_type, v, 1.0)


# ---------------------------------------------------------------------------
# Tool routing table
# ---------------------------------------------------------------------------

_TOOL_ROUTES: dict[EntityType, list[str]] = {
    EntityType.EMAIL: ["search_email", "search_breach", "search_footprint"],
    EntityType.USERNAME: ["search_username", "search_github", "search_footprint"],
    EntityType.DOMAIN: ["search_dns", "search_whois", "search_domain", "search_footprint"],
    EntityType.IP: ["search_ip", "search_shodan", "search_abuseipdb"],
    EntityType.PHONE: ["search_phone", "search_footprint"],
    EntityType.HASH: ["search_virustotal"],
    EntityType.URL: [],
    EntityType.PERSON: ["search_footprint"],
    EntityType.ORG: [],
    EntityType.ASN: [],
}

# API keys required per tool (empty list = no key needed to call this tool)
_TOOL_REQUIRED_KEYS: dict[str, list[str]] = {
    "search_email": [],
    "search_breach": ["HIBP_API_KEY"],
    "search_username": [],
    "search_github": [],
    "search_dns": [],
    "search_whois": [],
    "search_domain": [],
    "search_ip": [],
    "search_shodan": ["SHODAN_API_KEY"],
    "search_abuseipdb": ["ABUSEIPDB_API_KEY"],
    "search_phone": [],
    "search_virustotal": ["VIRUSTOTAL_API_KEY"],
    "search_censys": ["CENSYS_API_ID", "CENSYS_SECRET"],
    "search_footprint": ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"],
}


def _is_key_available(tool_name: str) -> bool:
    """Return True if all required API keys for *tool_name* are present."""
    return all(
        os.environ.get(key, "").strip()
        for key in _TOOL_REQUIRED_KEYS.get(tool_name, [])
    )


def _get_routable_tools(entity: Entity) -> list[str]:
    """Return tools applicable to *entity* whose required keys are present."""
    candidates = _TOOL_ROUTES.get(entity.type, [])
    return [t for t in candidates if is_tool_enabled(t) and _is_key_available(t)]


# ---------------------------------------------------------------------------
# Safe tool runner
# ---------------------------------------------------------------------------


def _build_arg_map(tool_name: str, entity: Entity) -> dict[str, Any]:
    """Map entity value to the correct parameter name expected by each tool."""
    value = entity.value
    param_map: dict[str, dict[str, str]] = {
        "search_email": {"email": value},
        "search_breach": {"email": value},
        "search_username": {"username": value},
        "search_github": {"query": value},
        "search_dns": {"domain": value},
        "search_whois": {"domain": value},
        "search_domain": {"domain": value},
        "search_ip": {"ip": value},
        "search_shodan": {"query": value},
        "search_abuseipdb": {"ip": value},
        "search_phone": {"phone": value},
        "search_virustotal": {"target": value},
        "search_censys": {"target": value},
        "search_footprint": {"target": value},
    }
    return param_map.get(tool_name, {"input": value})


async def _run_tool_safe(
    tool_name: str,
    entity: Entity,
    timeout_seconds: int,
) -> str:
    """Invoke a tool by name; return empty string on any failure."""
    from openosint.agent import _TOOL_MAP

    handler = _TOOL_MAP.get(tool_name)
    if handler is None:
        logger.debug("pivot: no handler for '%s'", tool_name)
        return ""

    arg_map = _build_arg_map(tool_name, entity)
    try:
        result: Any = await asyncio.wait_for(handler(arg_map), timeout=float(timeout_seconds))
        return str(result) if result is not None else ""
    except asyncio.TimeoutError:
        logger.debug("pivot: tool '%s' timed out after %ss", tool_name, timeout_seconds)
        return ""
    except Exception as exc:
        logger.debug("pivot: tool '%s' raised %s", tool_name, exc)
        return ""


# ---------------------------------------------------------------------------
# BFS auto-pivot engine
# ---------------------------------------------------------------------------


async def investigate_graph(
    seed: str,
    *,
    max_depth: int = 2,
    max_entities: int = 40,
    max_tool_calls: int = 60,
    timeout_seconds: int = 30,
) -> EntityGraph:
    """Build an entity correlation graph by BFS-pivoting from *seed*.

    Parameters
    ----------
    seed:
        Starting target value (email, domain, IP, username, phone, hash, URL).
    max_depth:
        Maximum BFS hops from the seed.
    max_entities:
        Hard cap on number of distinct entities investigated (not total in graph).
    max_tool_calls:
        Hard cap on total tool invocations across the entire run.
    timeout_seconds:
        Per-tool-call timeout in seconds.

    Returns
    -------
    EntityGraph
        The populated graph. Never raises — returns a partial graph on errors.
    """
    graph = EntityGraph()

    seed_entity = _detect_entity_type(seed)
    graph.add_entity(seed_entity)

    queue: deque[tuple[Entity, int]] = deque([(seed_entity, 0)])
    investigated: set[tuple[EntityType, str]] = set()
    queued: set[tuple[EntityType, str]] = {(seed_entity.type, seed_entity.normalized)}
    call_count = 0
    entities_investigated = 0

    while queue:
        if call_count >= max_tool_calls:
            logger.debug("pivot: max_tool_calls=%d reached", max_tool_calls)
            break

        entity, depth = queue.popleft()
        key = (entity.type, entity.normalized)

        if key in investigated:
            continue
        investigated.add(key)

        if depth >= max_depth:
            continue

        if entities_investigated >= max_entities:
            logger.debug("pivot: max_entities=%d reached", max_entities)
            break
        entities_investigated += 1

        tools = _get_routable_tools(entity)
        if not tools:
            continue

        # Slice the batch to never exceed the remaining call budget
        remaining = max_tool_calls - call_count
        batch = tools[:remaining]
        # Calls also spend the request's shared budget (see openosint.tool_policy).
        budget = current_budget()
        if budget is not None:
            batch = [t for t in batch if budget.try_consume()]
            if not batch:
                break
        call_count += len(batch)

        logger.debug(
            "pivot: depth=%d entity=%s(%s) tools=%s",
            depth,
            entity.type.value,
            entity.normalized,
            batch,
        )

        results = await asyncio.gather(
            *[_run_tool_safe(t, entity, timeout_seconds) for t in batch]
        )

        for tool_name, raw in zip(batch, results):
            extractor = EXTRACTOR_REGISTRY.get(tool_name)
            if extractor is None or not raw:
                continue

            try:
                new_entities, new_rels = extractor(raw, entity)
            except Exception as exc:
                logger.debug("pivot: extractor for '%s' raised %s", tool_name, exc)
                continue

            for new_e in new_entities:
                canonical = graph.add_entity(new_e)
                ekey = (canonical.type, canonical.normalized)
                should_enqueue = (
                    canonical.confidence >= _PIVOT_MIN_CONFIDENCE
                    and ekey not in investigated
                    and ekey not in queued
                    and len(graph._entities) <= max_entities
                    and call_count < max_tool_calls
                )
                if should_enqueue:
                    queued.add(ekey)
                    queue.append((canonical, depth + 1))

            for rel in new_rels:
                canonical_src = graph.add_entity(rel.source)
                canonical_tgt = graph.add_entity(rel.target)
                graph.add_relationship(
                    Relationship(
                        source=canonical_src,
                        target=canonical_tgt,
                        kind=rel.kind,
                        source_tool=rel.source_tool,
                        confidence=rel.confidence,
                    )
                )

    logger.debug(
        "pivot: done — %d entities, %d relationships, %d tool calls",
        len(graph._entities),
        len(graph._relationships),
        call_count,
    )
    return graph


# ---------------------------------------------------------------------------
# Agent-safe wrapper (conservative budgets, returns JSON string)
# ---------------------------------------------------------------------------


async def investigate_graph_for_agent(
    seed: str,
    max_depth: int = 1,
    max_entities: int = 15,
    max_tool_calls: int = 20,
    timeout_seconds: int = 30,
) -> str:
    """Run investigate_graph with agent-safe budgets and return JSON string.

    Conservative defaults prevent runaway cost when called from the agent loop.
    The agent loop awaits this coroutine directly — no asyncio.run() is used.
    """
    graph = await investigate_graph(
        seed,
        max_depth=max_depth,
        max_entities=max_entities,
        max_tool_calls=max_tool_calls,
        timeout_seconds=timeout_seconds,
    )
    return graph.to_json()
