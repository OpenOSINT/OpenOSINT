# openosint/multi_target.py
"""
Multi-target investigation support.

Runs independent OSINT investigations for multiple targets in parallel
via asyncio.gather(). Each run gets a unique directory with numbered target
reports. A consolidated summary is generated after all targets complete.

Maximum 10 targets per run.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from openosint.agent import AgentResponse, OpenOSINTAgent

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
    report_index: int,
) -> tuple[str, AgentResponse]:
    """Run one investigation and persist its report."""
    agent = OpenOSINTAgent(api_key=api_key)
    logger.info("Multi-target: investigating %s", target)
    response = await agent.run(prompt=f"Investigate: {target}")

    if response.content and "##" in response.content and len(response.content) > 300:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in target)
        path = reports_dir / f"{report_index:02d}_{safe}_report.md"
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
        Markdown summary report (also written to a unique run directory under
        ``reports/`` alongside the individual target reports).

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
    started_at = datetime.now()
    date_prefix = started_at.strftime("%Y-%m-%d")
    # Atomically reserve a directory even when concurrent runs share a timestamp.
    run_dir = Path(
        tempfile.mkdtemp(prefix=started_at.strftime("%Y-%m-%d_%H-%M-%S_"), dir=reports_dir)
    )

    # Ordinals keep duplicate, sanitized, and case-insensitive names distinct.
    tasks = [
        _investigate_one(target, api_key, run_dir, index)
        for index, target in enumerate(targets, start=1)
    ]
    results: list[tuple[str, AgentResponse]] = await asyncio.gather(*tasks)

    summary = _build_summary(results, date_prefix)

    summary_path = run_dir / "summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    logger.info("Summary report: %s", summary_path)

    if not is_pdf_disabled:
        try:
            from openosint.pdf_report import generate_pdf_report

            await generate_pdf_report(summary_path)
        except Exception:
            logger.debug("PDF skipped for summary.", exc_info=True)

    return summary
