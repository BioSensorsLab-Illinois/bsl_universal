#!/usr/bin/env python3
# Claude-API helper for the bsl_universal CI autofix workflow.
#
# Reads a failed CI log, identifies in-scope source files, asks Claude
# (Opus 4.7) for a minimal patch, validates against scope rules, applies
# it to the working tree, and writes a JSON result the workflow consumes
# to open the autofix PR (first attempt) or push another commit (continuation).
#
# Adapted from MantisCamUnified's scripts/ci/claude_fix_attempt.py.
# Library-specific scope: this repo is a Python package published to
# PyPI, not a PyInstaller binary. Fix surface is setup.py, the package
# imports, the workflow itself, and platform-dep install steps.
#
# Usage:
#   python3 scripts/ci/claude_fix_attempt.py \
#     --run-id <id> \
#     --log-file /tmp/failed-logs/log.txt \
#     --head-sha <sha> \
#     --head-branch <branch> \
#     --mode {first,continue} \
#     [--prior-attempts-summary /tmp/prior_attempts.txt] \
#     --output /tmp/fix_result.json

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_ID = "claude-opus-4-7"
MAX_LOG_LINES = 400
MAX_FILES = 8
MAX_FILE_BYTES = 80_000
MAX_TOTAL_BYTES = 350_000

SCOPE_FREEZE_FORBIDDEN_DIRS = (
    ".agent/",
    "tests/",
    "dist/",
    "build/",
    "bsl_universal.egg-info/",
)

SCOPE_FREEZE_FORBIDDEN_SUFFIXES = (".md", ".rst", ".txt")

# Files almost always relevant to a bsl_universal CI failure. Seeded into
# the candidate set before log-grep, so Claude sees the workflow + package
# entrypoint + dep manifests even when the log only names a leaf module.
ALWAYS_INCLUDED_PATHS = (
    ".github/workflows/ci.yml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "bsl_universal/__init__.py",
)

PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_./\\-]+/)+[A-Za-z0-9_.-]+\.(?:py|sh|ps1|yml|yaml|json|toml|cfg|spec))"
)


@dataclass
class FixResult:
    status: str
    reason: str
    modified_files: list[str] = field(default_factory=list)
    claude_message: str = ""
    branch_name: str = ""
    commit_message: str = ""
    pr_title: str = ""
    pr_body: str = ""

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--log-file", required=True, type=Path)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--head-branch", default="main")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--max-files", type=int, default=MAX_FILES)
    p.add_argument("--mode", choices=("first", "continue"), default="first")
    p.add_argument("--prior-attempts-summary", type=Path, default=None)
    return p.parse_args()


