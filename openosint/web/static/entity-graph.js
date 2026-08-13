/**
 * entity-graph.js — Entity normalizer registry.
 * Pure data in, pure data out. No DOM, no rendering.
 *
 * Node:  { id, type, label, data }
 *   id = "${type}:${value.toLowerCase()}" — stable dedupe key
 *   data.isRoot = true marks the target node (visual hint only, not a separate namespace)
 *
 * Edge:  { source, target, label }
 *
 * Entity types: email, username, domain, subdomain, ip, phone,
 *               org, social_account, breach, paste, asn
 *
 * Every extractor is wrapped in try/catch; any parse failure degrades
 * gracefully to a generic target-linked node (never throws).
 */

// ---------------------------------------------------------------------------
// Target-type inference
// ---------------------------------------------------------------------------

const _IPv4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const _IPv6_RE = /^[0-9a-f:]{4,}$/i;
const _DOMAIN_RE = /^[a-z0-9][a-z0-9\-._]*\.[a-z]{2,}$/i;
const _PHONE_RE = /^\+?\d[\d\s\-().]{6,}$/;

function _inferType(value) {
  const v = (value || '').trim();
  if (v.includes('@')) return 'email';
  if (_IPv4_RE.test(v)) return 'ip';
  if (_IPv6_RE.test(v) && v.includes(':')) return 'ip';
  if (_PHONE_RE.test(v) && !v.includes('.')) return 'phone';
  if (_DOMAIN_RE.test(v)) return 'domain';
  return 'username';
}

// ---------------------------------------------------------------------------
// Node / edge constructors
// ---------------------------------------------------------------------------

function _node(type, value, data = {}) {
  const v = String(value).trim();
  return { id: `${type}:${v.toLowerCase()}`, type, label: v, data };
}

function _edge(sourceId, targetId, label) {
  return { source: sourceId, target: targetId, label };
}

// ---------------------------------------------------------------------------
// Text parsing helpers
// ---------------------------------------------------------------------------

/** Extract the first value matching a prefixed line, e.g. "[+] Org: Google". */
function _val(text, prefixPattern) {
  const re = new RegExp(`${prefixPattern}\\s*(.+)$`, 'm');
  const m = re.exec(text);
  return m ? m[1].trim() : null;
}

/** Extract ALL values matching a prefixed line. */
function _vals(text, prefixPattern) {
  const re = new RegExp(`${prefixPattern}\\s*(.+)$`, 'gm');
  const results = [];
  let m;
  while ((m = re.exec(text)) !== null) results.push(m[1].trim());
  return results;
}

// ---------------------------------------------------------------------------
// Normalizer registry — one entry per tool
// Verbatim output samples are reproduced in tests/test_entity_graph.mjs.
// ---------------------------------------------------------------------------

