"""SSRF guard for the checks that connect to the target (TLS, HTTP headers); opt-in via public_only.

Resolve the host once, refuse it when ANY answer is not a public address, and hand the caller the
first vetted IP to connect to, so a second (rebound) DNS answer is never used.
"""

from __future__ import annotations

import ipaddress
import socket

from openosint.exposure.models import CheckSkipped

REFUSED_MESSAGE = "target resolves to a non-public address"

# Explicit list on top of ipaddress.is_global, so the intent is readable and testable.
_BLOCKED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",  # "this network"
        "10.0.0.0/8",
        "100.64.0.0/10",  # CGNAT
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local, incl. cloud metadata 169.254.169.254
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved, incl. broadcast
        "::/128",
        "::1/128",
        "100::/64",  # discard-only
        "2001::/32",  # Teredo
        "2001:db8::/32",
        "2002::/16",  # 6to4: embeds an arbitrary IPv4
        "64:ff9b::/96",  # NAT64: embeds an arbitrary IPv4
        "fc00::/7",  # unique local
        "fe80::/10",  # link-local
        "ff00::/8",  # multicast
    )
)

# Overridable in tests; the only resolver call the guard makes.
_getaddrinfo = socket.getaddrinfo


class NonPublicTarget(CheckSkipped):
    """The host resolves to at least one non-public address; reported as a skipped check."""

    def __init__(self) -> None:
        super().__init__(REFUSED_MESSAGE, "non_public_target")


class RedirectBlocked(CheckSkipped):
    """A redirect left HTTPS on port 443; reported as a skipped check."""

    def __init__(self, message: str = "redirect is not https on port 443") -> None:
        super().__init__(message, "redirect_blocked")


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])  # drop an IPv6 zone id
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not any(ip in net for net in _BLOCKED)


def pin(host: str, port: int = 443) -> str:
    """The first public address of `host` (IPv4 first); NonPublicTarget if any answer is non-public.

    socket.gaierror propagates, as it does without the guard.
    """
    infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or not all(is_public(a) for a in addresses):
        raise NonPublicTarget
    # TODO: only the first address is tried (no fallback to the others); Heroku has no IPv6 egress, so IPv4 first.
    return sorted(addresses, key=lambda a: ":" in a.split("%")[0])[0]
