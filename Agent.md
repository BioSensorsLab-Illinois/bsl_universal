# bsl_universal Project Structure and Development Guide

## IMPORTANT DEVELOPMENT RULES
1. **ALWAYS delete all test scripts** created during code generation (e.g., `test_*.py`)
2. **CRITICAL - For DearPyGUI changes**:
   - **ALWAYS CHECK DearPyGUI API DOCUMENTATION FIRST** before using any dpg function
   - Double check all DPG modifications - it is a very intricate library
   - For every change/addition, verify the function signature and available parameters
   - Common mistake: dpg.add_text() does NOT accept 'width' parameter
3. **NEVER generate** user-facing readme, tutorial, or changelog files

## Project Purpose
`bsl_universal` is a hardware-control and data-analysis Python package for BioSensors Lab workflows.
It has two major responsibilities:
1. Unified control of lab instruments over VISA, serial, USB SDKs, and ZMQ.
2. Post-processing utilities for MantisCam `.h5` recordings (standard and GSense dual-gain formats).

The package is intended for production lab automation, not just demos, so changes should prioritize:
- Device safety and predictable shutdown behavior.
- Connection robustness on mixed hardware environments.
- Reproducible, testable data processing outputs.

## Repository Layout (Actual)
```
bsl_universal/
├── Agent.md
├── setup.py
├── requirements.txt
└── bsl_universal/
    ├── __init__.py
    ├── instruments/
    │   ├── __init__.py
    │   ├── inst.py                             # Public factory entrypoints
    │   └── _inst_lib/
    │       ├── headers/
    │       │   ├── _bsl_type.py               # Custom exceptions
    │       │   ├── _bsl_inst_info.py          # Instrument metadata registry
    │       │   ├── _bsl_inst_info_class.py
    │       │   └── _bsl_logger.py
    │       ├── interfaces/
    │       │   ├── _bsl_serial.py             # Serial auto-discovery + transport
    │       │   └── _bsl_visa.py               # VISA/SCPI discovery + transport
    │       └── instruments/
    │           ├── _PM100D.py
    │           ├── _PM400.py
    │           ├── _DC2200.py
    │           ├── _CS260B.py
    │           ├── _M69920.py
    │           ├── _SP_2150.py
    │           ├── _RS_7_1.py
    │           ├── _Futek_USB_520.py
    │           ├── _HR4000CG.py
    │           ├── _BSC203.py
    │           ├── _mantisCam.py
    │           └── _thorlabs_apt_device/      # Vendored third-party motion-control stack
    ├── analysis/
    │   ├── __init__.py
    │   └── _mantisCam/
    │       ├── mantis_file.py
    │       ├── mantis_folder.py
    │       ├── mantis_file_GS.py
    │       └── mantis_folder_GS.py
    └── test.py                                # Local exploratory script (not test suite)
```

## Main Public API Surface
### 1) Instrument factories (`bsl_universal/instruments/inst.py`)
Top-level constructors initialize logging and return concrete instrument driver objects:
- `PM100D()`, `PM400()`, `DC2200()`, `M69920()`, `CS260B()`
- `HR4000CG()`, `RS_7_1()`, `SP_2150()`, `USB_520()`
- `BSC203_HDR50()`
- `mantisCam()`

Additive runtime safety helpers are attached when possible:
- `.safe.<method>(...)` executes with bounded retry + reset/reconnect recovery.
- `.invoke(...)` / `.invoke_safe(...)` provide explicit recovery-managed calls.
- `.reconnect_safe()` and `.reset_safe()` expose guarded recovery calls.
- `.close()` is monitored so GUI state transitions to disconnected.
- Managed instances auto-release on object destruction (`del` + GC), and monitor
  status is published as disconnected even when users forget to call `.close()`.
- MantisCam entries are additionally validated against local `MantisCamUnified`
  command ports (`127.0.0.1:60000` and `60001`); if backend process is gone,
  GUI state is auto-marked as disconnected.
- MantisCam runtime now publishes live monitor transitions from transport
  activity/timeouts: warning on link degradation, disconnected when backend is
  unreachable, and auto-connected again when communication resumes (including
  camera swaps behind the same backend process).
- Monitor publishes a `CONNECTING` status before constructor handshake so GUI can
  display in-progress connection attempts.
- MantisCam monitor identity is single-active per runtime process; sequential
  reconnects replace older entries instead of accumulating stale rows.
- Monitor email alerts use Google Workspace OAuth interactive authorization only.
  App-password fallback is removed by design.
  Authorization uses interactive browser login and forces consent to refresh scopes.
  Alerting supports multiple status categories (`CONNECTING`, `CONNECTED`,
  `DISCONNECTED`, `WARNING`, `UNRECOVERABLE_FAILURE`, `STALE_SESSION`) with
  default-category selection and per-instrument override matrix.
  The policy is editable from monitor GUI via `Alert Categories...` pop-up.
  The matrix editor lists connected instruments only.
  Default OAuth client-secret JSON is hardcoded for lab deployment; overriding
  the JSON path is available via monitor GUI `Settings > Advanced`.
  Tokens with legacy `gmail.send` scope are treated as incompatible in SMTP mode
  and require re-authorization.

