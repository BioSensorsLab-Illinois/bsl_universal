# MantisCam — remote image correction & raw-vs-processed save

> **Applies to:** `MantisCamCtrl` (the `mantisCam()` instrument). **Transport:** ZMQ `cmd-file`
> (the backend Saver). **Source:** `_mantisCam.py`; backend `MantisCamUnified/mantiscam_gui/save.py`.
> Read [mantiscam-camera](mantiscam-camera.md) first for construction and the core API.

These controls let an agent drive the MantisCamUnified Saver's dark / hot-pixel / flat-field
correction and choose whether a **processed** companion file is written — all remotely, for any
supported camera (single-gain, GSense dual-gain BSI/FSI, polarization, F13 full/quarter, simulation).

## The one thing to understand first

**Corrections are applied only to the PROCESSED-H5 companion**, not the raw H5 and not the live
display. A processed companion is written **only when `set_save_processed_h5(True)`** (and the
`h5` save target is on). So the normal flow is:

```python
from bsl_universal.instruments import mantisCam
cam = mantisCam()
try:
    cam.set_exposure_time(50)            # set exposure BEFORE capturing a dark
    # 1) capture references (block light for dark, uniform field for flat)
    cam.capture_dark_frame()             # builds dark ref AND the hot-pixel map
    cam.capture_flat_field()
    # 2) choose which corrections to apply to the processed file
    cam.set_dark_correction(True)
    cam.set_hot_pixel_correction(True)   # uses the map built during the dark capture
    cam.set_flat_field_correction(True)
    # 3) ask for the processed companion (this is the "processed file type" switch)
    cam.set_save_processed_h5(True)      # or: cam.set_save_file_type("processed")
    # 4) record — produces raw H5 + a `_proc_*` companion with corrections applied
    cam.start_recording(mode="n_frames", n_frames=100)
finally:
    cam.close()
```

## Methods

| Method | Sends (`cmd-file`) | Effect |
|---|---|---|
| `capture_dark_frame()` | `capture_dark_frame {capture:True}` | Averages a few dark frames (auto-sized from exposure, ≤5 / ≤3 s) → dark reference **and** the derived hot-pixel map. |
| `clear_dark_frame()` | `clear_dark_frame {clear:True}` | Discards the dark reference and the derived hot-pixel map. |
| `set_dark_correction(enabled)` | `dark_correction_enabled {enabled}` | Apply/skip dark subtraction on the processed companion. |
| `set_hot_pixel_correction(enabled)` | `hot_pixel_correction_enabled {enabled}` | Apply/skip hot-pixel replacement (needs a dark capture first). |
| `capture_flat_field()` | `capture_flat_field {capture:True}` | Averages a few frames → flat-field gain map. Illuminate uniformly first. |
| `clear_flat_field()` | `clear_flat_field {clear:True}` | Discards the flat-field map. |
| `set_flat_field_correction(enabled)` | `flat_field_correction_enabled {enabled}` | Apply/skip flat-field gain on the processed companion. |
| `set_save_processed_h5(enabled)` | `save_processed_h5 {enabled}` | Write (or not) the `_proc_*` processed companion. The raw-vs-processed switch. |
| `set_save_file_type("raw"\|"processed"\|"both")` | (wraps `save_processed_h5`) | Convenience: `"raw"` → raw only; `"processed"`/`"both"` → raw + processed companion. |
| `set_save_targets(h5=, isp=)` | `save_targets {h5, isp}` | Choose HDF5 and/or ISP image/video outputs. |

Client-side intent flags (read-only): `dark_correction_enabled`, `hot_pixel_correction_enabled`,
`flat_field_correction_enabled`, `save_processed_h5`, and `dark_correction_stale`.

## Key facts & gotchas (from the cross-camera audit)

- **Capture order matters: set exposure first.** The dark reference is exposure-dependent (dark
  current scales with integration time). One dark capture builds both the dark reference and the
  hot-pixel map.
- **Exposure-change warning is automatic.** If you change exposure after capturing a dark while
  dark/hot-pixel correction is on, `set_exposure_time()` logs a warning and sets
  `cam.dark_correction_stale = True`. Re-`capture_dark_frame()` at the new exposure.
- **Fire-and-forget, no ack.** These Saver toggles are not echoed back, so the calls return
  immediately (no readback). The controller tracks intent locally.
- **Mid-recording behavior differs by command.** `set_save_targets()` sent while a
  recording/snapshot is in progress is **dropped** by the backend (trace log only, no ack). The
  correction toggles (`set_dark_correction` / `set_hot_pixel_correction` /
  `set_flat_field_correction` / `set_save_processed_h5`) are instead **applied live** and change
  *subsequent* processed frames — but the already-open companion's `_proc_<flags>` filename and its
  flags attribute are sampled once at file-create time, so a mid-file flip desyncs the filename from
  the content. Safest: set all corrections/targets **before** `start_recording()`, and for a clean
  change prefer stop → change → restart. Clearing a dark mid-recording likewise desyncs an open
  companion.
- **Processed companion location.** The `_proc_<flags>.h5` lands next to the raw H5 in the session
  `raw_h5/` folder. A folder reader (`mantis_folder` / `mantis_folder_GS`) may pick it up as a
  separate recording — point single-file readers at the specific file, or filter `_proc_`.
- **Camera-family safety.** The correction math is per-pixel and shape-guarded by construction, so
  it is safe across all families. GSense per-half (HG|LG) dark handling happens in the ISP
  serializer (live/display path), independent of this Saver-domain correction.

## Analysis of the output
Both the raw and processed `.h5` carry the standard schema (`camera/frames`,
`camera/integration-time-expected`, `camera/timestamp`), so the
[analysis API](analysis-mantiscam.md) opens either. The processed file additionally encodes the
applied stages in its `_proc_<flags>` suffix (`c`=charge-sharing, `d`=dark, `h`=hot-pixel,
`f`=flat-field).
