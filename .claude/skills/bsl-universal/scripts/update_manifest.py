#!/usr/bin/env python3
"""Bless the current library source state as "skill is in sync".

Run this ONLY after you have re-audited the changed source and updated the
affected reference docs under .claude/skills/bsl-universal/. It rewrites
.api_manifest.json to the live source fingerprint, which clears the Stop-hook
drift gate.
"""
from __future__ import annotations

from _manifest_common import compute_manifest, write_manifest, MANIFEST_PATH


def main() -> int:
    manifest = compute_manifest()
    write_manifest(manifest)
    print(f"[bsl-skill-sync] Manifest updated: {MANIFEST_PATH}")
    print(f"[bsl-skill-sync] Tracked source files: {len(manifest['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
