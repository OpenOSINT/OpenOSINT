# Vendored: Tailwind CSS (prebuilt)

This directory holds a **prebuilt, offline** Tailwind CSS file. OpenOSINT is
an OSINT tool: it must run fully offline and must never announce its own
execution to a third party (a CDN request would). This also replaces
`cdn.tailwindcss.com`, which is the browser JIT build that Tailwind itself
documents as not for production. Nothing here is fetched at runtime — the
browser loads only this local file.

| Asset | Version | Source | License |
|---|---|---|---|
| `tailwind.css` | 3.4.17 | Generated with the Tailwind standalone CLI (see below) | MIT (`LICENSE.txt`) |

The file contains preflight (base reset) plus only the utility classes
actually used in `openosint/web/index.html`, minified (~12 KB).

## Regenerating

No Node toolchain is required — the standalone CLI is a single self-contained
binary, downloaded ad hoc and **not** committed to the repo:

```bash
# from the repo root; pick the binary for your platform from
# https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64
printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n' > /tmp/tw-input.css
./tailwindcss-macos-arm64 -i /tmp/tw-input.css \
  -o openosint/web/static/vendor/tailwindcss/tailwind.css \
  --content "openosint/web/index.html" --minify
rm tailwindcss-macos-arm64
```

**Regenerate whenever a new Tailwind utility class is added to `index.html`** —
the build only includes classes present in the file at build time. Classes
constructed dynamically in JS (string concatenation) are not detected; keep
class names literal in the HTML.
