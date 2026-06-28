# MantisCam — scientific camera control/acquisition client (GSense / F13-class sensors) over a local MantisCamUnified backend

> **Factory:** `from bsl_universal.instruments import mantisCam` then `mantisCam(device_sn: str = "")`
> **Transport:** ZMQ (localhost TCP, fixed `127.0.0.1:60000` cmd-PUB / `60001` cmd-SUB / `60011` vid-SUB) · **Datasheet:** none on disk · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_mantisCam.py`
>
> **See also:** [mantiscam-corrections](mantiscam-corrections.md) — remote dark / hot-pixel /
> flat-field correction and raw-vs-processed (`save_processed_h5`) file selection.

## When to use this
Use this for scientific-camera image acquisition and recording when a separate **MantisCamUnified** backend process is already running on localhost. It captures single raw or ISP (image-signal-processed) frame snapshots as numpy arrays, sets exposure, computes frame-mean statistics, runs an iterative auto-exposure loop, and records N-frame or until-stop video to disk on the backend. Pick it for camera-based measurements (intensity vs. exposure, image capture, recorded sequences); it is the only camera driver in this skill that speaks the MantisCam ZMQ protocol. It does **not** talk to the camera over USB/VISA directly — all hardware access goes through the backend.

## Construct & tear down
`device_sn` is a **logical label only** (used for logging / `device_id` tracking), **not a hardware serial** — the real serial is discovered live from backend metadata. The factory always connects to the fixed localhost ports; to use non-default ports you must construct `MantisCamCtrl` directly (not exposed via the factory).

```python
from bsl_universal.instruments import mantisCam

# Precondition: the MantisCamUnified backend must be running on
# localhost ports 60000 / 60001 / 60011. Construction will NOT fail if it
# is absent (ZMQ connect is lazy) — the first real call would time out instead.
cam = mantisCam(device_sn="lab-cam-1")
try:
    model, serial = cam.get_camera_name_serial(refresh=True)
    print("camera:", model, serial, "type:", cam.get_camera_type(refresh=False))

    cam.set_exposure_time(25.0, strict=False)      # 25 ms; non-GSense verifies readback
    raw = cam.get_raw_frame(timeout_ms=5000)        # numpy copy, shape (H,W) or (H,W,C)
    print("raw frame:", raw.shape, raw.dtype)
finally:
    cam.close()   # also runs via atexit and __del__/__exit__; idempotent
