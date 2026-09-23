# HA Windows Bridge — agent workflow

## Source of truth

Current Git state, code, tests, and phase documentation are authoritative.

Claude-mem is historical context only. Use it to recover a specific missing
decision or finding. Do not load broad project history when current repository
evidence is sufficient.

## Discovery

Do not repeat repository-wide discovery when continuing known work.

Inspect only the files, tests, and documentation relevant to the current task.
Reuse previous verified findings and reports unless the affected code has changed.

Do not use exhaustive codebase-reading workflows unless the user explicitly
requests a full-codebase audit.

## Skills

Do not invoke `learn-codebase` merely because a session is new, resumed,
compacted, or has limited context.

Do not invoke `do` unless the user explicitly requests its multi-agent workflow.

Do not invoke `make-plan` for continuation of an already-defined phase or for a
small, well-scoped task. Use it only when affected areas, dependencies, or the
implementation strategy are genuinely unknown.

Do not invoke CCS Align for ordinary instruction or rules audits.

Use claude-mem only for specific missing historical context. If an observation
ID is already known, fetch only that observation instead of searching or loading
a broad timeline.

## Agents

Use at most one implementation subagent at a time unless independent parallel
work is explicitly justified.

Do not create subagents for routine Git operations, commits, pushes, simple file
reads, or checks that can be performed directly.

Do not restart implementation with a new agent merely because a session was
resumed or context was compacted.

## Validation

Prefer targeted tests while implementation is changing.

Do not repeatedly run the full repository quality gate after every small fix.
Run the full gate after targeted validation and independent review are clean, or
when a change invalidates previous full-gate evidence.

Reuse still-valid test and QA results. Re-run evidence only when affected code
changed or the previous result is no longer applicable.

A green targeted test set does not replace an independent review when the active
phase requires one.

## Continuation

After context compaction, usage-limit interruption, or session resume:

1. inspect current Git status and diff,
2. identify the exact interruption point,
3. continue from the existing work.

Do not restart discovery, planning, QA, or implementation from the beginning
unless current repository evidence shows that earlier conclusions are stale.

## Git

Before staging, inspect:

- `git status`
- `git diff --check`
- `git diff --stat`
- `git diff --name-status`

Do not use broad staging such as `git add -A` before reviewing the file list.

Do not stage, commit, push, reset, rewrite history, or start the next project
phase unless the user has explicitly authorized that action.

## Phase boundaries

Work only on the explicitly active modernization phase.

Do not expand into the next phase because adjacent code was discovered during
implementation or review.

Previous completed phases are stable baselines unless a regression in the
current phase proves that a change is required.
