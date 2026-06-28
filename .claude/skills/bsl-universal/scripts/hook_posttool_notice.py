#!/usr/bin/env python3
"""PostToolUse nudge: when an agent edits bsl_universal source, remind it early.

This is a soft, non-blocking complement to the Stop-hook gate (hook_stop_sync.py).
It injects a one-time-per-edit reminder so the agent updates the AI skill as it
goes, rather than discovering the blocked Stop at the end of the turn.

Matched on Edit|Write|MultiEdit in .claude/settings.json. Never blocks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from _manifest_common import is_tracked_source
except Exception:
    sys.exit(0)  # never break the session over a nudge


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    tool_input = event.get("tool_input") or {}
    paths = []
    for key in ("file_path", "filePath", "path"):
        if tool_input.get(key):
            paths.append(tool_input[key])
    # MultiEdit / batch shapes
    for edit in tool_input.get("edits", []) or []:
        if isinstance(edit, dict) and edit.get("file_path"):
            paths.append(edit["file_path"])

    if not any(is_tracked_source(p) for p in paths):
        return 0

    context = (
        "[bsl-skill-sync] You just edited bsl_universal library source. Per "
        ".claude/CLAUDE.md you must, before ending the turn: re-audit the change, "
        "update the affected docs in .claude/skills/bsl-universal/reference/ (and "
        "SKILL.md if the public API changed), then run "
        "`python3 .claude/skills/bsl-universal/scripts/update_manifest.py`. "
        "A Stop hook will block you until the skill manifest is back in sync."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