```

`MantisCamCtrl` is also a context manager (`with mantisCam(...) as cam:`), whose `__exit__` calls `close()` and does **not** suppress exceptions. The constructor blocks ~0.1 s and side-sends two best-effort sync commands on creation: `set_recording_file_name(time_stamp_only=True)` and `set_exposure_time(50.0, strict=False)`.

## Most-used operations

### `get_camera_name_serial(*, refresh: bool = True) -> Tuple[str, str]`
- **Does:** Returns `(model_name, serial_number)`; updates `self.device_id` when a real serial is found.
- **Args:** `refresh: bool` — when True, blocks ~1.5 s to fetch fresh identity (forwarded to `get_camera_identity`/`refresh_hardware_nodes`).
- **Returns:** `tuple[str, str]`; falls back to `("Unknown", "Unknown")` if unknown.
- **Blocks?** Yes when `refresh=True` (~1.5 s).
- **Readback?** Read-only; no hardware state change.
- **Raises:** none specific to this call.
- **Example:** `model, sn = cam.get_camera_name_serial(refresh=True)`

### `get_camera_type(*, refresh: bool = True) -> str`
- **Does:** Returns the camera type string (e.g. `"GSense2020-BSI"`, `"F13-Full"`), or `"Unknown"`. This string drives GSense-specific exposure/auto-exposure branches internally.
- **Args:** `refresh: bool` — default True; blocks ~1.5 s for fresh metadata.
- **Returns:** `str`.
- **Blocks?** Yes when `refresh=True`.
- **Readback?** Read-only.
- **Raises:** none specific.
- **Example:** `t = cam.get_camera_type(refresh=False)`

### `set_exposure_time(exposure_ms: float, *, strict: bool = True, timeout_ms: int = 8000) -> bool`
- **Does:** Sets camera exposure. Sends both `cam`/`exp-00` and `widget`/`exp-00`. **Non-GSense:** polls frame metadata `int-set` and accepts when within `max(1%, 0.1 ms)` of the request. **GSense (no deterministic frame metadata):** cannot verify from a frame, so it blocks for the **mandatory exposure-settle delay** (see the camera-settle rule below), sets `current_exposure_ms = target`, and returns True unconditionally.
- **Args:** `exposure_ms: float` — **milliseconds (ms)**; cast via `float()`, **NO bound or sign validation** (negative/zero forwarded to hardware). `strict: bool` — raise on verify failure, default True. `timeout_ms: int` — verify window in ms, default 8000.
- **Returns:** `bool` — True on set/verify success; False on verify timeout when `strict=False`.
- **Blocks?** Yes. **GSense:** `2*max(prev, new) + min(prev, new) + 1 s` where `prev` = `current_exposure_ms` before the call and `new` = requested exposure (both converted to **seconds**); this is a **floor and is uncapped** — long exposures wait proportionally longer (e.g. 50 ms → 2500 ms ≈ 6.05 s; the 1 s term dominates for short exposures). Non-GSense: up to ~`2*timeout_ms` (two outer attempts) of polling.
- **Readback?** Non-GSense: **YES** (verifies `int-set` within tolerance). GSense: **NO** — assumes success after the settle delay elapses.
- **Raises:** `bsl_type.DeviceTimeOutError` when `strict=True` and verification fails (non-GSense path only).
- **Example:** `cam.set_exposure_time(50.0, strict=False)`

> 🕐 **Mandatory exposure-settle rule (cameras without deterministic frame metadata, e.g. GSense).**
> Such cameras do **not** echo a trustworthy applied-exposure value, so the new integration
> time cannot be confirmed from a frame. After **every** exposure change the driver blocks for
> at least
>
> ```
> delay = 2 × max(prev_exp, new_exp) + min(prev_exp, new_exp) + 1 s
> ```
>
> (exposures in seconds; `prev_exp` = the exposure in effect before the change, `new_exp` = the
> requested exposure). The camera may need additional time to stabilize at the new exposure, so
> this is a **minimum floor and is intentionally uncapped**. `set_exposure_time` already enforces
> it internally on the GSense path; if you change exposure by any **other** route (e.g.
> `set_hardware_node("exp-00", …)`, which has no settle logic), **you must sleep at least this long
> yourself** before trusting the next frame or starting a recording. The first frame(s) read before
> the delay elapses can still be integrating at the old exposure.

### `get_raw_frame(*, timeout_ms: int = 5000, fresh: bool = True, with_metadata: bool = False)`
- **Does:** Returns one **raw** (unprocessed) frame as a numpy copy.
- **Args:** `timeout_ms: int` — ms, default 5000. `fresh: bool` — reset the video SUB socket first to drop stale buffered frames, default True. `with_metadata: bool` — return `(frame, meta_dict)` when True, default False.
- **Returns:** `np.ndarray` (copy; pixel ADU; shape `(H,W)` or `(H,W,C)`) or `(np.ndarray, dict)`.
- **Blocks?** Yes, up to `timeout_ms`. `fresh=True` tears down/rebuilds the video socket and re-registers it on the poller.
- **Readback?** N/A (acquisition).
- **Raises:** `bsl_type.DeviceTimeOutError` if no frame arrives before timeout.
- **Example:** `frame, meta = cam.get_raw_frame(with_metadata=True)`

### `get_isp_frame(frame_name: Optional[str] = None, *, timeout_ms: int = 5000, fresh: bool = True, with_metadata: bool = False)`
- **Does:** Returns one **ISP** (processed, non-raw) frame. If `frame_name` is given, waits for that exact name; if None, returns the first available ISP frame.
- **Args:** `frame_name: str|None` — e.g. `"High Gain"`, `"RGB"`; None = any ISP frame. `timeout_ms: int` default 5000. `fresh: bool` default True. `with_metadata: bool` default False.
- **Returns:** `np.ndarray` (copy) or `(np.ndarray, dict)`.
- **Blocks?** Yes, up to `timeout_ms`; `fresh=True` resets the video socket.
- **Readback?** N/A (acquisition).
- **Raises:** `bsl_type.DeviceTimeOutError` on timeout.
- **Example:** `img = cam.get_isp_frame("RGB", timeout_ms=5000)`

### `get_isp_frame_names(*, timeout_ms: int = 1500, fresh: bool = False, settle_ms: int = 200) -> list[str]`
- **Does:** Observes the live stream and returns sorted unique ISP frame names (seeded with names observed earlier this session). Early-stops `settle_ms` after the last new name.
- **Args:** `timeout_ms: int` — observation window in ms, default 1500. `fresh: bool` — default False (keep False for minimal transport disturbance). `settle_ms: int` — early-stop window in ms, default 200.
- **Returns:** `list[str]` — sorted unique names; **may be empty** if no ISP frame arrives.
- **Blocks?** Yes, up to `timeout_ms`.
- **Readback?** N/A (observation).
- **Raises:** Does **not** raise on empty — returns `[]` and emits a non-recovering link-issue warning.
- **Example:** `names = cam.get_isp_frame_names()`

### `get_frame_mean(frame_name: str, *, sub_frame_type: str = "", timeout_ms: int = 5000) -> Union[float, np.ndarray]`
- **Does:** Returns the mean pixel value for an ISP frame. Prefers metadata `statistics["frame-mean"]` (or `frame-mean-<sub_frame_type>`); otherwise computes `np.mean` over pixels (per-channel for 3D multi-channel frames).
- **Args:** `frame_name: str` — ISP frame name (required, positional). `sub_frame_type: str` — sub-channel suffix e.g. `"red"`, default `""`. `timeout_ms: int` default 5000.
- **Returns:** `float`, or `np.ndarray` (per-channel) for multi-channel frames. Value is in pixel ADU.
- **Blocks?** Yes — fetches one ISP frame (`fresh=True`) up to `timeout_ms`.
- **Readback?** N/A.
- **Raises:** `bsl_type.DeviceTimeOutError` (via underlying `get_isp_frame`) on timeout.
- **Example:** `m = cam.get_frame_mean("High Gain")`

### `run_auto_exposure(*, frame_name: str, target_mean: float = 30000, min_exp_ms: float = 1.0, max_exp_ms: float = 2500.0, max_iter: int = 10, hysteresis: float = 2000, sub_frame_type: str = "", use_max_rgb_channel: bool = False) -> float`
- **Does:** Iterative proportional auto-exposure. Measures frame mean, scales the current target exposure by `target/cur` ratio (GSense subtracts a 1100-ADU black-level offset for the ratio), clamps to `[min_exp_ms, max_exp_ms]`, sets exposure, repeats. Caps the ratio at 0.2 when `cur_mean > 63000`.
- **Args:** `frame_name: str` — feedback ISP frame (keyword-only, required). `target_mean: float` — ADU, default 30000. `min_exp_ms`/`max_exp_ms: float` — ms bounds, default 1.0 / 2500.0. `max_iter: int` default 10. `hysteresis: float` — ADU convergence tolerance, default 2000. `sub_frame_type: str` default `""`. `use_max_rgb_channel: bool` — use max channel instead of mean, default False.
- **Returns:** `float` — final exposure in **ms** (`self.current_exposure_ms`).
- **Blocks?** Yes — up to `max_iter` × (frame fetch + exposure settle).
- **Readback?** Relies on `set_exposure_time` readback, which is skipped/assumed on GSense.
- **Raises:** propagates `bsl_type.DeviceTimeOutError` from `get_frame_mean` if a feedback frame times out.
- **Example:** `final_ms = cam.run_auto_exposure(frame_name="High Gain", target_mean=30000)`

### `start_recording(*, mode: str = "n_frames", n_frames: int = 10, wait_until_done: bool = True, frames_per_file: Optional[int] = None, strict: bool = True) -> bool`
- **Does:** Starts recording to disk on the backend. `n_frames` mode sets `frames_per_file = n_frames` and stop-condition `"File Full"`; `until_stop` mode uses `frames_per_file` (default 1000) and `"Click Stop Recording"`. Waits up to 5 s for the backend to report recording started; if `n_frames` + `wait_until_done`, also waits for completion.
- **Args:** `mode: str` — `"n_frames"` or `"until_stop"` (lowercased; any other value → `ValueError`). `n_frames: int` — clamped `>=1` (`max(1, int(...))`), default 10. `wait_until_done: bool` default True. `frames_per_file: int|None` — `until_stop` only, default 1000 (clamped `>=1`). `strict: bool` — raise on timeout, default True.
- **Returns:** `bool` — True on success; False on timeout when `strict=False`.
- **Blocks?** Yes: up to 5 s to confirm start; if waiting for completion, up to `max(20.0, target_exposure_ms*frames/500 + 20.0)` s (note: uses last-**requested** exposure, not measured).
- **Readback?** Confirms start via the `is_recording` flag (backend `file`/`recording_status`); confirms completion via `is_recording` going False.
- **Raises:** `ValueError` for an unsupported mode (note: plain `ValueError`, **not** a `bsl_type.*` exception); `bsl_type.DeviceTimeOutError` when `strict=True` and start/completion times out.
- **Example:** `cam.start_recording(mode="n_frames", n_frames=10, wait_until_done=True, strict=False)`

### `stop_recording(*, timeout_sec: float = 15.0, strict: bool = True) -> bool`
- **Does:** Sends `record=False` and waits for `is_recording` to clear.
- **Args:** `timeout_sec: float` — seconds, default 15.0. `strict: bool` default True.
- **Returns:** `bool` — True if acknowledged; False on timeout when `strict=False`.
- **Blocks?** Yes, up to `timeout_sec`.
- **Readback?** Waits for `is_recording=False` ack.
- **Raises:** `bsl_type.DeviceTimeOutError` when `strict=True` and the stop is not acknowledged.
- **Example:** `cam.stop_recording(strict=False)`

## Image-correction & processed-H5 save controls

`MantisCamCtrl` also exposes 10 methods that drive the MantisCamUnified **Saver's** dark /
hot-pixel / flat-field correction and the raw-vs-processed (`_proc_*`) file switch:
`capture_dark_frame`, `clear_dark_frame`, `set_dark_correction`, `set_hot_pixel_correction`,
`capture_flat_field`, `clear_flat_field`, `set_flat_field_correction`, `set_save_processed_h5`,
`set_save_file_type`, `set_save_targets`. They are **fire-and-forget** (no readback) and affect
**only the processed-H5 companion**, never the raw H5 or live display.

> 📄 **Full per-method docs, the capture-order recipe, and the cross-camera gotchas live in
> [mantiscam-corrections](mantiscam-corrections.md).** One-line summaries are in the method index
> below; the exposure-staleness interaction is in **Safety & gotchas**.

## Full method index

| name | kind | purpose | key args (units) | returns |
|---|---|---|---|---|
| `mantisCam` (factory) | function | Build + return a connected `MantisCamCtrl` via registry/runtime | `device_sn: str` (label only) | `MantisCamCtrl` |
| `MantisCamCtrl.__init__` | method | Construct client, connect transport, send 2 sync cmds | `device_sn=""`, `port_cmd_pub=60000`, `port_cmd_sub=60001`, `port_vid_sub=60011`, `*, log_level="TRACE"` (discarded) | `None` |
| `close` | method | Close sockets + terminate ZMQ ctx (idempotent) | — | `None` |
| `__enter__` / `__exit__` | method | Context manager; `__exit__` calls `close()`, returns False | — | `MantisCamCtrl` / `False` |
| `set_monitor_callbacks` | method | Register connected/warning/disconnected callbacks | `*, on_connected`, `on_warning`, `on_disconnected` (`Callable[[str,str,str,str],None]|None`) | `None` |
| `get_camera_identity` | method | Identity dict (model/serial/vendor/firmware/sensor/...) | `*, refresh: bool = True` | `dict` (may be `{}`) |
| `get_camera_name_serial` | method | `(model, serial)`; updates `device_id` | `*, refresh: bool = True` | `tuple[str,str]` |
| `get_camera_type` | method | Camera type string or `"Unknown"` | `*, refresh: bool = True` | `str` |
| `refresh_hardware_nodes` | method | Query node catalog; fabricates fallback on timeout | `*, timeout_ms: int = 1500` (ms) | `dict` |
| `get_hardware_nodes` | method | Cached node catalog (refresh if empty/asked) | `*, refresh: bool = False` | `dict` |
| `set_hardware_node` | method | Write a node by catalog name (fire-and-forget) | `node_name: str`, `value: Any = None` (units per node) | `None` |
| `set_save_directory` | method | Set backend recording root dir | `save_dir: str` (path) | `None` |
| `set_recording_file_name` | method | Set filename mode (Timestamp / Custom+name) | `file_name: str = "video"`, `*, time_stamp_only: bool = False` | `None` |
| `set_recording_folder` | method | Set folder mode (none/Timestamp/Custom) | `folder_name: str = "video"`, `*, create_new_folder=True`, `time_stamp_only=False` | `None` |
| `start_recording` | method | Start n_frames/until_stop recording | `*, mode="n_frames"`, `n_frames=10`, `wait_until_done=True`, `frames_per_file=None`, `strict=True` | `bool` |
| `stop_recording` | method | Stop recording, wait for ack | `*, timeout_sec: float = 15.0`, `strict=True` | `bool` |
| `capture_dark_frame` | method | Capture averaged dark ref (+ hot-pixel map) on backend | — (cover sensor first) | `None` |
| `clear_dark_frame` | method | Discard dark ref + derived hot-pixel map | — | `None` |
| `set_dark_correction` | method | Toggle dark subtraction (processed-H5 only; needs dark) | `enabled: bool` | `None` |
| `set_hot_pixel_correction` | method | Toggle hot-pixel correction (processed-H5; needs dark) | `enabled: bool` | `None` |
| `capture_flat_field` | method | Capture averaged flat-field ref (illuminate first) | — | `None` |
| `clear_flat_field` | method | Discard flat-field ref | — | `None` |
| `set_flat_field_correction` | method | Toggle flat-field gain (processed-H5; needs flat) | `enabled: bool` | `None` |
| `set_save_processed_h5` | method | Also write `_proc_*` corrected HDF5 companion | `enabled: bool` | `None` |
| `set_save_file_type` | method | `"raw"`/`"processed"`/`"both"` → companion on/off | `file_type: str` | `None` |
| `set_save_targets` | method | Choose Saver outputs (HDF5 / ISP); ignored mid-record | `*, h5=True`, `isp=True` | `None` |
| `set_exposure_time` | method | Set exposure, verify (non-GSense) / mandatory settle-delay (GSense) | `exposure_ms: float` (ms), `*, strict=True`, `timeout_ms=8000` | `bool` |
| `get_raw_frame` | method | One raw frame snapshot | `*, timeout_ms=5000`, `fresh=True`, `with_metadata=False` | `np.ndarray` or `(ndarray, dict)` |
| `get_isp_frame` | method | One ISP frame snapshot | `frame_name=None`, `*, timeout_ms=5000`, `fresh=True`, `with_metadata=False` | `np.ndarray` or `(ndarray, dict)` |
| `get_isp_frame_names` | method | Sorted unique live ISP frame names | `*, timeout_ms=1500`, `fresh=False`, `settle_ms=200` | `list[str]` |
| `get_frame_mean` | method | Mean of an ISP frame (ADU) | `frame_name: str`, `*, sub_frame_type=""`, `timeout_ms=5000` | `float` or `np.ndarray` |
| `run_auto_exposure` | method | Iterative proportional auto-exposure | `*, frame_name: str`, `target_mean=30000`, `min_exp_ms=1.0`, `max_exp_ms=2500.0`, `max_iter=10`, `hysteresis=2000`, `sub_frame_type=""`, `use_max_rgb_channel=False` | `float` (ms) |
| `FileNamingMode` | nested enum | `CUSTOM="Custom"`, `TIMESTAMP="Timestamp"` (used by `set_recording_file_name` only) | — | enum |
| `is_recording` | attribute | Backend recording status flag | — | `bool` |
| `current_exposure_ms` | attribute | Last accepted/assumed exposure (ms) | — | `float` |
| `dark_correction_enabled` | attribute | Intent flag: dark subtraction on processed-H5 | — | `bool` |
| `hot_pixel_correction_enabled` | attribute | Intent flag: hot-pixel correction on processed-H5 | — | `bool` |
| `flat_field_correction_enabled` | attribute | Intent flag: flat-field gain on processed-H5 | — | `bool` |
| `save_processed_h5` | attribute | Intent flag: also write `_proc_*` companion | — | `bool` |
| `dark_correction_stale` | attribute | Set True when exposure changed since dark capture | — | `bool` |
| `device_sn` | attribute | Logical label passed at construction | — | `str` |
| `device_id` | attribute | Discovered serial (or `"Unknown"`/label) | — | `str` |

Private/internal helpers (surfaced for completeness — do not call directly): `_connect_or_raise`, `_recover_transport`, `_reset_video_socket`, `_safe_send`, `_poll`, `_drain_nonblocking`, `_consume_cmd`, `_consume_vid`, `_wait_for_frame`, `_decode_frame`, `_update_exposure_from_meta`, `_exposure_matches`, `_exposure_settle_delay_sec` (computes the GSense settle delay `2*max(prev,new)+min(prev,new)+1 s`), `_note_exposure_change_for_dark` (flags `dark_correction_stale` when exposure moves after a dark capture), `_as_numeric`, `_fallback_hardware_nodes`, `_is_gsense_camera`, `_camera_type_token`, `_is_backend_reachable`, `_handle_link_issue`, `_publish_monitor_state`, `_monitor_*`. The class `_FallbackMessenger` is an internal ZMQ messenger used only when the project `MantisCam.Messenger`/`mantiscam_gui.Messenger` import is unavailable.

## Units, ranges & limits
- **Transport (fixed):** host `127.0.0.1`; ports `port_cmd_pub=60000`, `port_cmd_sub=60001`, `port_vid_sub=60011` (cast via `int()`, **no range validation**). The public `mantisCam()` factory cannot change ports — construct `MantisCamCtrl` directly for non-default ports.
- **Exposure:** `set_exposure_time` takes **ms**, with **no lower/upper bound or sign check** (negative/zero accepted and sent). Verify tolerance (non-GSense) = `max(1% of requested, 0.1 ms)`. **GSense settle delay (no deterministic metadata) = `2*max(prev, new) + min(prev, new) + 1 s`** (exposures in seconds; `prev` = exposure before the change, `new` = requested), a **floor with no upper cap** — negative `prev`/`new` clamp to 0 so the delay never drops below 1 s. (Replaces the older `min(max(ms/1000,0.02)*2+0.25, 3.0)` cap.)
- **Auto-exposure:** `target_mean` default 30000 ADU; exposure clamped to `[min_exp_ms=1.0, max_exp_ms=2500.0]` ms; `max_iter=10`; `hysteresis=2000` ADU; ratio forced to 0.2 when `cur_mean > 63000`; GSense black-level offset = 1100 ADU subtracted for the ratio computation.
- **Recording:** `mode ∈ {"n_frames", "until_stop"}` (lowercased; else `ValueError`). `n_frames` and `frames_per_file` clamped `>=1`. `frames_per_file` default for `until_stop` = 1000. Stop-condition literals: `"File Full"` (n_frames) / `"Click Stop Recording"` (until_stop). Start wait ≤5 s; completion wait `max(20.0, target_exposure_ms*frames/500 + 20.0)` s; `stop_recording` default timeout 15.0 s.
- **File/folder modes:** `FileNamingMode.CUSTOM="Custom"`, `TIMESTAMP="Timestamp"`. `set_recording_folder` mode literals: `"Do Not Create New Folder"` / `"Timestamp"` / `"Custom"` (raw strings, not all in the enum).
- **Corrections / processed-H5 (Saver):** dark capture auto-sizes from exposure (≤5 frames / ~3 s averaged) and also yields the hot-pixel map; `set_save_file_type` accepts `{"raw","processed","both"}` (else `DeviceOperationError`); `set_save_targets(h5, isp)` is ignored by the backend while a recording/snapshot is in progress. All correction/save toggles are intent flags sent fire-and-forget (no readback). Dark/flat references and the hot-pixel map live in the backend Saver, not the controller.
- **Hardware-node value types observed:** `float`, `int`, `bool`, `str`, `action`; grouped command families `{spi, dac, dly}`. Fallback catalog nodes (synthesized on timeout): `exp-00` (ms, float), `acq-fps` (int), `high-gain` (bool, if `has_high_gain`), `adc-gain` (int, if `has_adc_gain`), `coolingtemp-setpoint` (°C, float) + `tempcontrol-mode` (str) if `has_tec`.
- **Class constants:** `TIMEOUT_SEC=60.0` (defined but **unused** in any method flow), `_POLL_STEP_MS=25`, `_SEND_RETRIES=3`, monitor throttle 2.0 s (connected) / 3.0 s (warning/disconnected). `log_level` constructor arg is accepted then discarded.
- **Frame data:** `np.ndarray` copies in pixel ADU; shape `(H,W)` or `(H,W,C)`. Transport uses `multiprocessing.shared_memory` (`_shm_ref`) or dill/pickle-encoded dumps.

## Safety & gotchas
- **Recovery layer:** `dev.safe.<method>()` retries a method through the runtime recovery wrapper (`.safe` is method-only — see [runtime & construction](00-runtime-and-construction.md)). This is separate from the driver's own self-healing transport (`_safe_send` retries 3× with full socket recovery; eventually raises `bsl_type.DeviceOperationError`; frame timeouts raise `bsl_type.DeviceTimeOutError`).
- **Backend dependency:** construction does **not** verify the MantisCamUnified backend is running (ZMQ connect is lazy). A live, "connected"-looking object can exist with no backend; the first real call then fails with a timeout rather than a clear connection error. `_is_backend_reachable()` exists internally but is not used at construction.
- **`device_sn` is a label, not a serial.** The real serial is discovered live and written into `device_id`. Before discovery, identity getters may return `"Unknown"` or `{}`.
- **GSense exposure is not verified — it is settled by a mandatory blocking delay instead.** GSense has **no deterministic frame metadata**, so `set_exposure_time` skips metadata verification, **blocks for `2*max(prev,new)+min(prev,new)+1 s`** (uncapped) to let the sensor stabilize, then sets `current_exposure_ms = target` and returns True unconditionally — so `current_exposure_ms` and `run_auto_exposure` results reflect the **requested** value, not a confirmed readback. `start_recording`'s completion-timeout math and `run_auto_exposure` both trust this possibly-unverified value. If you change exposure by any path **other** than `set_exposure_time` (e.g. `set_hardware_node("exp-00", …)`), apply the same settle delay yourself before trusting frames.
- **Most setters are fire-and-forget:** `set_save_directory`, `set_recording_file_name`, `set_recording_folder`, `set_hardware_node`, and **all image-correction / processed-H5 controls** (`capture_dark_frame`, `clear_dark_frame`, `set_dark_correction`, `set_hot_pixel_correction`, `capture_flat_field`, `clear_flat_field`, `set_flat_field_correction`, `set_save_processed_h5`, `set_save_file_type`, `set_save_targets`) send with no readback. Only non-GSense `set_exposure_time` and the recording start/stop ack provide confirmation.
- **Corrections are processed-H5-only and order-dependent.** Dark/hot-pixel/flat-field correction affects **only** the `_proc_*` companion (never the raw H5 or live display), and only when `save_processed_h5` is on with the `"h5"` target enabled; the `*_correction_enabled` calls are intent and need their reference captured first. Full recipe and cross-camera notes: [mantiscam-corrections](mantiscam-corrections.md).
- **The dark reference is exposure-dependent.** Changing exposure after a dark capture sets `dark_correction_stale = True` and (if dark/hot-pixel correction is active) logs a warning — dark current scales with integration time, so **re-capture the dark at the new exposure** for accurate correction. This is checked inside `set_exposure_time` via `_note_exposure_change_for_dark`, so it fires only for that exposure path (not for `set_hardware_node("exp-00", …)`).
- **`set_hardware_node` is unguarded.** It can drive arbitrary registers — including the **TEC cooling setpoint** (`coolingtemp-setpoint`, °C), gains, and raw `spi`/`dac`/`dly` timing/DAC registers — with **no bounds checking and no readback**. Value validity is entirely the caller's responsibility. For grouped commands (`spi`/`dac`/`dly`) it rebuilds the full group from cached sibling `value`s; stale/`None` cached values can be written into hardware registers alongside your change. Do **not** rely on a successful return meaning the camera applied the value.
- **`refresh_hardware_nodes`/`get_camera_identity` can return fabricated data on timeout** (synthetic fallback catalog `schema="mantiscam.hardware.nodes.v2"`, or `{}`). `set_hardware_node` may then operate against nodes that do not reflect real hardware.
- **`fresh=True` (default) on frame getters** tears down and rebuilds the video SUB socket each call to drop stale frames; frequent calls churn the poller registration. Pass `fresh=False` when sampling rapidly and stale frames are acceptable.
- **Blocking surprises:** constructor sleeps ~0.1 s; GSense `set_exposure_time` blocks for the **uncapped** settle delay `2*max(prev,new)+min(prev,new)+1 s` (≈1.1 s for short exposures, but ≈6 s when moving to a 2500 ms exposure — and `run_auto_exposure` pays this on every iteration); `start_recording` can block up to `max(20, target_exposure_ms*frames/500 + 20)` s; frame getters block up to `timeout_ms`.
- **Exception-type inconsistency:** `start_recording` raises plain `ValueError` (not `bsl_type.*`) for an unsupported mode — callers filtering only on `bsl_type.CustomError` will miss it.
- **Recording writes to disk** on the backend; `start_recording` produces files. No high-power emitter, arc lamp, or motion homing exists in this module, but the TEC cooling setpoint (via `set_hardware_node`) is a real thermal actuator — apply only validated setpoints.
- **`run_auto_exposure` early-returns** when the clamped `next_exp` lands exactly on `min_exp_ms` or `max_exp_ms`, which can stop the loop before true convergence; its convergence test uses raw mean while the step uses the GSense offset-corrected value (minor inconsistency on GSense).
- **Monitor callbacks** (`set_monitor_callbacks`) receive `(model, device_type, serial, detail)`; their exceptions are silently swallowed.

## Audit notes (2026-06-28)
- **Fixed:** No P0/P1 defects were found/fixed in the original 2026-06-28 audit.
- **Changed (2026-06-28):** The GSense (no-deterministic-metadata) exposure path now blocks for a
  **mandatory, uncapped settle delay** `2*max(prev,new)+min(prev,new)+1 s` (helper
  `_exposure_settle_delay_sec`), replacing the previous `min(max(ms/1000,0.02)*2+0.25, 3.0)` ≤3 s
  guard. Rationale: the camera may need additional time to stabilize at a new exposure, and the
  old 3 s cap was too short for long exposures (a frame integrating at the old exposure could still
  be in flight). Behavioral impact: `run_auto_exposure` and the constructor's initial
  `set_exposure_time(50.0)` now block longer on GSense (≈1.1 s for short exposures, ≈6 s when moving
  to 2500 ms). Non-GSense (metadata-verified) behavior is unchanged.
- **Known / deferred:**
  - **State-changing hardware writes via `set_hardware_node` have no readback verification.** It is fire-and-forget: a dropped or rejected command leaves the caller believing the value was applied. This is a silent-failure / wrong-state hazard especially for safety-relevant nodes (TEC `coolingtemp-setpoint`, gains, `spi`/`dac`/`dly` registers). Do **not** treat a successful return as confirmation the camera accepted the value — independently re-read the node catalog/metadata if correctness matters, and validate values yourself (no bounds checking is performed). Note the related GSense `set_exposure_time` path also reports success without readback.
