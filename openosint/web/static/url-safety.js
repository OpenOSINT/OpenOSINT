/**
 * url-safety.js — validates a third-party-supplied URL before it is ever
 * used as a DOM href.
 *
 * Used by the globe pivot panel: GDELT's `html` property is a blurb
 * written by a worldwide, uncontrolled news feed, and the href pulled out
 * of it must never reach an anchor unchecked — a javascript:/data: URI
 * there would be a click-triggered XSS.
 *
 * Only http/https survive. Never rewrites or sanitizes — a URL is accepted
 * whole or rejected whole.
 */

/**
 * Returns raw unchanged if it parses as an absolute http(s) URL, else ''.
 * A protocol-relative URL (//host/path) is rejected too — new URL() with no
 * base argument only accepts absolute URLs, so //host throws just like a
 * malformed string does.
 */
export function safeHttpUrl(raw) {
  if (!raw) return '';
  try {
    const u = new URL(raw);
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : '';
  } catch {
    return '';
  }
}
