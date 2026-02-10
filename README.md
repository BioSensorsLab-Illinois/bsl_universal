# bsl_universal

Universal hardware control and camera-analysis library used by BioSensors Lab (UIUC).

`bsl_universal` provides:

- Unified constructors for supported lab instruments.
- Runtime stability helpers (retry/reconnect/reset paths).
- A live GUI monitor for connection status and health.
- Email alerts (Google Workspace OAuth via Gmail SMTP XOAUTH2).
- MantisCam control and recording utilities over ZMQ.
- Analysis loaders for MantisCam `.h5` data.

## Table of Contents

1. [Project Goals](#project-goals)
2. [Key Features](#key-features)
3. [Architecture](#architecture)
4. [Supported Instruments](#supported-instruments)
5. [Requirements](#requirements)
6. [Installation](#installation)
7. [Quick Start](#quick-start)
8. [Instrument API Quick Reference](#instrument-api-quick-reference)
9. [IDE Typing and Autocomplete](#ide-typing-and-autocomplete)
10. [MantisCam Control API](#mantiscam-control-api)
11. [Device Monitor GUI](#device-monitor-gui)
12. [Email Alerts (Google Workspace OAuth)](#email-alerts-google-workspace-oauth)
13. [Runtime State Files](#runtime-state-files)
14. [Stability and Recovery Model](#stability-and-recovery-model)
15. [Analysis API (Mantis `.h5`)](#analysis-api-mantis-h5)
16. [Build and Distribution](#build-and-distribution)
17. [CI/CD](#cicd)
18. [Troubleshooting](#troubleshooting)
19. [Repository Layout](#repository-layout)

## Project Goals

This library is designed for hardware-facing control where stability is prioritized over aggressive behavior changes.

Core objectives:

- Keep hardware communication robust under transient bus/software failures.
- Surface device state in a non-blocking monitor path.
- Avoid crashes in monitoring/alerting paths.
- Provide direct, typed constructors for better IDE autocomplete in VSCode.
- Keep camera controls explicit and safe for mixed camera families.

## Key Features

- Typed instrument constructors in `bsl_universal.instruments.inst`.
- Factory registry for dynamic construction (`InstrumentFactory`).
- Runtime helpers injected per instrument:
  - `safe.<method>(...)` recovery-managed method calls.
  - `invoke("method", ...)` or `invoke_safe(...)`.
  - `reconnect_safe()` and `reset_safe()`.
- Automatic monitor window startup on first instrument initialization.
- Automatic disconnection publication when objects are released and closed.
- MantisCam-specific monitor hooks:
  - connecting/connected/disconnected/warning transitions,
  - backend reachability checks,
  - stale-session reconciliation.
- Email alerts with policy categories and per-instrument matrix overrides.

## Architecture

### 1) Public constructors

Use `bsl_universal.instruments.inst` as the primary API.

- Direct constructors (recommended): `inst.PM100D(...)`, `inst.mantisCam(...)`, etc.
- Factory path: `InstrumentFactory.create("PM100D", ...)`.

### 2) Driver layer

Low-level instrument drivers live in:

- `bsl_universal/instruments/_inst_lib/instruments/`

These drivers handle command syntax and vendor-specific behavior.

### 3) Transport interfaces

Shared transport wrappers:

- Serial: `bsl_universal/instruments/_inst_lib/interfaces/_bsl_serial.py`
- VISA: `bsl_universal/instruments/_inst_lib/interfaces/_bsl_visa.py`

Both implement bounded retries and reconnect attempts.

### 4) Runtime health + GUI

- `DeviceHealthHub`: thread-safe device state registry and persistence.
- `device_monitor_gui.py`: subprocess Tk app for live status visualization.

### 5) Analysis layer

- `bsl_universal.analysis`: loaders for MantisCam files/folders.

## Supported Instruments

Canonical keys are defined in `bsl_universal/instruments/registry.py`.

- `PM100D`
- `PM400`
- `DC2200`
- `M69920`
- `CS260B`
- `HR4000CG`
- `RS_7_1`
- `SP_2150`
- `USB_520`
- `BSC203_HDR50`
- `mantisCam`

Aliases:

- `USB520` -> `USB_520`
- `MantisCam` -> `mantisCam`

## Requirements

Minimum runtime dependencies are listed in `requirements.txt`, including:

- `numpy`, `loguru`, `tqdm`
- `pyserial`
- `pyvisa`, `pyvisa-py`
- `seabreeze`, `libusb`
- `h5py`, `opencv-python`, `scikit-image`
- `pyzmq`
- `google-auth`, `google-auth-oauthlib`

Notes:

- GUI requires Tkinter availability in your Python distribution.
- VISA availability depends on backend/runtime environment.
- MantisCam control requires reachable MantisCamUnified ZMQ endpoints.

## Installation

### Editable development install

```bash
pip install -e .
```

### Standard install

```bash
pip install .
```

### Wheel build install

```bash
pip install dist/*.whl
```

## Quick Start

```python
from bsl_universal.instruments import inst

# Optional: set global logging level once
inst.init_logger("INFO")

# Example 1: PM100D
pm = inst.PM100D(device_sn="")
power_w = pm.get_measured_power()
print("Power (W):", power_w)
pm.close()

# Example 2: Safe invoke wrapper (recovery-managed)
pm2 = inst.PM400()
power2 = pm2.safe.get_measured_power()
pm2.close()

# Example 3: MantisCam
cam = inst.mantisCam()
name, sn = cam.get_camera_name_serial(refresh=True)
print(name, sn)
frame = cam.get_raw_frame(timeout_ms=5000)
cam.close()
```

## Instrument API Quick Reference

Recommended constructor module:

- `from bsl_universal.instruments import inst`

Common driver methods vary by instrument, but these are frequently used entry points:

- `inst.PM100D(device_sn="")`
  - `get_measured_power()`, `set_auto_range(...)`, `set_preset_wavelength(...)`, `reconnect()`, `reset_meter()`
- `inst.PM400(device_sn="")`
  - `get_measured_power()`, `set_auto_range(...)`, `set_preset_wavelength(...)`, `reconnect()`, `reset_meter()`
- `inst.DC2200(device_sn="")`
  - `set_LED1_ON()`, `set_LED1_constant_current(...)`, `set_LED1_PWM(...)`, `reconnect()`, `reset_controller()`
- `inst.M69920(device_sn="")`
  - `lamp_ON()`, `lamp_OFF()`, `set_lamp_power(...)`, `set_lamp_current(...)`, `reconnect()`, `reset_supply()`
- `inst.CS260B(device_sn="")`
  - `set_wavelength(...)`, `set_grating(...)`, `open_shutter()`, `reconnect()`, `reset_controller()`
- `inst.HR4000CG(device_sn="")`
  - `get_spectrum()`, `set_integration_time_micros(...)`, `reconnect()`, `reset_connection()`
- `inst.RS_7_1(device_sn="", power_on_test=True)`
  - `set_spectrum_*` family, `set_power_*` family, `reconnect()`, `reset_system()`
- `inst.SP_2150(device_sn="")`
  - `set_wavelength(...)`, `set_grating(...)`, `reconnect()`, `reset_controller()`
- `inst.USB_520(device_sn="", tear_on_startup=True, reverse_negative=True)`
  - `get_new_measurement()`, `set_tear_calibration(...)`, `reconnect()`, `reset_tear_calibration()`
- `inst.BSC203_HDR50()`
  - `home()`, `set_angle(...)`, `get_curr_angle(...)`, `reconnect()`, `reset_stage()`
- `inst.mantisCam(device_sn="")`
  - See [MantisCam Control API](#mantiscam-control-api)

RS-7-1 startup note:

- `power_on_test=True` runs integrity/basic assurance checks.
- Failures in these startup tests are warning-only and do not hard-fail initialization.

## IDE Typing and Autocomplete

Constructor wrappers in `bsl_universal.instruments.inst` include explicit return typing via `TYPE_CHECKING` imports and casts.
For best VSCode autocomplete:

- Import constructors from `inst`:
  - `from bsl_universal.instruments import inst`
- Optionally annotate concrete type:
  - `cam = inst.mantisCam()  # type: MantisCamCtrl`
  - `pm = inst.PM100D()      # type: PM100DDriver`
- Use direct constructor call result (avoid heavily dynamic wrapper indirection in user code).

## MantisCam Control API

Primary class: `MantisCamCtrl` (`inst.mantisCam(...)`).

### Core common operations

- `start_recording(mode="n_frames", n_frames=10, ...)`
- `stop_recording(...)`
- `set_exposure_time(exposure_ms, ...)`
- `get_camera_name_serial(refresh=True)`
- `set_recording_folder(...)`
- `set_recording_file_name(...)`
- `get_raw_frame(...)`
- `get_isp_frame(frame_name=None, ...)`
- `get_isp_frame_names(...)`

### Hardware-node catalog operations

- `refresh_hardware_nodes()`
- `get_hardware_nodes(refresh=False)`
- `set_hardware_node(node_name, value=None)`

### Exposure behavior

- GSense family uses safeguard timing (metadata readback not trusted).
- Other camera families use readback validation.
- Accept criteria: within `max(1%, 0.1 ms)`.

### Frame retrieval behavior

- `fresh=True` can reset local video socket to reduce stale buffered frames.
- Frames are copied out of transport/shared memory to avoid unsafe references.

### Auto exposure helper

- `run_auto_exposure(...)` uses ISP statistics / frame mean feedback.

## Device Monitor GUI

A monitor window starts automatically when an instrument is first initialized.

Function:

- `bsl_universal.core.device_monitor_gui.start_device_monitor_window()`

The GUI shows:

- Model/nickname, type, serial number
- Status (`CONNECTING`, `CONNECTED`, `DISCONNECTED`, `WARNING`, `UNRECOVERABLE_FAILURE`, `STALE_SESSION`)
- Last update time and last error
- Summary cards by status
- Filter and active-only view
- Actions to clear stale/disconnected/failure rows

### Status semantics

- `CONNECTING`: constructor/connection in progress.
- `CONNECTED`: healthy active session.
- `WARNING`: recoverable issue detected.
- `UNRECOVERABLE_FAILURE`: repeated operation/transport failure.
- `DISCONNECTED`: explicit close or backend unavailable.
- `STALE_SESSION`: old process-owned entry no longer alive.

## Email Alerts (Google Workspace OAuth)

Email alerts are policy-driven and non-blocking.

Current flow is OAuth-only (no app-password fallback).

### Default sender

- `students@bsl-uiuc.com`

### GUI configuration

In the monitor window:

- Keep recipient email in the main alert card.
- Open `Settings -> Advanced -> OAuth / Server JSON...` for:
  - sender workspace email,
  - OAuth client secret JSON path,
  - token file path.

### First-time authorization

Use `Authorize Google Workspace` button in the GUI.

Expected behavior:

- Browser-based login flow is launched (`run_local_server`).
- OAuth token is saved locally.
- SMTP XOAUTH2 is used for delivery.

Required scope:

- `https://mail.google.com/`

### Alert policy model

Supported categories:

- `CONNECTING`
- `CONNECTED`
- `DISCONNECTED`
- `WARNING`
- `UNRECOVERABLE_FAILURE`
- `STALE_SESSION`

Policy controls:

- Default categories for all instruments.
- Optional per-instrument category override matrix.
- Matrix popup shows connected instruments only.

## Runtime State Files

Runtime monitor and email configuration are persisted under:

- `~/.bsl_universal/device_monitor_state.json`
- `~/.bsl_universal/device_monitor_email.json`
- `~/.bsl_universal/gmail_oauth_token.json` (default token path)

The library includes a default OAuth client-secret path in code. In production, use the GUI advanced settings to point to your own managed OAuth client-secret file.

## Stability and Recovery Model

### Operation-level recovery

`InstrumentRecoveryManager` supports:

- bounded retries,
- optional reset-before-retry,
- reconnect-before-retry,
- configurable delay.

### Safe proxy

Every constructed instrument gets a safe proxy attribute:

- Usually `obj.safe.<method>(...)`
- If driver already has `safe`, library adds `obj.bsl_safe` instead.

### Lifecycle safety

- `close()` wrappers publish disconnection status.
- Class-level `__del__` hook or weakref finalizer handles GC-time release publication.
- Monitor/email errors are isolated from hardware control paths.

## Analysis API (Mantis `.h5`)

High-level analysis constructors:

```python
from pathlib import Path
from bsl_universal.analysis import (
    open_mantis_file,
    open_mantis_folder,
    open_mantis_gs_file,
    open_mantis_gs_folder,
)

f = open_mantis_file(Path("/path/to/file.h5"))
```

Also available as direct classes:

- `mantis_file`
- `mantis_folder`
- `mantis_file_GS`
- `mantis_folder_GS`

## Build and Distribution

### Build wheel/sdist

```bash
python -m build --sdist --wheel
```

### Unified wheel target

This project is configured to produce a pure Python wheel:

- Tag expectation: `py3-none-any`

Example artifact:

- `bsl_universal-0.5-py3-none-any.whl`

## CI/CD

GitHub Actions workflow: `.github/workflows/ci.yml`

### Validation matrix

Platforms:

- `windows-2022`
- `macos-26`
- `ubuntu-22.04`
- `ubuntu-22.04-arm`
- `macos-15`
- `macos-15-intel`

Python versions:

- `3.8`, `3.9`, `3.10`, `3.11`, `3.12`, `3.13`, `3.14`

### Distribution artifact job

A dedicated `unified-wheel` job:

- builds one wheel,
- verifies `py3-none-any` tag,
- runs `twine check`,
- uploads artifact `bsl-universal-unified-wheel`.

## Troubleshooting

### MantisCam appears connected after backend closes

The health hub reconciles MantisCam liveness by probing required local command ports. If backend is not reachable, status transitions to `DISCONNECTED`.

### Gmail auth errors (`535` / username-password not accepted)

This library uses OAuth XOAUTH2 SMTP. Ensure:

- OAuth authorization completed in GUI,
- token includes `https://mail.google.com/` scope,
- signed-in account matches sender email (or has send-as permission),
- Workspace SMTP AUTH policy allows the account.

### No GUI window appears

Possible causes:

- Tkinter unavailable in Python environment.
- Monitor subprocess startup blocked by environment policy.

### VISA devices not found

Check:

- PyVISA installation and backend.
- Device visibility in resource manager.
- USB VID/PID/serial filters.

### Serial devices not found

Check:

- Device permissions and busy ports.
- Correct serial selector / hardware connection.
- Expected query response configured in metadata.

## Repository Layout

```text
bsl_universal/
  core/
    device_health.py          # Runtime status registry + email alert delivery
    device_monitor_gui.py     # Tk monitor subprocess GUI
    instrument_runtime.py     # Recovery manager, safe proxy, managed wrapper
    logging.py                # Loguru setup
    exceptions.py             # Public exception aliases

  instruments/
    inst.py                   # Public typed constructors + runtime hook injection
    factory.py                # Lazy-loading factory
    registry.py               # Instrument key/spec registry
    _inst_lib/
      instruments/            # Device-specific drivers
      interfaces/             # Serial/VISA robust transport wrappers
      headers/                # Legacy metadata/type helpers

  analysis/
    api.py                    # High-level Mantis analysis constructors
    _mantisCam/               # Mantis file/folder analysis implementations
```

## License

MIT License. See `LICENSE`.