def read_failure_log(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > MAX_LOG_LINES:
        lines = ["... (log head trimmed; last %d lines) ..." % MAX_LOG_LINES] + lines[-MAX_LOG_LINES:]
    return "\n".join(lines)


def is_forbidden_path(rel_posix: str) -> bool:
    if any(rel_posix.startswith(d) for d in SCOPE_FREEZE_FORBIDDEN_DIRS):
        return True
    if any(rel_posix.endswith(s) for s in SCOPE_FREEZE_FORBIDDEN_SUFFIXES):
        return True
    return False


def candidate_files_from_log(log: str, max_files: int) -> list[Path]:
    seen: list[Path] = []

    # 1. Always-included paths first.
    for always_str in ALWAYS_INCLUDED_PATHS:
        rel = Path(always_str)
        full = REPO_ROOT / rel
        if full.is_file() and rel not in seen and not is_forbidden_path(str(rel)):
            seen.append(rel)
            if len(seen) >= max_files:
                return seen

    # 2. Heuristic-grep over the log.
    for match in PATH_PATTERN.finditer(log):
        raw = match.group("path").replace("\\", "/")
        for prefix in (
            "/Users/runner/work/bsl_universal/bsl_universal/",
            "D:/a/bsl_universal/bsl_universal/",
            "D:\\a\\bsl_universal\\bsl_universal\\",
            "/home/runner/work/bsl_universal/bsl_universal/",
        ):
            raw = raw.replace(prefix, "").replace(prefix.replace("/", "\\"), "")
        candidate = (REPO_ROOT / raw).resolve()
        try:
            rel = candidate.relative_to(REPO_ROOT)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        if rel in seen:
            continue
        if is_forbidden_path(str(rel)):
            continue
        seen.append(rel)
        if len(seen) >= max_files:
            break
    return seen


def package_neighbors(files: list[Path], cap: int) -> list[Path]:
    extra: list[Path] = []
    for f in files:
        pkg_dir = (REPO_ROOT / f).parent
        if pkg_dir == REPO_ROOT:
            continue
        for sibling in sorted(pkg_dir.glob("*.py")):
            try:
                rel = sibling.relative_to(REPO_ROOT)
            except ValueError:
                continue
            if rel in files or rel in extra:
                continue
            if is_forbidden_path(str(rel)):
                continue
            extra.append(rel)
            if len(files) + len(extra) >= cap:
                return extra
    return extra


def read_file_capped(rel: Path) -> str:
    full = REPO_ROOT / rel
    raw = full.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raw = raw[:MAX_FILE_BYTES] + b"\n... (truncated for size) ..."
    return raw.decode("utf-8", errors="replace")


def build_messages(
    log: str,
    files: list[Path],
    prior_attempts: str | None = None,
) -> tuple[str, list[dict]]:
    file_blocks: list[str] = []
    used_bytes = 0
    actual_files: list[str] = []
    for rel in files:
        body = read_file_capped(rel)
        block = f"--- file: {rel.as_posix()} ---\n{body}\n"
        if used_bytes + len(block) > MAX_TOTAL_BYTES:
            break
        used_bytes += len(block)
        actual_files.append(rel.as_posix())
        file_blocks.append(block)

    prior_block = ""
    if prior_attempts:
        if len(prior_attempts) > 20_000:
            prior_attempts = prior_attempts[:20_000] + "\n... (prior-attempts log truncated) ...\n"
        prior_block = (
            "PRIOR AUTOFIX ATTEMPTS ON THIS BRANCH — do NOT repeat any of these patches.\n"
            "If your previous reasoning was wrong, switch approach (different file, different fix shape).\n"
            "If you cannot find a NEW direction, return NO_PATCH_AVAILABLE.\n\n"
            "```\n"
            + prior_attempts
            + "\n```\n\n"
        )

    user_text = (
        prior_block
        + "Failure log (tail):\n```\n"
        + log
        + "\n```\n\n"
        + "In-scope files (full contents below — you may ONLY edit these):\n\n"
        + "\n".join(file_blocks)
        + "\n\nProduce the smallest possible unified diff that makes the build green.\n"
        + "Return ONLY the diff in a fenced ```diff block, followed by a one-paragraph\n"
        + "explanation of the root cause and what your patch does."
    )

    messages = [{"role": "user", "content": user_text}]
    return ",".join(actual_files), messages


SYSTEM_PROMPT = """You are a CI auto-fix agent for the bsl_universal Python library
(BioSensors Lab @ UIUC). The CI workflow runs a 42-leg matrix
(6 platforms × 7 Python versions) that pip-installs the package, compiles
its sources, and runs an import-smoke test; followed by a unified-wheel
build, twine-check, and PyPI publish (publish only fires on push to main).

Your job: read the failure log + in-scope source files, propose the SMALLEST
possible patch that would make the build green, and return a unified diff.

NON-NEGOTIABLE CONSTRAINTS:

1. Edit ONLY files whose full content was provided in the user message. Inventing
   new file paths or editing files you weren't shown is forbidden.
2. Do NOT edit documentation (*.md, *.rst, *.txt), tests, or .agent/ files.
3. Do NOT bump the `version` field in setup.py — the CI auto-version-bump
   step (in `.github/workflows/ci.yml`) handles versions by querying PyPI.
   Editing the version manually will collide with that step.
4. The patch must apply cleanly with `git apply --check` (after we retry
   with --recount and --3way as fallbacks).
5. Honor Agent.md repo rules: NEVER add user-facing README / tutorial /
   changelog files; if you create test scripts, they must be deleted.

OUTPUT FORMAT:

```diff
<unified diff suitable for `git apply`>
```

Then 1-2 sentences on the root cause and what your patch does. Nothing else.

Common failure modes for THIS repo (and the matching fix surface):

- ModuleNotFoundError during `pip install`: a dependency in setup.py /
  requirements.txt is missing or version-pinned wrong for the target
  Python / platform. Fix in `setup.py install_requires=[...]` or
  `requirements.txt`. The `.github/workflows/ci.yml` already pre-installs
  some Linux system deps (libhdf5-dev, libusb, libudev, pkg-config) — if
  the failure is platform-specific (e.g., macOS needs `brew install ...`),
  extend the workflow's per-platform install steps.

- Import-smoke failure (`python -c "import bsl_universal"` errors): a
  module imported at package scope raises during the bare-Python smoke
  step. Fix is usually a lazy-import refactor in `bsl_universal/__init__.py`
  or the implicated submodule.

- HDF5 / libusb pkg-config issues on Linux: the workflow has the
  "Ensure libusb pkg-config alias" + "Configure HDF5 environment" steps —
  extend those if a new platform / Python version exposes a new gap.

- Wheel build (`python -m build`) error: setup.py syntax error,
  invalid classifier, missing package data, etc. Fix in setup.py.

- twine check failure: distribution metadata is malformed. Fix in setup.py
  description fields, classifiers, license string.

- Python-version exclude misses (e.g., scikit-image / numpy not yet wheel-
  available on a brand-new Python release): add an `exclude` clause to the
  matrix in ci.yml, mirroring the existing
  `python-version: "3.14"` exclude for linux-arm.

Workflow file (`.github/workflows/ci.yml`) is the FIRST place to look when
the failure is platform-specific or step-config-specific. Runtime imports
are the LAST resort — never weaken a runtime invariant to make CI pass.

If you cannot determine a safe minimal fix from the provided context,
return exactly the string NO_PATCH_AVAILABLE inside the ```diff block.
"""


def call_claude(
    log: str,
    files: list[Path],
    prior_attempts: str | None = None,
) -> tuple[str, list[str]]:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed in CI env (pip install anthropic).")

    file_csv, messages = build_messages(log, files, prior_attempts=prior_attempts)
    actual_files = file_csv.split(",") if file_csv else []

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=messages,
    )
    text_parts = [block.text for block in response.content if getattr(block, "text", None)]
    return "\n".join(text_parts), actual_files


