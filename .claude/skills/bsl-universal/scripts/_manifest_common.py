"""Shared helpers for the bsl-universal skill <-> library sync gate.

The "API manifest" is a sha256 fingerprint of every first-party bsl_universal
source file. The skill (AI-native API docs) is considered IN SYNC with the
library only when the stored manifest matches the live source tree.

This module has NO third-party dependencies so it can run from a bare Stop hook.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# scripts/ -> bsl-universal/ -> skills/ -> .claude/ -> <repo root>
SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent.parent
PKG_ROOT = REPO_ROOT / "bsl_universal"
MANIFEST_PATH = SKILL_DIR / ".api_manifest.json"

# Vendored / generated / non-API paths excluded from the fingerprint.
EXCLUDE_PARTS = {
    "__pycache__",
    "_thorlabs_apt_device",   # vendored third-party motion stack (not our API)
    "device_monitor_gui.py",  # GUI chrome, not part of the agent-facing API
    "_web_monitor",           # web monitor (HTTP/SSE GUI chrome, not agent-facing API)
    "test.py",                # local exploratory scratch script, not part of the API
}


def iter_source_files() -> list[Path]:
    """Return the sorted list of first-party .py files that define the public API."""
    files: list[Path] = []
    for path in sorted(PKG_ROOT.rglob("*.py")):
        rel_parts = set(path.relative_to(PKG_ROOT).parts)
        if rel_parts & EXCLUDE_PARTS:
            continue
        if path.name in EXCLUDE_PARTS:
            continue
        files.append(path)
    return files


def is_tracked_source(path: str | Path) -> bool:
    """True if `path` is one of the first-party source files the manifest tracks."""
    try:
        p = Path(path).resolve()
    except Exception:
        return False
    if p.suffix != ".py":
        return False
    try:
        rel_parts = set(p.relative_to(PKG_ROOT).parts)
    except Exception:
        return False
    if rel_parts & EXCLUDE_PARTS or p.name in EXCLUDE_PARTS:
        return False
    return p.exists()


def compute_manifest() -> dict:
    """Compute {relative_path: sha256} for every tracked source file."""
    entries: dict[str, str] = {}
    for path in iter_source_files():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries[str(path.relative_to(REPO_ROOT))] = digest
    return {"version": 1, "files": entries}


def load_manifest() -> dict | None:
    if not MANIFEST_PATH.exists():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text())
    except Exception:
        return None


def diff_manifest(stored: dict | None, current: dict) -> dict:
    """Return added/removed/changed file lists between stored and current manifests."""
    stored_files = (stored or {}).get("files", {})
    cur_files = current.get("files", {})
    added = sorted(set(cur_files) - set(stored_files))
    removed = sorted(set(stored_files) - set(cur_files))
    changed = sorted(
        f for f in set(cur_files) & set(stored_files) if cur_files[f] != stored_files[f]
    )
    return {"added": added, "removed": removed, "changed": changed}


def write_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