const _REGISTRY = {

  /** search_ip output example:
   *   IP intelligence for '8.8.8.8':
   *   [+] Ip: 8.8.8.8
   *   [+] Hostname: dns.google
   *   [+] Org: AS15169 Google LLC
   *   [+] City: Mountain View
   *   [+] Country: US
   */
  search_ip(target, output) {
    const nodes = [], edges = [];
    const rootId = `ip:${target.toLowerCase().trim()}`;

    const org      = _val(output, '\\[\\+\\] Org:');
    const hostname = _val(output, '\\[\\+\\] Hostname:');

    if (org) {
      const n = _node('org', org, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'hosted by'));
    }
    if (hostname) {
      const n = _node('domain', hostname, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'hostname'));
    }
    return { nodes, edges };
  },

  /** search_whois output example:
   *   WHOIS results for 'example.com':
   *   [+] Domain: EXAMPLE.COM
   *   [+] Registrar: RESERVED-Internet Assigned Numbers Authority
   *   [+] Emails: abuse@iana.org
   *   [+] Org: Internet Assigned Numbers Authority
   *   [+] Name Servers: a.iana-servers.net, b.iana-servers.net
   */
  search_whois(target, output) {
    const nodes = [], edges = [];
    const rootId = `domain:${target.toLowerCase().trim()}`;

    const registrar = _val(output, '\\[\\+\\] Registrar:');
    const org       = _val(output, '\\[\\+\\] Org:');
    const emailRaw  = _val(output, '\\[\\+\\] Emails:');
    const nsRaw     = _val(output, '\\[\\+\\] Name Servers:');

    if (registrar) {
      const n = _node('org', registrar, { role: 'registrar' });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'registered by'));
    }
    if (org) {
      const n = _node('org', org, { role: 'registrant' });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'owned by'));
    }
    if (emailRaw) {
      emailRaw.split(',').forEach(e => {
        const em = e.trim();
        if (em.includes('@')) {
          const n = _node('email', em, {});
          nodes.push(n); edges.push(_edge(rootId, n.id, 'contact'));
        }
      });
    }
    if (nsRaw) {
      nsRaw.split(',').forEach(ns => {
        const d = ns.trim();
        if (d) {
          const n = _node('domain', d, { role: 'nameserver' });
          nodes.push(n); edges.push(_edge(rootId, n.id, 'ns'));
        }
      });
    }
    return { nodes, edges };
  },

  /** search_breach output example:
   *   Found in 2 breach(es) for 'test@example.com':
   *   [+] Adobe (2013-10-04) — leaked: Email addresses, Passwords, Usernames
   *   [+] LinkedIn (2012-05-05) — leaked: Email addresses, Passwords
   */
  search_breach(target, output) {
    const nodes = [], edges = [];
    const rootId = `email:${target.toLowerCase().trim()}`;
    const re = /^\[\+\] ([^\s(]+)\s*\(([^)]+)\)/gm;
    let m;
    while ((m = re.exec(output)) !== null) {
      const n = _node('breach', m[1], { date: m[2] });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'breached in'));
    }
    return { nodes, edges };
  },

  /** search_dns output example:
   *   [DNS] Domain: example.com
   *   [DNS] A: 93.184.216.34
   *   [DNS] MX records:
   *     • 0 mail.example.com.
   *   [DNS] NS: a.iana-servers.net, b.iana-servers.net
   */
  search_dns(target, output) {
    const nodes = [], edges = [];
    const rootId = `domain:${target.toLowerCase().trim()}`;

    const aRaw = _val(output, '\\[DNS\\] A:');
    if (aRaw) {
      aRaw.split(/[,\s]+/).forEach(ip => {
        ip = ip.trim();
        if (_IPv4_RE.test(ip)) {
          const n = _node('ip', ip, {});
          nodes.push(n); edges.push(_edge(rootId, n.id, 'resolves to'));
        }
      });
    }

    const lines = output.split('\n');
    let inMx = false;
    for (const line of lines) {
      if (line.includes('[DNS] MX records:')) { inMx = true; continue; }
      if (/^\[DNS\]/.test(line) || /^\[!]/.test(line)) {
        if (line.includes('[DNS] NS:')) {
          const nsRaw = line.replace(/.*\[DNS\] NS:/, '').trim();
          nsRaw.split(',').forEach(ns => {
            const d = ns.trim().replace(/\.$/, '');
            if (d) {
              const n = _node('domain', d, { role: 'ns' });
              nodes.push(n); edges.push(_edge(rootId, n.id, 'ns'));
            }
          });
        }
        inMx = false;
        continue;
      }
      if (inMx && line.trim().startsWith('•')) {
        const host = line.replace('•', '').trim().split(/\s+/).pop()?.replace(/\.$/, '');
        if (host && _DOMAIN_RE.test(host)) {
          const n = _node('domain', host, { role: 'mx' });
          nodes.push(n); edges.push(_edge(rootId, n.id, 'mail server'));
        }
      }
    }
    return { nodes, edges };
  },

  /** search_ip2location output example:
   *   [IP2Location] IP: 8.8.8.8
   *   [IP2Location] ISP: Google LLC
   *   [IP2Location] Domain: google.com
   *   [IP2Location] ASN: AS15169
   */
  search_ip2location(target, output) {
    const nodes = [], edges = [];
    const rootId = `ip:${target.toLowerCase().trim()}`;

    const isp    = _val(output, '\\[IP2Location\\] ISP:');
    const asn    = _val(output, '\\[IP2Location\\] ASN:');
    const domain = _val(output, '\\[IP2Location\\] Domain:');

    if (isp && isp !== 'N/A') {
      const n = _node('org', isp, { role: 'isp' });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'hosted by'));
    }
    if (asn && asn !== 'N/A') {
      const n = _node('asn', asn, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'belongs to'));
    }
    if (domain && domain !== 'N/A') {
      const n = _node('domain', domain, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'reverse domain'));
    }
    return { nodes, edges };
  },

  /** search_abuseipdb output example:
   *   [AbuseIPDB] IP: 8.8.8.8
   *   [AbuseIPDB] Abuse Confidence Score: 0%
   *   [AbuseIPDB] ISP: Google LLC
   *   [AbuseIPDB] Domain: google.com
   *   [AbuseIPDB] Country: US
   */
  search_abuseipdb(target, output) {
    const nodes = [], edges = [];
    const rootId = `ip:${target.toLowerCase().trim()}`;

    const isp    = _val(output, '\\[AbuseIPDB\\] ISP:');
    const domain = _val(output, '\\[AbuseIPDB\\] Domain:');
    const score  = _val(output, '\\[AbuseIPDB\\] Abuse Confidence Score:');

    if (isp && isp !== 'N/A') {
      const n = _node('org', isp, { role: 'isp' });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'hosted by'));
    }
    if (domain && domain !== 'N/A') {
      const n = _node('domain', domain, { abuseScore: score });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'reverse domain'));
    }
    return { nodes, edges };
  },

  /** search_shodan (host) output example:
   *   Shodan host data for '8.8.8.8':
   *   [+] IP: 8.8.8.8
   *   [+] Org: Google LLC
   *   [+] Hostnames: dns.google, 8888.google
   *   [+] Open ports: 53, 443
   *
   *   search_shodan (search) output example:
   *   Shodan search results for 'nginx' (1000 total, showing 3):
   *   [+] 1.2.3.4:80 — Acme Corp — United States
   */
  search_shodan(target, output) {
    const nodes = [], edges = [];
    const inferredType = _inferType(target);
    const rootId = `${inferredType}:${target.toLowerCase().trim()}`;

    const org = _val(output, '\\[\\+\\] Org:');
    if (org) {
      const n = _node('org', org, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'hosted by'));
    }
    const hostsRaw = _val(output, '\\[\\+\\] Hostnames:');
    if (hostsRaw) {
      hostsRaw.split(',').forEach(h => {
        h = h.trim();
        if (h) {
          const n = _node('domain', h, {});
          nodes.push(n); edges.push(_edge(rootId, n.id, 'hostname'));
        }
      });
    }

    // Search-result bullets: "[+] 1.2.3.4:80 — Org — Country"
    const searchRe = /^\[\+\] ([\d.]+):\d+ — (.+?) — .+$/gm;
    let m;
    while ((m = searchRe.exec(output)) !== null) {
      const ipNode = _node('ip', m[1], {});
      nodes.push(ipNode); edges.push(_edge(rootId, ipNode.id, 'found'));
      const orgName = m[2];
      if (orgName && orgName !== 'unknown') {
        const orgNode = _node('org', orgName, {});
        nodes.push(orgNode); edges.push(_edge(ipNode.id, orgNode.id, 'hosted by'));
      }
    }
    return { nodes, edges };
  },

  /** search_virustotal output example:
   *   [VirusTotal] Malicious: 2
   *   [VirusTotal] ASN: AS15169 Google LLC
   *   [VirusTotal] Country: US
   *   [VirusTotal] Registrar: MarkMonitor Inc.
   */
  search_virustotal(target, output) {
    const nodes = [], edges = [];
    const inferredType = _inferType(target);
    const rootId = `${inferredType}:${target.toLowerCase().trim()}`;

    const asn       = _val(output, '\\[VirusTotal\\] ASN:');
    const registrar = _val(output, '\\[VirusTotal\\] Registrar:');

    if (asn) {
      const n = _node('asn', asn, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'belongs to'));
    }
    if (registrar) {
      const n = _node('org', registrar, { role: 'registrar' });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'registered by'));
    }
    return { nodes, edges };
  },

  /** search_github output example (direct profile):
   *   [GitHub] Login: octocat
   *   [GitHub] Name: The Octocat
   *   [GitHub] Company: GitHub
   *   [GitHub] Email (profile): N/A
   *   [GitHub] Profile URL: https://github.com/octocat
   *   [GitHub] Emails found in commits: octocat@github.com
   *
   *   search_github output example (search results):
   *   [GitHub] Search results for 'johndoe' (2 match(es)):
   *     • johndoe — https://github.com/johndoe (type: User)
   */
  search_github(target, output) {
    const nodes = [], edges = [];
    const login   = _val(output, '\\[GitHub\\] Login:');
    const rootId  = `username:${(login || target).toLowerCase().trim()}`;

    const email        = _val(output, '\\[GitHub\\] Email \\(profile\\):');
    const company      = _val(output, '\\[GitHub\\] Company:');
    const profileUrl   = _val(output, '\\[GitHub\\] Profile URL:');
    const commitEmails = _val(output, '\\[GitHub\\] Emails found in commits:');

    if (profileUrl) {
      const n = _node('social_account', profileUrl, { platform: 'github', login: login || target });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'found on'));
    }
    if (email && email !== 'N/A') {
      const n = _node('email', email, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'email'));
    }
    if (company && company !== 'N/A') {
      const n = _node('org', company, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'works at'));
    }
    if (commitEmails) {
      commitEmails.split(',').forEach(e => {
        const em = e.trim();
        if (em.includes('@')) {
          const n = _node('email', em, { source: 'commit' });
          nodes.push(n); edges.push(_edge(rootId, n.id, 'commit email'));
        }
      });
    }
    // Search-result bullets: "  • johndoe — https://github.com/johndoe (type: User)"
    const searchRe = /•\s+(\S+)\s+—\s+(https?:\/\/\S+)/gm;
    let m;
    while ((m = searchRe.exec(output)) !== null) {
      const n = _node('social_account', m[2], { platform: 'github', login: m[1] });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'found on'));
    }
    return { nodes, edges };
  },

  /** search_censys output example (IP):
   *   [Censys] Type: ip
   *   [Censys] IP: 8.8.8.8
   *   [Censys] ASN: AS15169 GOOGLE
   *   [Censys] Country: US
   *
   *   search_censys output example (domain/cert):
   *   [Censys] Domain: example.com
   *   [Censys] Certificates Found: 3
   *   [Censys] SANs: example.com, www.example.com, api.example.com
   */
  search_censys(target, output) {
    const nodes = [], edges = [];
    const inferredType = _inferType(target);
    const rootId = `${inferredType}:${target.toLowerCase().trim()}`;

    const ip      = _val(output, '\\[Censys\\] IP:');
    const asn     = _val(output, '\\[Censys\\] ASN:');
    const sansRaw = _val(output, '\\[Censys\\] SANs:');

    if (ip && ip.toLowerCase() !== target.toLowerCase().trim()) {
      const n = _node('ip', ip, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'resolves to'));
    }
    if (asn) {
      const n = _node('asn', asn, {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'belongs to'));
    }
    if (sansRaw) {
      sansRaw.split(',').forEach(d => {
        d = d.trim();
        if (d && d.toLowerCase() !== target.toLowerCase().trim()) {
          const n = _node('domain', d, { role: 'san' });
          nodes.push(n); edges.push(_edge(rootId, n.id, 'certificate san'));
        }
      });
    }
    return { nodes, edges };
  },

  /** search_paste output example:
   *   Found in 2 paste(s) for 'test@example.com':
   *   [+] https://pastebin.com/abc12345 (2023-01-15)
   *   [+] https://pastebin.com/xyz98765 (2022-08-03)
   */
  search_paste(target, output) {
    const nodes = [], edges = [];
    const inferredType = _inferType(target);
    const rootId = `${inferredType}:${target.toLowerCase().trim()}`;

    const re = /^\[\+\] (https?:\/\/\S+)\s*\(([^)]+)\)/gm;
    let m;
    while ((m = re.exec(output)) !== null) {
      const n = _node('paste', m[1], { date: m[2] });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'found in'));
    }
    return { nodes, edges };
  },

  /** search_footprint output example:
   *   [Footprint] URL: https://twitter.com/johndoe
   *   [Footprint] Domain: twitter.com
   *   [Footprint] URL: https://linkedin.com/in/johndoe
   *   [Footprint] Domain: linkedin.com
   */
  search_footprint(target, output) {
    const nodes = [], edges = [];
    const inferredType = _inferType(target);
    const rootId = `${inferredType}:${target.toLowerCase().trim()}`;

    if (typeof output === 'object' && output !== null) {
      (output.discovered_urls || []).forEach(url => {
        const n = _node('social_account', url, { source: 'footprint' });
        nodes.push(n); edges.push(_edge(rootId, n.id, 'links to'));
      });
      (output.seen_domains || []).forEach(d => {
        const n = _node('domain', d, {});
        nodes.push(n); edges.push(_edge(rootId, n.id, 'found at'));
      });
    } else {
      _vals(output, '\\[Footprint\\] URL:').forEach(url => {
        const n = _node('social_account', url, { source: 'footprint' });
        nodes.push(n); edges.push(_edge(rootId, n.id, 'links to'));
      });
      _vals(output, '\\[Footprint\\] Domain:').forEach(d => {
        const n = _node('domain', d, {});
        nodes.push(n); edges.push(_edge(rootId, n.id, 'found at'));
      });
    }
    return { nodes, edges };
  },

  // ---- Type-B demo stubs (verbatim patterns from agent-loop.js _TYPE_B_DEMO) ----

  /** search_email Type-B demo stub:
   *   [DEMO DATA — install holehe: pip install holehe]
   *   [+] github.com     — demo@example.com registered (sample)
   *   [+] spotify.com    — demo@example.com registered (sample)
   *   [-] twitter.com    — not found (sample)
   */
  search_email(target, output) {
    const nodes = [], edges = [];
    const rootId = `email:${target.toLowerCase().trim()}`;
    const re = /^\[\+\] (\S+)\s+—\s+\S+\s+registered/gm;
    let m;
    while ((m = re.exec(output)) !== null) {
      const n = _node('social_account', m[1], { platform: m[1] });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'found on'));
    }
    return { nodes, edges };
  },

  /** search_username Type-B demo stub:
   *   [DEMO DATA — install sherlock: pip install sherlock-project]
   *   [+] GitHub         https://github.com/demouser (sample)
   *   [+] Reddit         https://reddit.com/u/demouser (sample)
   *   [-] Instagram      not found (sample)
   */
  search_username(target, output) {
    const nodes = [], edges = [];
    const rootId = `username:${target.toLowerCase().trim()}`;
    const re = /^\[\+\] (\S+)\s+(https?:\/\/\S+)\s+\(sample\)/gm;
    let m;
    while ((m = re.exec(output)) !== null) {
      const n = _node('social_account', m[2], { platform: m[1] });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'found on'));
    }
    return { nodes, edges };
  },

  /** search_domain Type-B demo stub:
   *   [DEMO DATA — install sublist3r: pip install sublist3r]
   *   [+] www.example.com     (sample subdomain)
   *   [+] mail.example.com    (sample subdomain)
   *   [+] api.example.com     (sample subdomain)
   */
  search_domain(target, output) {
    const nodes = [], edges = [];
    const rootId = `domain:${target.toLowerCase().trim()}`;
    const re = /^\[\+\] (\S+)\s+\(sample subdomain\)/gm;
    let m;
    while ((m = re.exec(output)) !== null) {
      const n = _node('subdomain', m[1], {});
      nodes.push(n); edges.push(_edge(rootId, n.id, 'subdomain'));
    }
    return { nodes, edges };
  },

  /** search_phone Type-B demo stub:
   *   [DEMO DATA — install phoneinfoga: github.com/sundowndev/phoneinfoga/releases]
   *   [+] Number:    +14155550100 (sample)
   *   [+] Country:   US
   *   [+] Carrier:   Sample Carrier LLC (sample)
   *   [+] Line type: mobile (sample)
   */
  search_phone(target, output) {
    const nodes = [], edges = [];
    const rootId = `phone:${target.toLowerCase().trim()}`;
    const carrier = _val(output, '\\[\\+\\] Carrier:');
    const country = _val(output, '\\[\\+\\] Country:');
    if (carrier) {
      const carrierClean = carrier.replace(/\s*\(sample\)\s*$/, '').trim();
      const n = _node('org', carrierClean, { role: 'carrier', country });
      nodes.push(n); edges.push(_edge(rootId, n.id, 'carrier'));
    }
    return { nodes, edges };
  },

  // Informational / dork tools produce no meaningful graph nodes
  generate_dorks()    { return { nodes: [], edges: [] }; },
  search_dorks_live() { return { nodes: [], edges: [] }; },
  scrape_url()        { return { nodes: [], edges: [] }; },
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function inferEntityType(value) {
  return _inferType(value);
}