def extract_diff(text: str) -> str | None:
    match = re.search(r"```(?:diff)?\n(.*?)```", text, re.DOTALL)
    if not match:
        return None
    diff = match.group(1).strip()
    if diff == "NO_PATCH_AVAILABLE" or "NO_PATCH_AVAILABLE" in diff.splitlines()[:2]:
        return None
    return diff


def diff_target_paths(diff: str) -> list[str]:
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            out.append(line[6:].strip())
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            cand = line[4:].strip()
            if cand and cand != "/dev/null":
                out.append(cand)
    return out


def patch_violates_scope(diff: str, allowed: list[str]) -> tuple[bool, list[str]]:
    targets = diff_target_paths(diff)
    allowed_set = {p for p in allowed}
    out_of_scope = [t for t in targets if t not in allowed_set]
    if out_of_scope:
        return True, out_of_scope
    if any(is_forbidden_path(t) for t in targets):
        return True, [t for t in targets if is_forbidden_path(t)]
    return False, []


def apply_diff(diff: str) -> tuple[bool, str]:
    attempts = [
        ["git", "apply", "--check", "--whitespace=fix"],
        ["git", "apply", "--check", "--whitespace=fix", "--recount"],
        ["git", "apply", "--check", "--whitespace=fix", "--recount", "--3way"],
    ]
    last_err = ""
    chosen: list[str] | None = None
    for cmd in attempts:
        proc = subprocess.run(
            cmd, input=diff, text=True, capture_output=True, cwd=REPO_ROOT,
        )
        if proc.returncode == 0:
            chosen = cmd
            break
        last_err = proc.stderr
    if chosen is None:
        return False, f"git apply --check failed (tried strict / --recount / --3way): {last_err}"

    apply_cmd = [a for a in chosen if a != "--check"]
    proc = subprocess.run(
        apply_cmd, input=diff, text=True, capture_output=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        return False, f"git apply failed: {proc.stderr}"
    return True, " ".join(apply_cmd)


def build_pr_artifacts(run_id: str, modified: list[str], explanation: str, repo: str) -> dict:
    branch_name = f"autofix/ci-{run_id}"
    pr_title = f"[autofix] CI failure (run {run_id})"
    files_md = "\n".join(f"- `{m}`" for m in modified)
    failure_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    commit_message = (
        f"[autofix] CI run {run_id}\n\n"
        f"Failed run: {failure_url}\n\n"
        f"{explanation}\n\n"
        f"Generated by Claude Opus 4.7 via .github/workflows/auto-fix.yml.\n"
        f"Adapted from MantisCamUnified L-AUTOFIX pattern."
    )
    pr_body = (
        "## Auto-generated fix attempt\n\n"
        f"**Failed run**: {failure_url}\n\n"
        "The CI workflow failed. Claude analyzed the log and proposed the patch in this PR.\n\n"
        "### Modified files\n"
        f"{files_md}\n\n"
        "### Claude's analysis\n"
        f"{explanation}\n\n"
        "---\n"
        "⚠️ **Auto-fixes can be wrong.** Review carefully before merging."
    )
    return {
        "branch_name": branch_name,
        "commit_message": commit_message,
        "pr_title": pr_title,
        "pr_body": pr_body,
    }


def main() -> int:
    args = parse_args()
    output_path: Path = args.output

    log = read_failure_log(args.log_file)
    if not log.strip():
        result = FixResult(status="skip", reason="empty-log")
        result.write(output_path)
        print("No failure log content; nothing to fix.", file=sys.stderr)
        return 1

    candidates = candidate_files_from_log(log, args.max_files)
    if not candidates:
        result = FixResult(status="skip", reason="no-candidate-files")
        result.write(output_path)
        print("Could not identify any in-scope files from the failure log.", file=sys.stderr)
        return 1

    extras = package_neighbors(candidates, args.max_files)
    file_set = candidates + extras
    print(f"In-scope files for Claude ({len(file_set)}):", file=sys.stderr)
    for p in file_set:
        print(f"  - {p.as_posix()}", file=sys.stderr)

    repo = os.environ.get("GH_REPO", "")

    prior_attempts: str | None = None
    if args.prior_attempts_summary and args.prior_attempts_summary.exists():
        try:
            prior_attempts = args.prior_attempts_summary.read_text(encoding="utf-8", errors="replace")
            print(f"Including {len(prior_attempts)} bytes of prior-attempt history in prompt.", file=sys.stderr)
        except Exception as exc:
            print(f"Could not read prior-attempts summary: {exc}", file=sys.stderr)

    try:
        response_text, sent_files = call_claude(log, file_set, prior_attempts=prior_attempts)
    except Exception as exc:
        result = FixResult(status="error", reason=f"api-error: {exc}")
        result.write(output_path)
        print(f"Claude API call failed: {exc}", file=sys.stderr)
        return 1

    diff = extract_diff(response_text)
    if not diff:
        result = FixResult(
            status="skip",
            reason="no-patch-available",
            claude_message=response_text[:4000],
        )
        result.write(output_path)
        print("Claude declined to propose a patch.", file=sys.stderr)
        return 1

    violates, bad = patch_violates_scope(diff, sent_files)
    if violates:
        result = FixResult(
            status="skip",
            reason=f"scope-violation: {bad}",
            claude_message=response_text[:4000],
        )
        result.write(output_path)
        print(f"Patch touches out-of-scope files: {bad}", file=sys.stderr)
        return 1

    ok, err = apply_diff(diff)
    if not ok:
        result = FixResult(
            status="skip",
            reason=f"apply-failed: {err}",
            claude_message=response_text[:4000],
        )
        result.write(output_path)
        print(f"Patch did not apply: {err}", file=sys.stderr)
        return 1

    modified = diff_target_paths(diff)
    explanation = response_text.split("```", 2)[-1].strip() or "No explanation returned."
    artifacts = build_pr_artifacts(args.run_id, modified, explanation, repo)
    result = FixResult(
        status="patched",
        reason="ok",
        modified_files=modified,
        claude_message=explanation,
        **artifacts,
    )
    result.write(output_path)
    print(f"Patch applied. Modified: {modified}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
