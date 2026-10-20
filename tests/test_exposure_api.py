"""openosint.exposure.api is the supported library surface; every advertised name must import."""

import pytest

from openosint.exposure import api

EXPECTED = {
    "CHECK_NAMES", "DomainNotRegistered", "ExposureReport", "PASSIVE_CHECKS", "normalize_domain",
    "registrable_domain", "render_html", "run_exposure",
}


def test_all_is_the_documented_surface():
    assert set(api.__all__) == EXPECTED
    assert api.__doc__ and "supported library API" in api.__doc__


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_name_in_all_imports(name):
    namespace: dict = {}
    exec(f"from openosint.exposure.api import {name}", namespace)  # noqa: S102 - the import itself is under test
    assert namespace[name] is getattr(api, name)