/**
 * Build the root target node with the same id scheme as normalizers use,
 * so tools that rediscover the same entity merge into one node.
 * data.isRoot = true marks it visually — NOT a separate id namespace.
 */
export function makeTargetNode(target) {
  const v = (target || '').trim();
  const type = _inferType(v);
  return {
    id: `${type}:${v.toLowerCase()}`,
    type,
    label: v,
    data: { isRoot: true },
  };
}

/**
 * Extract graph nodes and edges from a tool result.
 * Never throws — any parse failure returns a single generic node linked to the target.
 */
export function extractEntities(toolName, target, output) {
  const inferredType = _inferType(target);
  const rootId = `${inferredType}:${(target || '').toLowerCase().trim()}`;

  const extractor = _REGISTRY[toolName];
  if (!extractor) {
    const n = _node('social_account', `${toolName}:${target}`, { tool: toolName });
    return { nodes: [n], edges: [_edge(rootId, n.id, 'found by ' + toolName)] };
  }

  try {
    const result = extractor(target, output || '');
    return {
      nodes: Array.isArray(result?.nodes) ? result.nodes : [],
      edges: Array.isArray(result?.edges) ? result.edges : [],
    };
  } catch {
    const n = _node('social_account', `${toolName}:${target}:error`, { tool: toolName, parseError: true });
    return { nodes: [n], edges: [_edge(rootId, n.id, 'found by ' + toolName)] };
  }
}
