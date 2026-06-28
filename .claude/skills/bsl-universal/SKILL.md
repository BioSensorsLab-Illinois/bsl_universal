---
name: bsl-universal
description: >-
  Drive BioSensors Lab instruments and analyze MantisCam recordings via the
  bsl_universal Python library. Use whenever a task involves controlling lab
  hardware through bsl_universal — Thorlabs power meters (PM100D/PM400), the
  DC2200 LED driver, Newport M69920 arc lamp, Newport CS260B or Princeton SP-2150
  monochromators, the Gamma RS-7-1 SpectralLED, OceanOptics HR4000CG spectrometer,
  Futek USB-520 load cell, Thorlabs BSC203/HDR50 rotation stage, or the MantisCam
  camera — or analyzing MantisCam .h5 files (standard or GSense dual-gain). Also
  use when measuring optical power/spectra, setting wavelengths/gratings, driving
  LEDs/lamps, moving the stage, recording frames, or wiring an automated optical
  experiment. Covers safe construction, the .safe recovery layer, per-instrument
  APIs with units/ranges, and known hardware gotchas.
---

# bsl-universal — driving BioSensors Lab instruments

`bsl_universal` is the BioSensors Lab (UIUC) hardware-control + data-analysis library. This
skill lets you drive real lab instruments **correctly and safely without reading the source**.
Every reference doc is grounded in the actual driver code and is kept in sync with it by a
Stop-hook gate (see [`MAINTENANCE.md`](MAINTENANCE.md)).

> ⚠️ **This controls real hardware** — arc lamps, high-power LEDs, motorized stages, light
> sources. A wrong command can damage equipment or invalidate an experiment. Follow the
> safety notes in each reference doc. When in doubt, read the doc before issuing a command.

## Start here: read the runtime contract first
**Always read [`reference/00-runtime-and-construction.md`](reference/00-runtime-and-construction.md) first.**
It covers the construction contract, the `.safe` / `.invoke` recovery layer, `close()` /
teardown, exceptions, and logging — shared by *every* instrument. Then read the specific
instrument doc(s) below.

## Golden rules (apply to every instrument)
1. **Construct via the public factory** in `bsl_universal.instruments` (e.g. `PM100D()`).
   Never instantiate the `_inst_lib` `_Driver` classes directly — that bypasses logging, the
   health monitor, retry-on-connect, and the `.safe` recovery layer.
2. **Always `close()`** in a `try/finally`. An open serial/VISA/USB handle blocks the next
   process from connecting. GC auto-release exists but timing is not guaranteed.
3. **Use `dev.safe.<method>(...)`** for transient-fault resilience (bounded retry +
   reset/reconnect). `.safe` wraps **method calls only** — read properties directly.
4. **Trust readback, not the setpoint.** Many setters do not verify the hardware echoed the
   value (noted per method). Where a `get_*` exists, read it back for safety-critical state.
5. **Validate ranges yourself.** Most drivers do not bounds-check arguments before sending to
   hardware. Use the "Units, ranges & limits" section of each doc.
6. **Catch typed exceptions** from `bsl_universal.core.exceptions`
   (`DeviceConnectionFailed`, `DeviceOperationError`, `DeviceTimeOutError`,
   `DeviceInconsistentError`), not bare `Exception`.

## Pick your instrument

| If you need to…​ | Instrument | Reference |
|---|---|---|
| Measure optical **power / power density / current** | Thorlabs **PM100D / PM400** | [power-meters](reference/power-meters.md) |
| Drive a **high-power LED** (constant-current or PWM) | Thorlabs **DC2200** | [dc2200-led-driver](reference/dc2200-led-driver.md) |
| Run a **Xe/arc lamp** power supply | Newport **M69920** | [m69920-arc-lamp](reference/m69920-arc-lamp.md) |
| Select wavelength with a **monochromator** (grating+filter, shutter) | Newport **CS260B** | [cs260b-monochromator](reference/cs260b-monochromator.md) |
| Select wavelength with a **compact monochromator** | Princeton **SP-2150** | [sp2150-monochromator](reference/sp2150-monochromator.md) |
| Emit a **tunable / arbitrary spectrum** (multi-LED source) | Gamma **RS-7-1 SpectralLED** | [rs7-1-spectralled](reference/rs7-1-spectralled.md) |
| Acquire a **spectrum** (UV-NIR spectrometer) | OceanOptics **HR4000CG** | [hr4000cg-spectrometer](reference/hr4000cg-spectrometer.md) |
| Read **force / load** (grams) | Futek **USB-520** | [usb520-loadcell](reference/usb520-loadcell.md) |
| **Rotate** an optic / sample stage | Thorlabs **BSC203 + HDR50** | [bsc203-hdr50-stage](reference/bsc203-hdr50-stage.md) |
| Control the **camera** (exposure, gains, TEC, record frames) | **MantisCam** (ZMQ) | [mantiscam-camera](reference/mantiscam-camera.md) |
| Remote **dark / hot-pixel / flat-field correction** + raw-vs-processed file save | **MantisCam** (ZMQ) | [mantiscam-corrections](reference/mantiscam-corrections.md) |
| Figure out **why a device won't connect** (serial/VISA discovery, baud, VID/PID) | transport layer | [transport-and-discovery](reference/transport-and-discovery.md) |
| **Analyze MantisCam `.h5`** recordings (standard or GSense dual-gain) | analysis API | [analysis-mantiscam](reference/analysis-mantiscam.md) |

Construct all 11 instruments the same way:

```python
from bsl_universal.instruments import (
    PM100D, PM400, DC2200, M69920, CS260B, SP_2150,
    RS_7_1, USB_520, HR4000CG, BSC203_HDR50, mantisCam,
)
# e.g.
mono = CS260B()                 # device_sn="" auto-selects the only matching unit
try:
    mono.safe.set_wavelength(550)
    ...
finally:
    mono.close()
```

Analyze recordings via `bsl_universal.analysis`:

```python
from bsl_universal.analysis import (
    open_mantis_file, open_mantis_folder,
    open_mantis_gs_file, open_mantis_gs_folder,
)
```

## Common multi-instrument experiment pattern
A typical spectral-response measurement chains a source, a wavelength selector, and a
detector. Construct each, drive them through `.safe`, read back, and `close()` all in a
`finally`. See the per-instrument docs for the exact calls; see the runtime doc for how to
manage several instruments at once.

## Audit & known issues
This skill ships an [`AUDIT.md`](AUDIT.md) recording the 2026-06-28 code audit: 28 confirmed
P0/P1 defects fixed in the drivers, plus known issues deliberately deferred (documented as
warnings in each instrument's "Audit notes"). Read an instrument's **Audit notes** section
before relying on edge-case behavior.

## Keeping this skill correct
If you (an agent) modify `bsl_universal` library code, you **must** update the affected
reference docs and re-bless the sync manifest — this is enforced by a Stop hook. See
[`MAINTENANCE.md`](MAINTENANCE.md).
