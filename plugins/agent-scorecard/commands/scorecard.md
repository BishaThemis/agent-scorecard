---
description: Show the subagent scorecard (pass "dashboard" to open the desktop dashboard)
argument-hint: "[dashboard] [--lang en|tr]"
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/scripts/scorecard_cli.py" $ARGUMENTS`

Show the output above to the user exactly as it is. Do not add comments, summaries or analysis.
