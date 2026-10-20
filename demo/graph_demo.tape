# demo/graph_demo.tape — graph module demo (~33s, deterministic)
#
# Regenerate: vhs demo/graph_demo.tape   (run from the repo root)
# Requires: vhs, ttyd, ffmpeg, and the project venv at .venv (with the
# `graph` + `graph-dedup` extras installed, and `ftm` on the venv's bin).
#
# SYNTHETIC DATA ONLY — see demo/seed_demo.py's docstring. Everything shown
# is fictional and the demo never touches the network. Timestamps, run ids,
# and the store path are frozen so every render produces identical frames.

Output demo/graph-demo.gif
Output demo/graph-demo.webm

Set Shell "bash"
Set FontSize 22
Set Width 1200
Set Height 760
Set Theme "Catppuccin Mocha"
Set Padding 24
Set TypingSpeed 35ms
Set Framerate 20

# --- hidden setup: venv on PATH, clean prompt, seed the throwaway store ---
Hide
Type `export PATH="$PWD/.venv/bin:$PATH" PS1='$ '`
Enter
Type "python demo/seed_demo.py seed"
Enter
Sleep 2s
Type "clear"
Enter
Sleep 500ms
Show
# --------------------------------------------------------------------------

Sleep 800ms

# Scene 1 — two identity entities, two datasets, provenance on every fact
Type "python demo/seed_demo.py entities"
Enter
Sleep 4s

# Scene 2 — crossref proposes same_as: score + feature explanation (hold long)
Type "python demo/seed_demo.py crossref"
Enter
Sleep 7s

# Scene 3 — review queue: still 'unsure', nothing auto-merged (hold long)
Type "python demo/seed_demo.py review"
Enter
Sleep 7s

# Scene 4 — a human accepts; canonical_for() now agrees
Type "python demo/seed_demo.py accept"
Enter
Sleep 4500ms

# Scene 5 — export valid FollowTheMoney data
Type "python demo/seed_demo.py export"
Enter
Sleep 2s
Type "ftm validate -i /tmp/osint-graph-demo/aurora.ftm -o /dev/null; echo exit=$?"
Enter
Sleep 3500ms
