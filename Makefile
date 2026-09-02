.PHONY: demo demo-check demo-globe demo-globe-check

# Record and encode the OpenOSINT web graph demo.
#
# Prerequisites:
#   - node (https://nodejs.org)
#   - ffmpeg  (brew install ffmpeg)
#   - gifski  (brew install gifski)
#   - Web server running: openosint --web  (default http://localhost:8080)
#   - OPENOSINT_DEMO_KEY env var set to your Anthropic API key
#
# Usage:
#   export OPENOSINT_DEMO_KEY=sk-ant-...
#   make demo
#
# See scripts/record-demo/README.md for full operator instructions.

demo: demo-check
	node scripts/record-demo/record.mjs
	bash scripts/record-demo/encode.sh

demo-check:
	@command -v node   >/dev/null 2>&1 || (echo "ERROR: node not found — install from https://nodejs.org"; exit 1)
	@command -v ffmpeg >/dev/null 2>&1 || (echo "ERROR: ffmpeg not found — brew install ffmpeg"; exit 1)
	@command -v gifski >/dev/null 2>&1 || (echo "ERROR: gifski not found — brew install gifski"; exit 1)
	@[ -n "$$OPENOSINT_DEMO_KEY" ] || (echo "ERROR: OPENOSINT_DEMO_KEY is not set"; exit 1)
	@cd scripts/record-demo && npm install --silent
	@cd scripts/record-demo && npx playwright install chromium --quiet 2>&1 | grep -v "Downloading\|[0-9]%" || true
	@echo "[ok] All prerequisites satisfied"

# Record and encode the OpenOSINT GLOBE view demo.
#
# Prerequisites: node, ffmpeg, gifski, gifsicle; web server running
# (openosint web --port 8080, localhost only); OPENOSINT_DEMO_KEY set.
#
# Usage:
#   export OPENOSINT_DEMO_KEY=sk-ant-...
#   make demo-globe

demo-globe: demo-globe-check
	node scripts/record-demo/record-globe.mjs
	bash scripts/record-demo/encode-globe.sh

demo-globe-check:
	@command -v node     >/dev/null 2>&1 || (echo "ERROR: node not found — install from https://nodejs.org"; exit 1)
	@command -v ffmpeg   >/dev/null 2>&1 || (echo "ERROR: ffmpeg not found — brew install ffmpeg"; exit 1)
	@command -v gifski   >/dev/null 2>&1 || (echo "ERROR: gifski not found — brew install gifski"; exit 1)
	@command -v gifsicle >/dev/null 2>&1 || (echo "ERROR: gifsicle not found — brew install gifsicle"; exit 1)
	@[ -n "$$OPENOSINT_DEMO_KEY" ] || (echo "ERROR: OPENOSINT_DEMO_KEY is not set"; exit 1)
	@cd scripts/record-demo && npm install --silent
	@cd scripts/record-demo && npx playwright install chromium --quiet 2>&1 | grep -v "Downloading\|[0-9]%" || true
	@echo "[ok] All prerequisites satisfied"
