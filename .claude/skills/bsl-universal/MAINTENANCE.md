# MAINTENANCE — keeping the bsl-universal skill in sync with the code

This skill is the agent-facing source of truth for driving bsl_universal hardware. If it
drifts from the code, an agent will issue a wrong command to a real instrument. The repo
therefore **enforces** that any AI-driven change to the library is followed by a skill update.

## How enforcement works
- **Manifest:** `.api_manifest.json` holds a sha256 fingerprint of every tracked
  first-party source file (drivers, core runtime, factory/registry, interfaces, headers,
  analysis). The vendored Thorlabs APT stack, the monitor GUI, and `test.py` are excluded.
- **Stop hook** (`scripts/hook_stop_sync.py`, registered in `.claude/settings.json`): when an
  agent tries to end its turn, it recomputes the fingerprint. If it differs from the manifest,
  it returns `{"decision":"block", ...}` and the agent cannot stop until the skill is updated
  and the manifest re-blessed. (It honors `stop_hook_active` to avoid infinite loops.)
- **PostToolUse hook** (`scripts/hook_posttool_notice.py`): an early, non-blocking nudge the
  moment a tracked source file is edited.

## What to do when you (an AI agent) change library code

1. **Re-audit the change.** Apply the audit lens in [`AUDIT.md`](AUDIT.md) to the code you
   touched (and anything it calls): wrong SCPI/units/ranges, missing readback on a
   state-changing command, missing `None` checks on transport handles, sentinel values that
   collide with real readings, `ZeroDivision`/`avg<=0`, non-idempotent `close()`, off-by-one
   in wavelength/position/channel math. Fix or explicitly note anything you find.

2. **Update the reference docs** under `reference/` for every instrument/topic whose public
   behavior, signature, units, ranges, or gotchas changed:
   - Keep the section structure identical to the existing docs (see any `reference/*.md`).
   - Every claim must be grounded in the code you just wrote — never document an intended
     behavior that isn't in the source.
   - Update the **Audit notes** subsection (Fixed / Known-deferred).
   - If you **added a new instrument**: add a `reference/<name>.md`, add it to the table in
     [`SKILL.md`](SKILL.md), add the factory to `SKILL.md`'s construction section, and (if it
     needs a new registry/alias) reflect that in `reference/transport-and-discovery.md`.
   - If you **changed the shared construction or `.safe`/recovery contract**: update
     [`reference/00-runtime-and-construction.md`](reference/00-runtime-and-construction.md).

3. **Re-bless the manifest:**
   ```bash
   python3 .claude/skills/bsl-universal/scripts/update_manifest.py
   ```
   Run this **only after** the docs actually reflect the new code. Do not bless a stale skill
   just to clear the gate — that silently misleads the next agent and defeats the policy.

4. **Sanity check:** `python3 -c "import bsl_universal"` must succeed, and
   `python3 .claude/skills/bsl-universal/scripts/check_sync.py` must exit 0.

## Regenerating the whole skill from scratch
If a large refactor touched many files, regenerate comprehensively rather than patching:
re-run the three-phase pipeline that built this skill (map → verify/fix → author → review).
The workflow scripts used originally are described in [`AUDIT.md`](AUDIT.md#regeneration).
At minimum, for each changed module: re-read the source in full, rewrite its `reference/*.md`
to match, then `update_manifest.py`.

## Files in this skill
```
.claude/skills/bsl-universal/
├── SKILL.md                      # entry point: index + decision tree + safety rules
├── MAINTENANCE.md                # this file
├── AUDIT.md                      # audit findings (applied + deferred) + methodology
├── .api_manifest.json           # source fingerprint (the sync gate's baseline)
├── reference/
│   ├── 00-runtime-and-construction.md
│   ├── <one .md per instrument>
│   ├── transport-and-discovery.md
│   └── analysis-mantiscam.md
└── scripts/
    ├── _manifest_common.py       # shared hashing helpers (no deps)
    ├── check_sync.py             # CLI drift check (exit 2 on drift)
    ├── update_manifest.py        # bless current source state
    ├── hook_stop_sync.py         # Stop-hook gate
    └── hook_posttool_notice.py   # PostToolUse nudge
```
