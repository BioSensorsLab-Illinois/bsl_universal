# CI Autofix Loop — bsl_universal

Adapted from the [MantisCamUnified L-AUTOFIX initiative](https://github.com/BioSensorsLab-Illinois/MantisCamUnified/tree/main/.agent/runs/binary-build-autofix).
Same Five Hard Rules, same iteration mechanic, with library-specific scope changes.

## Purpose / Big Picture

After this change, when the **CI** workflow (`.github/workflows/ci.yml`) fails for any reason on `main` (or on an autofix-PR), a Claude-Opus-4.7-drafted patch attempt lands within minutes — either as a new PR (first attempt) or as another commit on the existing autofix PR (continuation, up to 10 commits per failure). On exhaustion, a comment + `autofix-exhausted` label surfaces the PR for human review.

This is a library, not a binary app. The fix surface differs from MantisCamUnified:

- **always-included candidate files**: `.github/workflows/ci.yml`, `setup.py`, `setup.cfg`, `requirements.txt`, `bsl_universal/__init__.py`
- **forbidden scope additions**: `dist/`, `build/`, `bsl_universal.egg-info/`
- **system-prompt note**: do NOT touch `setup.py:version` — the CI auto-version-bump step manages it by querying PyPI.

## Channels (this repo)

| Channel | Trigger | Outcome on failure |
|---|---|---|
| L-CI | `ci.yml`: push to main + every PR + dispatch | Failure triggers L-AUTOFIX |
| L-AUTOFIX first-attempt | `workflow_run` on CI failure, branch = `main`/`master` | New PR `autofix/ci-<RUN_ID>` |
| L-AUTOFIX continuation | `workflow_run` on CI failure, branch = `autofix/*` | Push another commit to same PR; cap at MAX_ITERATIONS=10 |

The existing `ci.yml` already runs on every PR, so each autofix commit is naturally re-validated. No `should-run` gate needed for this repo (CI is fast enough — 42 light legs ~10-15 min total, mostly ubuntu).

## Progress

- [x] (2026-05-15) Initiative scaffolded.
- [x] (2026-05-15) `.github/workflows/auto-fix.yml` created.
- [x] (2026-05-15) `scripts/ci/claude_fix_attempt.py` created — adapted constants, library-flavored system prompt.
- [ ] Verify the helper script parses + workflow YAML parses (in this session).
- [ ] One-time activation by user:
  ```bash
  gh secret set ANTHROPIC_API_KEY --repo BioSensorsLab-Illinois/bsl_universal --body "$ANTHROPIC_API_KEY"
  gh api -X PUT /repos/BioSensorsLab-Illinois/bsl_universal/actions/permissions/workflow \
    -F can_approve_pull_request_reviews=true
  ```

## Decision Log

- **Decision**: No new smoke / lint workflow. The existing `ci.yml` already runs imports + compileall across the 42-leg matrix; that's the smoke test for this repo. Wrapping it in extra layers would be duplicate work.
  Date/Author: 2026-05-15 / Claude port session.

- **Decision**: No `should-run` gate on CI. The existing `pull_request:` trigger is unfiltered (every PR runs CI). Cost is acceptable because each leg is fast (~3-5 min, mostly ubuntu), unlike MantisCamUnified's 30-60min PyInstaller legs.
  Date/Author: 2026-05-15.

- **Decision**: `setup.py:version` is in the forbidden-edit list in the system prompt, not as a hard scope-freeze rule.
  Rationale: A scope-freeze rule would be black-or-white. A system-prompt instruction lets Claude reason about edge cases (e.g., if `version =` literally has a syntax error, Claude can still fix the syntax around it — just not the value).
  Date/Author: 2026-05-15.

- **Decision**: No `.agent/` workspace beyond this initiative folder.
  Rationale: The repo has an existing `Agent.md` at root that documents conventions. Replicating MantisCamUnified's full `.agent/{AGENT,SOP,PLANS}.md` infrastructure would be over-engineering for a single-purpose library.
  Date/Author: 2026-05-15.

## Plan of Work

### Files added

- `.github/workflows/auto-fix.yml` — workflow_run trigger on CI failure, mode detection, iteration cap, continuation mode.
- `scripts/ci/claude_fix_attempt.py` — helper script, library-flavored.
- `.agent/runs/ci-autofix-loop/{ExecPlan,Status}.md` — this initiative.

### Files NOT modified

- `.github/workflows/ci.yml` stays as-is. No `pull_request: paths-ignore`, no `should-run` gate. Cost is acceptable.

## Validation and Acceptance

- Helper script parses cleanly under Python 3.14.
- Workflow YAML parses cleanly.
- `python -c "import bsl_universal"` still works locally (no Python-side regression — these changes are pure CI infra).
- First real CI failure after merge should trigger the autofix workflow; user verifies the PR is opened against the correct base.
- After ≤10 iterations: either L3 green (PR ready for review) OR Claude returns NO_PATCH_AVAILABLE (loop ends silently) OR cap is hit (comment + `autofix-exhausted` label).

## Idempotence and Recovery

- The added files are pure additions — easy to revert by deleting them.
- The workflow only fires on `workflow_run` of `CI` with `conclusion == failure`, so it can't infinite-loop.
- Without `ANTHROPIC_API_KEY`, the workflow silently no-ops with a clear log line.

## Notes for Handoff

- Five Hard Rules live in both the helper's `SYSTEM_PROMPT` and the discipline pages of `MantisCamUnified/.agent/skills/release-fix-loop/SKILL.md`. If you change one, mirror the other.
- The auto-version-bump step in `ci.yml` (queries PyPI for the latest `2.x.x` and increments patch) is a load-bearing part of the publish flow. Claude is explicitly instructed in the system prompt NOT to touch the `version =` line.
- Forbidden-paths list (`dist/`, `build/`, `*.egg-info/`) keeps Claude from "fixing" the build by editing built artifacts.
- This repo runs on the same `ANTHROPIC_API_KEY` as MantisCamUnified — single key, three repos using it.
