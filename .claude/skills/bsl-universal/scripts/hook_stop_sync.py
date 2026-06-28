#!/usr/bin/env python3
"""Stop-hook gate: block turn-end while the AI skill is out of sync with the library.

Registered as a `Stop` hook in .claude/settings.json. Protocol (Claude Code hooks):
- Reads a JSON event on stdin. If `stop_hook_active` is true we ALLOW the stop
  (exit 0, no output) to avoid an infinite block loop.
- Otherwise it fingerprints the bsl_universal source tree and compares to the
  blessed manifest. On DRIFT it prints `{"decision":"block","reason":...}` on
  stdout and exits 0, which makes Claude keep working (it must update the skill
  + re-bless the manifest before it can stop).

Pure stdlib + the sibling _manifest_common module — no jq, no third-party deps.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make the sibling manifest helper importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from _manifest_common import compute_manifest, diff_manifest, load_manifest
except Exception as exc:  # pragma: no cover - defensive: never break the session
    # If the gate itself is broken, do not trap the user — allow the stop.
    print(json.dumps({"systemMessage": f"[bsl-skill-sync] gate import failed: {exc}"}))
    sys.exit(0)


def _read_event() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def main() -> int:
    event = _read_event()

    # Avoid infinite loops: once we've already blocked once this chain, let it stop.
    if event.get("stop_hook_active") is True:
        return 0

    stored = load_manifest()
    current = compute_manifest()

    if stored is None:
        # No manifest yet — first-time setup. Don't block (the skill is being built).
        return 0

    delta = diff_manifest(stored, current)
    if not (delta["added"] or delta["removed"] or delta["changed"]):
        return 0  # in sync — allow stop

    lines = ["bsl_universal source changed since the AI-native skill was last regenerated."]
    for kind in ("added", "removed", "changed"):
        for f in delta[kind]:
            lines.append(f"  {kind}: {f}")
    lines.append(
        "Per repo policy you MUST, before finishing: (1) re-audit the changed code, "
        "(2) update the affected docs under .claude/skills/bsl-universal/reference/ "
        "(and SKILL.md if the public API changed), then (3) run "
        "`python3 .claude/skills/bsl-universal/scripts/update_manifest.py`. "
        "See .claude/skills/bsl-universal/MAINTENANCE.md."
    )
    reason = "\n".join(lines)

    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
