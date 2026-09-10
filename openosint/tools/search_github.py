# openosint/tools/search_github.py
"""
GitHub OSINT integration.

Searches GitHub for a username, email, or keyword. For direct username
matches, returns profile data, public repos, and emails discovered from
commit history. For other queries, returns the top user search hits.
Optional GITHUB_TOKEN env var raises the API rate limit from 60 to 5000
requests per hour.
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

from openosint.proxy import get_aiohttp_connector, get_aiohttp_proxy
from openosint.utils import get_ssl_context

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 30
_MAX_REPOS = 10
_COMMIT_REPOS_SAMPLE = 3
_COMMITS_PER_REPO = 5


def _build_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _get(
    session: aiohttp.ClientSession,
    url: str,
    params: dict | None = None,
) -> dict | list | None:
    async with session.get(
        url, params=params, proxy=get_aiohttp_proxy(), ssl=get_ssl_context()
    ) as resp:
        if resp.status == 404:
            return None
        resp.raise_for_status()
        return await resp.json()


async def _fetch_user(session: aiohttp.ClientSession, login: str) -> dict | None:
    result = await _get(session, f"{_API_BASE}/users/{login}")
    return result if isinstance(result, dict) else None


async def _fetch_repos(session: aiohttp.ClientSession, login: str) -> list[dict]:
    result = await _get(
        session,
        f"{_API_BASE}/users/{login}/repos",
        params={"per_page": _MAX_REPOS, "sort": "updated"},
    )
    return result if isinstance(result, list) else []


async def _discover_emails(
    session: aiohttp.ClientSession,
    login: str,
    repos: list[dict],
) -> set[str]:
    emails: set[str] = set()
    for repo in repos[:_COMMIT_REPOS_SAMPLE]:
        try:
            commits = await _get(
                session,
                f"{_API_BASE}/repos/{login}/{repo['name']}/commits",
                params={"author": login, "per_page": _COMMITS_PER_REPO},
            )
            if not isinstance(commits, list):
                continue
            for commit in commits:
                author = commit.get("commit", {}).get("author", {})
                email = author.get("email", "")
                if email and not email.endswith("noreply.github.com"):
                    emails.add(email)
        except Exception:
            pass
    return emails


async def _search_users(session: aiohttp.ClientSession, query: str) -> list[dict]:
    data = await _get(
        session,
        f"{_API_BASE}/search/users",
        params={"q": query, "per_page": 5},
    )
    if not isinstance(data, dict):
        return []
    return data.get("items", [])


def _format_profile(user: dict, repos: list[dict], emails: set[str]) -> str:
    lines = [
        f"[GitHub] Login: {user.get('login', '')}",
        f"[GitHub] Name: {user.get('name') or 'N/A'}",
        f"[GitHub] Bio: {user.get('bio') or 'N/A'}",
        f"[GitHub] Location: {user.get('location') or 'N/A'}",
        f"[GitHub] Company: {user.get('company') or 'N/A'}",
        f"[GitHub] Email (profile): {user.get('email') or 'N/A'}",
        f"[GitHub] Followers: {user.get('followers', 0)}  |  Following: {user.get('following', 0)}",
        f"[GitHub] Public repos: {user.get('public_repos', 0)}  |  Gists: {user.get('public_gists', 0)}",
        f"[GitHub] Account type: {user.get('type', 'N/A')}",
        f"[GitHub] Created: {user.get('created_at', 'N/A')}",
        f"[GitHub] Profile URL: {user.get('html_url', '')}",
    ]
    if emails:
        lines.append(f"[GitHub] Emails found in commits: {', '.join(sorted(emails))}")
    if repos:
        lines.append(f"\n[GitHub] Recent repositories (up to {_MAX_REPOS}):")
        for repo in repos:
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or "unknown"
            desc = (repo.get("description") or "").strip()
            suffix = f" — {desc[:80]}" if desc else ""
            lines.append(f"  • {repo['name']} [{lang}] ★{stars}{suffix}")
    return "\n".join(lines)


async def run_github_osint(query: str, timeout_seconds: int = _DEFAULT_TIMEOUT, *, api_key: str | None = None) -> str:
    """Search GitHub for a username, email, or keyword. GITHUB_TOKEN increases rate limits."""
    query = query.strip()
    if not query:
        return "Error: query cannot be empty."

    token = api_key or os.environ.get("GITHUB_TOKEN") or None
    timeout_cfg = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(
            headers=_build_headers(token),
            timeout=timeout_cfg,
            connector=get_aiohttp_connector(),
        ) as session:
            user = await _fetch_user(session, query)
            if user:
                repos = await _fetch_repos(session, query)
                emails = await _discover_emails(session, query, repos)
                return _format_profile(user, repos, emails)

            users = await _search_users(session, query)
            if not users:
                return f"[GitHub] No users found for query: '{query}'."

            lines = [f"[GitHub] Search results for '{query}' ({len(users)} match(es)):"]
            for u in users:
                lines.append(
                    f"  • {u.get('login')} — {u.get('html_url')} (type: {u.get('type', '?')})"
                )
            return "\n".join(lines)

    except asyncio.TimeoutError:
        return f"Scan error: GitHub request timed out after {timeout_seconds}s."
    except aiohttp.ClientResponseError as exc:
        if exc.status == 403:
            return "Scan error: GitHub rate limit exceeded. Set GITHUB_TOKEN for higher limits."
        if exc.status == 401:
            return "Scan error: Invalid GITHUB_TOKEN."
        return f"Scan error: GitHub API error HTTP {exc.status}."
    except aiohttp.ClientError as exc:
        return f"Scan error: Network error querying GitHub: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during GitHub lookup.")
        return f"Internal error: {exc}"
