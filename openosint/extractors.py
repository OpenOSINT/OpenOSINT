# openosint/extractors.py
"""
Tool output extractors — parse raw tool strings into Entity + Relationship objects.

Each extractor is a pure function:
    (raw_output: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]

All extractors are defensive: they return empty lists on unparseable input and
never raise exceptions to callers. The registry maps tool names to extractors.
"""

from __future__ import annotations

import re
from typing import Callable

from openosint.correlation import Entity, EntityType, Relationship, make_entity

ExtractorFn = Callable[[str | dict | list, Entity], tuple[list[Entity], list[Relationship]]]

# ---------------------------------------------------------------------------
# Shared regex patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_ASN_RE = re.compile(r"\bAS(\d+)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------


def _extract_github(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract emails, org, and profile URL from search_github output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        if "Emails found in commits:" in line:
            _, _, emails_part = line.partition("Emails found in commits:")
            for raw_email in emails_part.split(","):
                email = raw_email.strip()
                if _EMAIL_RE.fullmatch(email) and "noreply" not in email:
                    e = make_entity(EntityType.EMAIL, email, 0.85, "search_github")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "commit_email", "search_github", 0.85)
                    )
        elif line.startswith("[GitHub] Email (profile):"):
            _, _, email_raw = line.partition("[GitHub] Email (profile):")
            email = email_raw.strip()
            if email and _EMAIL_RE.fullmatch(email):
                e = make_entity(EntityType.EMAIL, email, 0.95, "search_github")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "profile_email", "search_github", 0.95)
                )
        elif line.startswith("[GitHub] Company:"):
            _, _, company = line.partition("[GitHub] Company:")
            company = company.strip().lstrip("@")
            if company and company.lower() not in ("none", "n/a", ""):
                e = make_entity(EntityType.ORG, company, 0.7, "search_github")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "member_of", "search_github", 0.7)
                )
        elif line.startswith("[GitHub] Profile URL:"):
            _, _, url = line.partition("[GitHub] Profile URL:")
            url = url.strip()
            if url.startswith("http"):
                e = make_entity(EntityType.URL, url, 0.95, "search_github")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "account_on", "search_github", 0.95)
                )

    return entities, relationships


def _extract_breach(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract breach names from search_breach output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    # Lines like: [+] BreachName (2020-01-01) — leaked: Emails, Passwords
    breach_re = re.compile(r"^\[+\]\s+(\S+)\s+\(")
    for line in raw.splitlines():
        m = breach_re.match(line)
        if m:
            breach_name = m.group(1)
            e = make_entity(EntityType.ORG, breach_name, 0.9, "search_breach")
            entities.append(e)
            relationships.append(
                Relationship(seed, e, "found_in_breach", "search_breach", 0.9)
            )

    return entities, relationships


def _extract_dns(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract IPs, nameservers, CNAME targets, and MX hosts from search_dns output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[DNS] A:"):
            _, _, rest = stripped.partition("[DNS] A:")
            for ip in rest.split(","):
                ip = ip.strip()
                if _IPV4_RE.fullmatch(ip):
                    e = make_entity(EntityType.IP, ip, 0.95, "search_dns")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "resolves_to", "search_dns", 0.95)
                    )

        elif stripped.startswith("[DNS] NS:"):
            _, _, rest = stripped.partition("[DNS] NS:")
            for ns in rest.split(","):
                ns = ns.strip().rstrip(".")
                if ns and "." in ns:
                    e = make_entity(EntityType.DOMAIN, ns, 0.9, "search_dns")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "nameserver", "search_dns", 0.9)
                    )

        elif stripped.startswith("[DNS] CNAME:"):
            _, _, rest = stripped.partition("[DNS] CNAME:")
            for cname in rest.split(","):
                cname = cname.strip().rstrip(".")
                if cname and "." in cname:
                    e = make_entity(EntityType.DOMAIN, cname, 0.85, "search_dns")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "cname_to", "search_dns", 0.85)
                    )

        elif stripped.startswith("• "):
            # MX record bullet: • 10 mail.example.com
            parts = stripped[2:].split()
            if parts:
                mx_host = parts[-1].rstrip(".")
                if "." in mx_host:
                    e = make_entity(EntityType.DOMAIN, mx_host, 0.9, "search_dns")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "mx_host", "search_dns", 0.9)
                    )

    return entities, relationships


