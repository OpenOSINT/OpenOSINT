# openosint/graph/dedup_guard.py
"""
The Python-version check for openosint.graph.dedup, kept OUTSIDE that package.

WHY a separate module instead of inline in dedup/__init__.py: importing any
name from a package always runs that package's __init__.py first — so a
version check for "should openosint.graph.dedup even be importable" cannot
live inside dedup/__init__.py and still be independently testable, because
testing it would mean importing the very package the test is trying to
verify is blocked. Living here, this module has no nomenklatura dependency
and works on any Python version (3.10 included), so tests can call
check_python_version() directly with an injected version tuple instead of
monkeypatching sys.version_info and reloading modules.
"""

from __future__ import annotations

MIN_PYTHON = (3, 11)


def check_python_version(version_info: tuple[int, int]) -> None:
    """Raise ImportError with a clear, actionable message if *version_info* is too old.

    Parameters
    ----------
    version_info:
        (major, minor) — pass sys.version_info[:2] in production; tests pass
        an arbitrary tuple to exercise both branches without touching the
        real interpreter version.
    """
    if version_info < MIN_PYTHON:
        raise ImportError(
            f"openosint.graph.dedup requires Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
            "(nomenklatura's own requirement, not an OpenOSINT choice) — this interpreter "
            f"is Python {version_info[0]}.{version_info[1]}. Phases 1-2 of openosint.graph "
            "(mapping, provenance, the SQLite store) work fine on Python 3.10+; only "
            "same_as cross-referencing needs 3.11+. Install the extra under a 3.11+ "
            "interpreter: pip install 'openosint[graph-dedup]'."
        )
