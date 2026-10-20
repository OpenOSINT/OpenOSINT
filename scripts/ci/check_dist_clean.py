"""Fail if a built wheel or sdist contains bytecode (.pyc/.pyo or __pycache__)."""

import sys
import tarfile
import zipfile
from pathlib import Path


def is_bytecode(name: str) -> bool:
    return "__pycache__" in name or name.endswith((".pyc", ".pyo"))


def offenders(dist_dir: Path) -> list[str]:
    found = []
    for wheel in dist_dir.glob("*.whl"):
        found += [f"{wheel.name}: {n}" for n in zipfile.ZipFile(wheel).namelist() if is_bytecode(n)]
    for sdist in dist_dir.glob("*.tar.gz"):
        with tarfile.open(sdist) as tar:
            found += [f"{sdist.name}: {n}" for n in tar.getnames() if is_bytecode(n)]
    return found


if __name__ == "__main__":
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    if not any(dist.glob("*.whl")) or not any(dist.glob("*.tar.gz")):
        sys.exit(f"FAIL: expected a wheel and an sdist in {dist}/")
    bad = offenders(dist)
    if bad:
        sys.exit("FAIL: bytecode in built distributions:\n  " + "\n  ".join(bad))
    print("ok  no bytecode in wheel or sdist")
