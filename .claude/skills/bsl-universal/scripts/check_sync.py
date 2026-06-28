#!/usr/bin/env python3
"""Sync gate: is the bsl-universal AI skill in sync with the library source?

Exit 0  -> in sync (manifest matches live source tree)
Exit 2  -> DRIFT: library source changed since the skill was last regenerated,
           OR the manifest is missing. Prints the drift so an agent can act.

Used by the project Stop hook (.claude/settings.json). When it exits non-zero,
the agent is told to follow MAINTENANCE.md (re-audit + update the affected
reference docs) and then run update_manifest.py to bless the new state.
"""
from __future__ import annotations

import sys

from _manifest_common import compute_manifest, diff_manifest, load_manifest


def main() -> int:
    stored = load_manifest()
    current = compute_manifest()

    if stored is None:
        print("[bsl-skill-sync] No API manifest found "
              "(.claude/skills/bsl-universal/.api_manifest.json).")
        print("[bsl-skill-sync] Run: python .claude/skills/bsl-universal/scripts/update_manifest.py")
        return 2

    delta = diff_manifest(stored, current)
    if not (delta["added"] or delta["removed"] or delta["changed"]):
        return 0

    print("[bsl-skill-sync] DRIFT DETECTED: bsl_universal source changed since the "
          "AI-native skill was last regenerated.")
    for kind in ("added", "removed", "changed"):
        for f in delta[kind]:
            print(f"  {kind:>7}: {f}")
    print()
    print("[bsl-skill-sync] Per repo policy, AI-driven changes to the library MUST be "
          "followed by a skill re-audit + API doc update.")
    print("[bsl-skill-sync] Follow .claude/skills/bsl-universal/MAINTENANCE.md, then run:")
    print("[bsl-skill-sync]   python .claude/skills/bsl-universal/scripts/update_manifest.py")
    return 2


if __name__ == "__main__":
    sys.exit(main())
