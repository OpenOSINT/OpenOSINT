/**
 * Test-only ESM loader hook: rewrites the browser-root-relative "/static/..."
 * imports used throughout openosint/web/static/*.js (they're served from
 * the app's web root, not meant to be filesystem-relative) to real paths
 * under openosint/web/static/, so these modules can be `import`ed directly
 * by Node in tests without changing their source.
 */
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const STATIC_DIR = path.resolve(import.meta.dirname, '..', 'openosint', 'web', 'static');

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('/static/')) {
    const real = path.join(STATIC_DIR, specifier.slice('/static/'.length));
    return nextResolve(pathToFileURL(real).href, context);
  }
  return nextResolve(specifier, context);
}
