# openosint/multi_target.py
"""
Multi-target investigation support.

Runs independent OSINT investigations for multiple targets in parallel
via asyncio.gather().  Each target gets its own timestamped report file.
A consolidated summary report is generated after all targets complete.

Maximum 10 targets per run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from openosint.agent import AgentResponse, OpenOSINTAgent
from openosint.tool_policy import ENV_MAX_CALLS, ENV_MAX_CALLS_MULTI, ToolBudget, max_tool_calls_multi

logger = logging.getLogger(__name__)

MAX_TARGETS = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_targets(source: str) -> list[str]:
    """
    Parse a target list from *source*.

    If *source* is the path of an existing file, read one target per line.
    Otherwise treat *source* as comma-separated inline targets.
    """
    p = Path(source)
    if p.exists() and p.is_file():
        lines = p.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip()]
    return [t.strip() for t in source.split(",") if t.strip()]


async def _investigate_one(
    target: str,
    api_key: str | None,
    reports_dir: Path,
    date_prefix: str,
    budget: ToolBudget,
) -> tuple[str, AgentResponse]:
    """Run one investigation and persist its report."""
    agent = OpenOSINTAgent(api_key=api_key)
    logger.info("Multi-target: investigating %s", target)
    response = await agent.run(prompt=f"Investigate: {target}", budget=budget)

    if response.content and "##" in response.content and len(response.content) > 300:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in target)
        path = reports_dir / f"{date_prefix}_{safe}_report.md"
        path.write_text(response.content, encoding="utf-8")
        logger.info("Saved: %s", path)

    return target, response


def _build_summary(results: list[tuple[str, AgentResponse]], date_prefix: str) -> str:
    lines = [
        "# OpenOSINT Multi-Target Investigation Summary",
        "",
        f"**Date:** {date_prefix}  ",
        f"**Targets investigated:** {len(results)}",
        "",
        "---",
        "",
    ]
    for target, response in results:
        lines.append(f"## {target}")
        lines.append("")
        if response.error:
            lines.append(f"**Error:** {response.error}")
        elif response.content:
            content = response.content
            summary_start = content.find("## Summary")
            conclusion_start = content.find("## Conclusion")
            if summary_start != -1:
                end = conclusion_start if conclusion_start != -1 else len(content)
                lines.append(content[summary_start:end].strip())
            else:
                excerpt = content[:500].strip()
                if len(content) > 500:
                    excerpt += "…"
                lines.append(excerpt)
        else:
            lines.append("No findings.")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_multi_target(
    targets: list[str],
    api_key: str | None = None,
    is_pdf_disabled: bool = False,
) -> str:
    """
    Investigate targets in parallel using asyncio.gather().

    Parameters
    ----------
    targets:
        List of OSINT targets (emails, usernames, domains, IPs, names).
        Maximum ``MAX_TARGETS`` entries.
    api_key:
        Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
    is_pdf_disabled:
        When True, skip PDF generation for the summary report.

    Returns
    -------
    str
        Markdown summary report (also written to ``reports/``).

    Raises
    ------
    ValueError
        If more than ``MAX_TARGETS`` targets are supplied.
    """
    if len(targets) > MAX_TARGETS:
        raise ValueError(
            f"Multi-target investigation supports at most {MAX_TARGETS} targets; "
            f"got {len(targets)}. Split into smaller batches."
        )
    if not targets:
        return "No targets provided."

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    date_prefix = datetime.now().strftime("%Y-%m-%d")

    # One budget for the whole run: N targets must not mean N x OPENOSINT_MAX_TOOL_CALLS.
    budget = ToolBudget(limit=max_tool_calls_multi())
    tasks = [_investigate_one(target, api_key, reports_dir, date_prefix, budget) for target in targets]
    results: list[tuple[str, AgentResponse]] = await asyncio.gather(*tasks)

    summary = _build_summary(results, date_prefix)
    if budget.denied:
        summary = f"> ⚠ {budget.message().replace(ENV_MAX_CALLS, ENV_MAX_CALLS_MULTI)}\n\n" + summary

    summary_path = reports_dir / f"{date_prefix}_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    logger.info("Summary report: %s", summary_path)

    if not is_pdf_disabled:
        try:
            from openosint.pdf_report import generate_pdf_report

            await generate_pdf_report(summary_path)
        except Exception:
            logger.debug("PDF skipped for summary.", exc_info=True)

    return summary
