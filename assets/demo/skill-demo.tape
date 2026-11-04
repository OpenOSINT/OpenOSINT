# skill-demo.tape: real Claude Code session showing the OpenOSINT plugin.
# Regenerate: see "Regenerating the plugin demo" in CONTRIBUTING.md.
#
# Uses your normal Claude Code login. Before recording, the plugin and the
# openosint marketplace must NOT be installed, other plugins that print notices
# should be disabled, and /tmp/openosint-demo/.claude/settings.local.json must
# pre-allow the openosint tools (see CONTRIBUTING.md). Raw output goes to /tmp.
# Everything with account info (banner, trust dialog) happens inside Hide;
# the leftover header is masked in post-processing.

Output "/tmp/openosint-demo-raw/raw.mp4"

Require claude
Require uvx

Set Shell "bash"
Set Width 1200
Set Height 700
Set FontSize 20
Set FontFamily "Menlo"
Set Padding 16
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set TypingSpeed 55ms
Set Framerate 15

Env TERM "xterm-256color"

# ---- private setup, never shown --------------------------------------------
Hide
Type "exec bash --noprofile --norc"
Enter
Type "export PS1='$ ' HISTFILE=/dev/null OPENOSINT_HOME=$(mktemp -d /tmp/oo-home.XXXXXX)"
Enter
# Inherited CLAUDE_CODE_* markers from a parent session print warnings.
Type "unset $(compgen -e | grep -E '^(CLAUDE|ANTHROPIC)')"
Enter
Type "export CLAUDE_CODE_NO_FLICKER=1 CLAUDE_CODE_HIDE_CWD=1"
Enter
Type "cd /tmp/openosint-demo && clear"
Enter
Type "claude"
Enter
# Trust dialog on first run in a folder; on later runs the prompt shows directly.
# Down+Enter is a no-op on an empty prompt.
Wait+Screen@60s /(Yes, I trust|Try ")/
Sleep 1s
Down
Enter
Wait+Screen@30s /auto mode on|shift\+tab/
Sleep 1s
Type "/clear"
Enter
Sleep 2s

# ---- visible part ------------------------------------------------------------
Show
Sleep 1s

# 1. add marketplace
Type "/plugin marketplace add OpenOSINT/OpenOSINT"
Enter
Wait+Screen@90s /Successfully added marketplace/
Sleep 1500ms

# 2. install plugin (scope picker defaults to user scope)
Type "/plugin install openosint@openosint"
Enter
Wait+Screen@90s /(user scope|Installing|Installed openosint)/
Sleep 1s
Enter
Wait+Screen@90s /Installed openosint/
Sleep 1500ms

# 3. run the skill
Type "/openosint:osint example.com"
Enter
Wait+Screen@360s /Leads to verify/

# let the last bullets stream; post-processing trims to the final frame + 3s hold
Sleep 15s