### 2) Transport abstraction
- `_bsl_visa`: enumerates VISA resources by USB PID/VID and queries identity.
- `_bsl_serial`: scans serial ports, tries configured baudrates, validates responses.

### 3) Metadata-driven instrument selection
`_bsl_inst_info.py` defines per-device metadata:
- Interface type (`VISA`, `Serial`, `USB-SDK`, `ZMQ`, `FTDI`)
- Vendor/product identifiers
- Query commands and expected response matching regex

### 4) MantisCam analysis API
- `mantis_file` / `mantis_folder` for standard files.
- `mantis_file_GS` / `mantis_folder_GS` for GSense dual-gain and optional 2x2 filters.
- Features include dark-frame subtraction, HDR merge, and color/special-plane extraction.

## Supported Device Families
- Thorlabs: `PM100D`, `PM400`, `DC2200`, `BSC203_HDR50`
- Newport: `M69920`, `CS260B`
- Princeton Instruments: `SP_2150`
- Gamma Scientific: `RS_7_1`
- OceanOptics: `HR4000CG`
- Futek: `USB_520`
- MantisCam recorder/control over ZMQ: `MantisCamCtrl`

## Data Model Expectations
MantisCam analysis utilities expect `.h5` files with:
- `camera/frames`
- `camera/integration-time-expected`
- `camera/timestamp`

GSense convention:
- Left half of frame = High Gain
- Right half of frame = Low Gain
- Optional 2x2 sampling maps channels (`R_loc`, `G_loc`, `B_loc`, `SP_loc`)

## Development Workflow For New Instrument Support
1. Add metadata entry in `_bsl_inst_info.py`.
2. Implement driver in `_inst_lib/instruments/`.
3. Use `_bsl_serial` or `_bsl_visa` (or SDK-specific connector) instead of direct ad hoc transport logic.
4. Add factory wrapper in `instruments/inst.py`.
5. Ensure `close()` safely releases hardware and can be called repeatedly.
6. Keep method names aligned with existing driver naming patterns.

## Current Technical Risks And Upgrade Priorities
### Priority 0 (stability/safety)
1. Replace `sys.exit(...)` calls inside drivers with typed exceptions (`bsl_type`).
2. Fix obvious runtime defects:
   - `MantisCamCtrl.get_frame_mean_gs_hg/get_frame_mean_gs_lg` argument forwarding bug.
   - `RS_7_1.set_iris_position` boundary condition (`and` should be logical range validation).
   - `RS_7_1.set_spectrum_pantone` uses undefined variable names.
3. Harden null checks around `_com` and transport connection failures.

### Priority 1 (maintainability)
1. Deduplicate `PM100D` and `PM400` into shared base behavior.
2. Move `_bsl_inst_info_class` to `@dataclass` with validation.
3. Add context-manager support (`__enter__`/`__exit__`) for all instrument classes.
4. Improve typing and return consistency across all public methods.

### Priority 2 (analysis performance and correctness)
1. Add lazy frame-window reading utilities for large HDF5 files.
2. Add validation helpers for dark-frame exposure matching.
3. Add non-naive demosaic option for GS 2x2 color reconstruction.
4. Add deterministic unit tests for HDR/tone mapping edge cases.

### Priority 3 (packaging and release hygiene)
1. Migrate from legacy `setup.py`-only packaging to `pyproject.toml`.
2. Split optional dependencies into extras (e.g., `mantis`, `spectrometer`, `motion`).
3. Add CI matrix (Linux/macOS, Python 3.8-3.12) with lint + smoke tests.
4. Audit license boundaries for vendored third-party code under `_thorlabs_apt_device`.

## Coding Guidelines Specific To This Repo
- Keep driver methods narrow and hardware-safe; verify readback after state-changing commands.
- Prefer explicit timeout handling and retry loops with bounded retries.
- Avoid side effects at import time (especially hardware and global logger reconfiguration).
- Backward compatibility is **not required** for this refactor cycle; prioritize stable architecture.
- Treat external SDK imports as optional and fail with actionable errors.
- RS-7-1 startup integrity/basic assurance checks are warning-only: failures must not block operation.

## Validation Expectations For Changes
For each behavior change, validate with one of:
1. Hardware-in-loop verification on target instrument.
2. Mocked transport unit test for command formatting + parser behavior.
3. Replay-based test using saved `.h5` files for analysis changes.

Minimum validation before merge:
- Module import succeeds in clean environment.
- No regression in instrument construction path for untouched drivers.
- Analysis classes can open and inspect shape metadata from sample files.
