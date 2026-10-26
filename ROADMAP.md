# Roadmap

This document covers what comes after v0.1: which requested features the current data really supports,
and the order to build them in. None of the steps require LLM calls.

## A basic fact first

Scores do not change agent behavior on their own. Subagents do not learn between sessions and never see
their scores. A reward system can only have an effect through three channels:

1. **Routing:** the orchestrating agent picks which agent gets which task based on track record, using a short summary added to its context at session start.
2. **Feedback:** a subagent gets a short note about its own recurring problems when it starts, for example "your last 5 reports claimed done without evidence; include the test result."
3. **Human changes:** agent definitions (`.claude/agents/*.md`) are edited based on what the dashboard shows.

Channels 1 and 2 add a few hundred tokens to the context. That is not an extra LLM call, but it is not free
either. The experiment in phase 3 exists to measure whether it pays for itself.

## What the infrastructure provides

| Available (verified) | Not available, or only partly |
|---|---|
| Real per-message API `usage` for each subagent: input, output, 5-min and 1-hour cache writes, cache reads | Tokens the orchestrator spends on a subagent (writing the prompt, reading the result). Could be approximated from the parent transcript |
| Every tool call's input, result, error flag and time | The agent's intent and the task's scope, beyond what the prompt and markers say |
| Agent type, description, model, finished flag (`meta.json`), final report (`SubagentHandback`) | Real acceptance criteria, unless given with `ACCEPT-*` markers or a user vote |
| `SubagentStart`, `SubagentStop` and `SessionStart` hooks | Transcripts are deleted after `cleanupPeriodDays`; measurements survive, re-parsing does not |
| Old and new text of Edit/Write calls (useful for detecting weakened tests) | Sessions on other machines or in the cloud |
| | The transcript format is not a public API and can change |
| **To verify:** whether `SubagentStart` can add context to a subagent, and whether `PreToolUse` can change the Agent tool's input. Will be tested before phase 3 starts | The database is a local file. It cannot be made undeletable, only tamper-evident |

## Planned work

### Phase 1: trustworthy records and profiles

Everything later depends on this.

1. **Append-only history:** votes and corrections go into an append-only event log where each entry carries a hash of the previous one. Nothing is ever deleted by the app, and a broken chain is flagged in the dashboard. Each score also stores a hash of the rules file and the list of reference tasks it used.
2. **Agent profiles:** completed and failed tasks, success rate, points gained and lost, tokens and cost, average duration, tools used, error history, strongest categories, and the trend over time.
3. **Levels:** Novice → Apprentice → Expert → Master → Elite → Legend, based on accumulated points kept separate from per-task scores. Levels are display only and never feed back into scoring; a test enforces that.
4. **Dashboard basics:** filters by state (running, pending, done, failed), daily and weekly summaries, CSV/JSON export.
5. **Total cost per task:** sums every agent and retry under one `TASK-ID`. Without a TASK-ID, grouping by session + agent + description is marked as approximate.

### Phase 2: fair comparison and waste detection

6. **Comparison view:** agents compared only within the same category and difficulty, with Wilson confidence intervals for success rates and a clear "not enough data" state. Duration and tool count also get similar-task references.
7. **Test-weakening detection:** looks for added `skip`, `xfail` or `.only`, removed `assert`/`expect` lines, and deleted test files in Edit/Write diffs. If found, success is not accepted and the task is flagged.
8. **More waste detectors, each classified as certain or suspected:**
    - Agents duplicating each other: identical reads with identical output in overlapping agents of one session count as certain.
    - Work after completion: read-only calls after the last passing check.
    - The same command family failing repeatedly.

    Suspected cases are shown but never penalized.
9. **Charts, notifications and settings:** token and cost charts (tkinter canvas, no extra packages), tray notifications for failed tasks while the dashboard is open, and a settings screen for thresholds and prices. Settings changes are logged and trigger a rescore.

### Phase 3: proving the effect, then routing

10. **Hook check:** confirm the `SubagentStart` context and `PreToolUse` input-change hooks in the current Claude Code version.
11. **Experiment mode:**
    - Each session is assigned deterministically, from a hash of its ID, to *control* (measure only) or *active* (routing summary and feedback are added). The mode is stored with every task.
    - Comparing calendar weeks would mix different kinds of work; random assignment avoids that.
    - Results are compared within category + difficulty: tokens per successful task, total cost per task (including the added context), success rate, test pass rate, duration, repeated errors and redundant calls.
    - A token saving only counts if quality does not drop below the control group's confidence interval.
    - With too few tasks, the result is reported as inconclusive.
    - If the result is negative, the active mode is turned off and the scoring rules are simplified.
12. **Optional automatic routing,** only if the experiment shows a real benefit, and opt-in.
