# demo.tape
# Charmbracelet VHS — https://github.com/charmbracelet/vhs
# OpenOSINT demo: `openosint dns example.com` — no API key required.
# Run: vhs demo.tape  (or ./build.sh)
#
# FontFamily: "JetBrains Mono" does NOT resolve on this machine
# (`fc-match "JetBrains Mono"` -> Andale Mono) — that mismatch between the
# requested font's metrics and the substituted font's actual glyph advance
# is what caused the doubled letter-spacing in the first render. Menlo is
# a real system font (`fc-match Menlo` -> Menlo itself) with predictable
# monospace metrics: verified empirically at ~0.67x FontSize per column.
#
# Columns: the CLI hardcodes a 60-char divider (`"=" * 60`, cli.py:58) and
# does not read terminal width, so the terminal just needs to be >= 60
# cols for that divider to never wrap. FontSize/Padding below are picked
# to land at ~63 cols at Width 800 — enough margin that only the one
# genuinely-long data line (the 91-char SOA record) still wraps, which is
# real content wrapping, not an orphaned stub.

Output demo.gif

Set Shell "bash"
Set FontSize 18
Set FontFamily "Menlo"
Set Width 800
Set Height 700
Set Padding 14
Set Theme "Dracula"
Set TypingSpeed 45ms
Set WindowBar Colorful

# Clean-machine setup: minimal prompt, no local proxy config leaking into
# the recording, blank slate. Still a real shell, real command, real output.
Hide
Type "export PS1='❯ '"
Enter
Type "export OPENOSINT_PROXY_URL=''"
Enter
Type "clear"
Enter
Show

Sleep 400ms

Type "openosint dns example.com"
Enter

Sleep 5900ms
