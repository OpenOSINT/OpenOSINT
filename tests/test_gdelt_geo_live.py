"""Opt-in live check against the real GDELT file server.

Skipped by default (no live network in the normal suite). Run it with:

    OPENOSINT_LIVE=1 pytest tests/test_gdelt_geo_live.py -v
"""

from __future__ import annotations

import json
import os
import re

import pytest

from openosint.tools import gdelt_gkg as gkg
from openosint.tools import search_gdelt_geo as geo

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENOSINT_LIVE") != "1", reason="live network check; set OPENOSINT_LIVE=1"
)


async def test_live_newest_file_yields_geolocated_news(monkeypatch):
    # One file is enough for the check; don't make the real server serve the backfill too.
    monkeypatch.setattr(gkg.GkgWindow, "_ensure_backfill", lambda *_a: None)
    gkg.get_window().clear()
    try:
        result = await geo.run_gdelt_geo_osint("*", timespan=15)
    finally:
        gkg.get_window().clear()

    assert geo.SERVICE_UNAVAILABLE_MARKER not in result, result
    fc = json.loads(re.search(r"```geojson\n(.*?)```", result, re.DOTALL).group(1))
    assert len(fc["features"]) > 10
    sample = fc["features"][0]["properties"]
    assert sample["title"] and sample["url"].startswith(("http://", "https://"))
    assert fc["coverage"]["minutes"] == gkg.SLOT_MINUTES
