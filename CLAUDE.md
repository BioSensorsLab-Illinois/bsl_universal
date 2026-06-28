# CLAUDE.md — bsl_universal

Operating rules for any AI agent (Claude Code or otherwise) working in this repository.
For library architecture and contributor conventions, see [`Agent.md`](Agent.md).

---

## 🔒 HARDENED RULE — library changes MUST update the AI skill

`bsl_universal` ships an **AI-native skill** at
[`.claude/skills/bsl-universal/`](.claude/skills/bsl-universal/) — the canonical,
agent-facing description of every instrument's API, units, ranges, safety notes, and
known defects. It is the source other agents rely on to drive lab hardware **without
reading the source**. If it drifts from the code, an agent will send a wrong command to
real instruments.

**Therefore, whenever you modify, extend, refactor, or fix anything under
`bsl_universal/bsl_universal/**` (drivers, core runtime, factory/registry, interfaces,
analysis), you MUST, before ending your turn:**

1. **Re-audit** the changed code for P0/P1 defects (the audit lens in
   [`.claude/skills/bsl-universal/AUDIT.md`](.claude/skills/bsl-universal/AUDIT.md)).
2. **Update the affected reference docs** under `.claude/skills/bsl-universal/reference/`
   so signatures, parameters, units, ranges, examples, and gotchas match the new code.
   Add new instruments to `SKILL.md`'s index and a new `reference/*.md` file.
3. **Re-bless the sync manifest:**
   ```
   python .claude/skills/bsl-universal/scripts/update_manifest.py
   ```

This is **enforced mechanically**: a `Stop` hook in
[`.claude/settings.json`](.claude/settings.json) runs `scripts/check_sync.py` and **blocks
you from ending the turn** while the library source fingerprint differs from the manifest.
Do not bypass it by blessing the manifest without actually updating the docs — that defeats
the purpose and will mislead the next agent.

The full procedure is in
[`.claude/skills/bsl-universal/MAINTENANCE.md`](.claude/skills/bsl-universal/MAINTENANCE.md).

### 🔗 Cross-repo rule — the MantisCam controller

The MantisCam controller (`bsl_universal/instruments/_inst_lib/instruments/_mantisCam.py`) is
**one half of a two-repo contract** with **MantisCamUnified** (the camera backend it drives over
ZMQ). When you change the controller's command surface — or when the backend changes a command,
payload key, save schema, or per-camera behavior — **both sides and all supported camera families
must be re-audited.** Concretely, any change to `_mantisCam.py` that adds/renames/removes a
backend command (`_safe_send(topic, name, …)`) MUST:

1. Match the backend handlers in `MantisCamUnified/mantiscam_gui/save.py` (file topic),
   `cameras/cam/acquisition.py` (cam topic), `cameras/isp/isp.py` (isp topic), and the shared
   contract `MantisCamUnified/.agent/contracts/zmq_command_contract.json`.
2. State behavior across every camera family (SINGLE_GAIN, DUAL_GAIN_BSI/FSI, POLARIZATION,
   F13_FULL/QUARTER, SIMULATION) — see the backend's `.agent/skills/cross-repo-compat/SKILL.md`.
3. Update the reference docs [`reference/mantiscam-camera.md`](.claude/skills/bsl-universal/reference/mantiscam-camera.md)
   and [`reference/mantiscam-corrections.md`](.claude/skills/bsl-universal/reference/mantiscam-corrections.md).

The backend enforces its half mechanically (`check_zmq_contract.py` + a Stop hook). Keep the two
repos in lockstep.

---

## Quick reference
- **Use the skill**: when driving instruments, read `.claude/skills/bsl-universal/SKILL.md`
  first, then the per-instrument reference file. Construct via the public factories in
  `bsl_universal.instruments` — never instantiate `_inst_lib` driver classes directly.
- **Safety**: state-changing hardware commands should verify readback and raise typed
  `bsl_universal.core.exceptions.*` — never `sys.exit()` inside a driver.
- **Validation before finishing a code change**: `python -c "import bsl_universal"` must
  succeed, and untouched drivers' construction path must not regress.
