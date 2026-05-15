# Status — CI Autofix Loop (bsl_universal)

## Current Branch

- `main`

## Current Focus

- Port the MantisCamUnified L-AUTOFIX iteration loop to this repo. Failing `CI` workflow → Claude-Opus-4.7 patch attempt → autofix PR (first attempt) or another commit on the existing PR (continuation, capped at 10).

## Progress

- [x] (2026-05-15) Initiative scaffolded (ExecPlan + Status).
- [x] (2026-05-15) `.github/workflows/auto-fix.yml` created.
- [x] (2026-05-15) `scripts/ci/claude_fix_attempt.py` created (adapted for Python-library context, not PyInstaller).
- [ ] Helper script + workflow parse-checks (in this session).
- [ ] Activation (user): set `ANTHROPIC_API_KEY` secret + enable PR-create toggle.

## Blockers

- **One-time activation by user** (gh CLI, no UI):
  ```bash
  # Set ANTHROPIC_API_KEY secret
  gh secret set ANTHROPIC_API_KEY \
    --repo BioSensorsLab-Illinois/bsl_universal \
    --body "$ANTHROPIC_API_KEY"

  # Allow GitHub Actions to create + approve PRs
  gh api -X PUT \
    /repos/BioSensorsLab-Illinois/bsl_universal/actions/permissions/workflow \
    -F can_approve_pull_request_reviews=true
  ```

## Known Checks Still Required

- After merge: first real CI failure should trigger `auto-fix.yml`. Verify:
  1. The autofix workflow fires (look in Actions tab).
  2. With API key + PR toggle set, an `[autofix]` PR opens against `main`.
  3. The PR's own CI runs (existing `ci.yml` `pull_request:` trigger). On failure, autofix fires again in continuation mode.
- No regression to the existing 42-leg matrix or PyPI publish flow.

## Next Steps

1. Verify workflow YAML + helper script parse cleanly (in this session).
2. Commit + push from this `main` branch.
3. (User, when ready) Run the `gh` commands above to activate.

## Uncommitted Files

- `.github/workflows/auto-fix.yml`
- `scripts/ci/claude_fix_attempt.py`
- `.agent/runs/ci-autofix-loop/ExecPlan.md`
- `.agent/runs/ci-autofix-loop/Status.md`

## Notes for Handoff

- Five Hard Rules are encoded in the helper's `SYSTEM_PROMPT`. They mirror the MantisCamUnified release-fix-loop skill.
- `setup.py:version` is explicitly excluded from autofix edits — the CI auto-version-bump step (queries PyPI) owns versioning.
- Forbidden-path list includes `dist/`, `build/`, `bsl_universal.egg-info/` — prevents Claude from editing built artifacts.
- This repo and MantisCamUnified (and the upcoming MantisAnalysis + MantisSpectrometer rollouts) share one `ANTHROPIC_API_KEY` configured per-repo via `gh secret set`.
- If/when a Tier 4 or stricter smoke layer is added to this repo, update the system prompt's "Common failure modes" section accordingly.
