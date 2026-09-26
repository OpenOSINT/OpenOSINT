"""Offline regressions for preserving reports across targets and runs."""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from openosint import multi_target
from openosint.agent import AgentResponse


@pytest.fixture
def report_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 9, 22, 12, 0, 0)

    monkeypatch.setattr(multi_target, "datetime", FrozenDatetime)
    contents = []

    async def investigate(prompt):
        content = (
            f"## Summary\n\nReport {len(contents)} for {prompt}\n" + "Synthetic finding. " * 30
        )
        contents.append(content)
        await asyncio.sleep(0)
        return AgentResponse(content=content)

    agent = Mock()
    agent.run = AsyncMock(side_effect=investigate)
    monkeypatch.setattr(multi_target, "OpenOSINTAgent", Mock(return_value=agent))
    return contents


async def test_repeated_runs_preserve_all_previous_reports(report_run):
    await multi_target.run_multi_target(["example.com"], is_pdf_disabled=True)
    before = {p: p.read_bytes() for p in Path("reports").rglob("*.md")}
    assert len(before) == 2

    await multi_target.run_multi_target(["example.com"], is_pdf_disabled=True)

    assert all(path.read_bytes() == content for path, content in before.items())
    assert len(list(Path("reports").rglob("*summary.md"))) == 2
    assert len(list(Path("reports").rglob("*_report.md"))) == 2


@pytest.mark.parametrize(
    "targets",
    [
        ["a+b@example.com", "a_b@example.com"],
        ["EXAMPLE.com", "example.com"],
        ["example.com", "example.com"],
    ],
)
async def test_each_target_gets_its_own_report(targets, report_run):
    await multi_target.run_multi_target(targets, is_pdf_disabled=True)

    reports = list(Path("reports").rglob("*_report.md"))
    assert len(reports) == len(targets)
    assert {p.read_text(encoding="utf-8") for p in reports} == set(report_run)
    # Even on case-insensitive Windows filesystems the destinations must differ.
    assert len({str(p).casefold() for p in reports}) == len(targets)


async def test_concurrent_runs_with_same_timestamp_use_separate_directories(report_run):
    summaries = await asyncio.gather(
        multi_target.run_multi_target(["example.com"], is_pdf_disabled=True),
        multi_target.run_multi_target(["example.com"], is_pdf_disabled=True),
    )

    paths = list(Path("reports").rglob("*summary.md"))
    assert len(paths) == 2
    assert len({p.parent for p in paths}) == 2
    assert {p.read_text(encoding="utf-8") for p in paths} == set(summaries)
    for path in paths:
        assert len(list(path.parent.glob("*_report.md"))) == 1


async def test_preserves_legacy_flat_reports(report_run):
    Path("reports").mkdir()
    legacy = [
        Path("reports/2026-09-22_summary.md"),
        Path("reports/2026-09-22_example.com_report.md"),
    ]
    for path in legacy:
        path.write_text("Previous investigation", encoding="utf-8")

    await multi_target.run_multi_target(["example.com"], is_pdf_disabled=True)

    assert all(p.read_text(encoding="utf-8") == "Previous investigation" for p in legacy)
    assert len(list(Path("reports").rglob("*.md"))) == 4


async def test_pdf_receives_summary_from_the_same_run(report_run, monkeypatch):
    from openosint import pdf_report

    generate_pdf = AsyncMock()
    monkeypatch.setattr(pdf_report, "generate_pdf_report", generate_pdf)
    summary = await multi_target.run_multi_target(["example.com"])

    generate_pdf.assert_awaited_once()
    summary_path = generate_pdf.await_args.args[0]
    assert summary_path.read_text(encoding="utf-8") == summary
    assert summary_path.parent != Path("reports")
    assert len(list(summary_path.parent.glob("*_report.md"))) == 1


async def test_invalid_or_empty_batches_do_not_create_report_directories(report_run):
    assert await multi_target.run_multi_target([]) == "No targets provided."
    with pytest.raises(ValueError, match="at most 10"):
        await multi_target.run_multi_target(["example.com"] * 11)
    assert not Path("reports").exists()