def _extract_whois(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract registrant email, org, and nameservers from search_whois output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[+] Emails:"):
            _, _, rest = stripped.partition("[+] Emails:")
            for email in rest.split(","):
                email = email.strip()
                if _EMAIL_RE.fullmatch(email):
                    e = make_entity(EntityType.EMAIL, email, 0.9, "search_whois")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "registrant_email", "search_whois", 0.9)
                    )

        elif stripped.startswith("[+] Org:"):
            _, _, org = stripped.partition("[+] Org:")
            org = org.strip()
            if org and org.lower() not in ("none", "n/a", ""):
                e = make_entity(EntityType.ORG, org, 0.8, "search_whois")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "registrant_org", "search_whois", 0.8)
                )

        elif stripped.startswith("[+] Name Servers:"):
            _, _, rest = stripped.partition("[+] Name Servers:")
            for ns in rest.split(","):
                ns = ns.strip().lower().rstrip(".")
                if ns and "." in ns:
                    e = make_entity(EntityType.DOMAIN, ns, 0.85, "search_whois")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "nameserver", "search_whois", 0.85)
                    )

    return entities, relationships


def _extract_username(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract platform URLs from sherlock output (search_username)."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    # Sherlock --print-found: [+] PlatformName: https://...
    line_re = re.compile(r"^\[.*?\]\s+\S+[:\s]+(https?://\S+)")
    for line in raw.splitlines():
        m = line_re.match(line)
        if m:
            url = m.group(1).rstrip(".,;")
            e = make_entity(EntityType.URL, url, 0.8, "search_username")
            entities.append(e)
            relationships.append(
                Relationship(seed, e, "account_on", "search_username", 0.8)
            )

    return entities, relationships


def _extract_email(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract registered platform accounts from holehe output (search_email).

    Holehe prints [+] platform when the email is registered there.
    We create URL entities for the found platforms.
    """
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    # Holehe lines: [+] twitter.com  or  [+] twitter
    found_re = re.compile(r"^\[\+\]\s+(\S+)")
    for line in raw.splitlines():
        m = found_re.match(line.strip())
        if m:
            platform = m.group(1).rstrip(":")
            host = platform if "." in platform else f"{platform}.com"
            url = f"https://{host}"
            e = make_entity(EntityType.URL, url, 0.75, "search_email")
            entities.append(e)
            relationships.append(
                Relationship(seed, e, "registered_at", "search_email", 0.75)
            )

    return entities, relationships


def _extract_domain(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract subdomain entities from search_domain (sublist3r) output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[+] "):
            sub = stripped[4:].strip()
            if "." in sub and not sub.startswith("http"):
                e = make_entity(EntityType.DOMAIN, sub, 0.85, "search_domain")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "subdomain_of", "search_domain", 0.85)
                )

    return entities, relationships


def _extract_ip(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract org, ASN, and hostname from search_ip (ipinfo.io) output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[+] Org:"):
            _, _, org = stripped.partition("[+] Org:")
            org = org.strip()
            if org:
                org_name = re.sub(r"^AS\d+\s+", "", org).strip()
                if org_name:
                    e = make_entity(EntityType.ORG, org_name, 0.75, "search_ip")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "hosted_at", "search_ip", 0.75)
                    )
                asn_m = _ASN_RE.search(org)
                if asn_m:
                    e_asn = make_entity(
                        EntityType.ASN, f"AS{asn_m.group(1)}", 0.9, "search_ip"
                    )
                    entities.append(e_asn)
                    relationships.append(
                        Relationship(seed, e_asn, "belongs_to_asn", "search_ip", 0.9)
                    )

        elif stripped.startswith("[+] Hostname:"):
            _, _, hostname = stripped.partition("[+] Hostname:")
            hostname = hostname.strip()
            if hostname and "." in hostname:
                e = make_entity(EntityType.DOMAIN, hostname, 0.8, "search_ip")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "reverse_dns", "search_ip", 0.8)
                )

    return entities, relationships


def _extract_shodan(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract org and hostnames from search_shodan output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[+] Org:"):
            _, _, org = stripped.partition("[+] Org:")
            org = org.strip()
            if org and org.lower() not in ("none", ""):
                e = make_entity(EntityType.ORG, org, 0.8, "search_shodan")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "hosted_at", "search_shodan", 0.8)
                )

        elif stripped.startswith("[+] Hostnames:"):
            _, _, rest = stripped.partition("[+] Hostnames:")
            for h in rest.split(","):
                hostname = h.strip()
                if hostname and "." in hostname:
                    e = make_entity(EntityType.DOMAIN, hostname, 0.8, "search_shodan")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "hostname", "search_shodan", 0.8)
                    )

    return entities, relationships


def _extract_ip2location(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract ASN and ISP from search_ip2location output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[IP2Location] ASN:"):
            _, _, asn = stripped.partition("[IP2Location] ASN:")
            asn = asn.strip()
            if asn:
                e = make_entity(EntityType.ASN, asn, 0.9, "search_ip2location")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "belongs_to_asn", "search_ip2location", 0.9)
                )

        elif stripped.startswith("[IP2Location] ISP:"):
            _, _, isp = stripped.partition("[IP2Location] ISP:")
            isp = isp.strip()
            if isp and isp.lower() not in ("none", ""):
                e = make_entity(EntityType.ORG, isp, 0.75, "search_ip2location")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "hosted_at", "search_ip2location", 0.75)
                )

    return entities, relationships


def _extract_virustotal(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract ASN and network owner from search_virustotal (metadata, no nav pivot)."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[VirusTotal] ASN:"):
            _, _, asn_part = stripped.partition("[VirusTotal] ASN:")
            asn_m = re.match(r"(AS\d+)\s*(.*)", asn_part.strip(), re.IGNORECASE)
            if asn_m:
                e_asn = make_entity(
                    EntityType.ASN, asn_m.group(1).upper(), 0.9, "search_virustotal"
                )
                entities.append(e_asn)
                relationships.append(
                    Relationship(seed, e_asn, "belongs_to_asn", "search_virustotal", 0.9)
                )
                org_name = asn_m.group(2).strip()
                if org_name:
                    e_org = make_entity(EntityType.ORG, org_name, 0.75, "search_virustotal")
                    entities.append(e_org)
                    relationships.append(
                        Relationship(seed, e_org, "hosted_at", "search_virustotal", 0.75)
                    )

    return entities, relationships


def _extract_abuseipdb(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract ISP from search_abuseipdb (metadata only, no new navigation pivot)."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[AbuseIPDB] ISP:"):
            _, _, isp = stripped.partition("[AbuseIPDB] ISP:")
            isp = isp.strip()
            if isp and isp.lower() not in ("none", ""):
                e = make_entity(EntityType.ORG, isp, 0.7, "search_abuseipdb")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "hosted_at", "search_abuseipdb", 0.7)
                )

    return entities, relationships


def _extract_footprint(raw: str | dict | list, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract URL and domain entities from search_footprint output."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    seen_domains: set[str] = set()

    if isinstance(raw, dict):
        for url in raw.get("discovered_urls", []):
            if url.startswith("http"):
                e = make_entity(EntityType.URL, url, 0.75, "search_footprint")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "found_via_serp", "search_footprint", 0.75)
                )
        for domain in raw.get("seen_domains", []):
            if domain and "." in domain and domain not in seen_domains:
                seen_domains.add(domain)
                e = make_entity(EntityType.DOMAIN, domain, 0.7, "search_footprint")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "footprint_on", "search_footprint", 0.7)
                )
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[Footprint] URL:"):
            _, _, url = stripped.partition("[Footprint] URL:")
            url = url.strip()
            if url.startswith("http"):
                e = make_entity(EntityType.URL, url, 0.75, "search_footprint")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "found_via_serp", "search_footprint", 0.75)
                )

        elif stripped.startswith("[Footprint] Domain:"):
            _, _, domain = stripped.partition("[Footprint] Domain:")
            domain = domain.strip()
            if domain and "." in domain and domain not in seen_domains:
                seen_domains.add(domain)
                e = make_entity(EntityType.DOMAIN, domain, 0.7, "search_footprint")
                entities.append(e)
                relationships.append(
                    Relationship(seed, e, "footprint_on", "search_footprint", 0.7)
                )

    return entities, relationships


def _extract_censys(raw: str, seed: Entity) -> tuple[list[Entity], list[Relationship]]:
    """Extract domain entities from Censys certificate SANs — high-value pivot source."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    if not raw:
        return entities, relationships

    for line in raw.splitlines():
        stripped = line.strip()

        if stripped.startswith("[Censys] SANs:"):
            _, _, sans_part = stripped.partition("[Censys] SANs:")
            for san in sans_part.split(","):
                san = san.strip().lstrip("*.")
                if san and "." in san and not san.startswith("http"):
                    e = make_entity(EntityType.DOMAIN, san, 0.85, "search_censys")
                    entities.append(e)
                    relationships.append(
                        Relationship(seed, e, "certificate_san", "search_censys", 0.85)
                    )

    return entities, relationships


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EXTRACTOR_REGISTRY: dict[str, ExtractorFn] = {
    "search_github": _extract_github,
    "search_breach": _extract_breach,
    "search_dns": _extract_dns,
    "search_whois": _extract_whois,
    "search_username": _extract_username,
    "search_email": _extract_email,
    "search_domain": _extract_domain,
    "search_ip": _extract_ip,
    "search_shodan": _extract_shodan,
    "search_ip2location": _extract_ip2location,
    "search_virustotal": _extract_virustotal,
    "search_abuseipdb": _extract_abuseipdb,
    "search_censys": _extract_censys,
    "search_footprint": _extract_footprint,
}
