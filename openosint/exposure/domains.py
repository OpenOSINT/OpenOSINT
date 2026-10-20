"""Registrable domain (eTLD+1) from the bundled Public Suffix List snapshot.

No runtime fetch (suffix_list_urls=()) and no cache directory (cache_dir=None): nothing is
read from the network or written to disk.
"""

from __future__ import annotations

import tldextract


def _build() -> tldextract.TLDExtract:
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


_EXTRACT = _build()


def registrable_domain(host: str) -> str:
    """expired.badssl.com -> badssl.com; a.b.co.uk -> b.co.uk. ValueError if host has none."""
    result = _EXTRACT(host)
    if not result.domain or not result.suffix:
        raise ValueError(f"'{host}' has no registrable domain (no known public suffix).")
    return result.top_domain_under_public_suffix
