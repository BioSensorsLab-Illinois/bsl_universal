# BSC203 + HDR50 Rotation Stage — Thorlabs 3-channel APT stepper controller (BSC203) driving the HDR50 motorized rotary stage (open-loop angular positioning)

> **Factory:** `from bsl_universal.instruments import inst` then `inst.BSC203_HDR50()` (takes **no arguments**). The driver class is also importable directly: `from bsl_universal.instruments import BSC203_HDR50` then `BSC203_HDR50(serial_port=None, vid=None, pid=None, manufacturer=None, product=None, serial_number="70", location=None, home=False, invert_direction_logic=False, swap_limit_switches=True)`.
> **Transport:** USB-SDK — Thorlabs APT protocol over USB-serial (pyserial), driven by a background asyncio event loop (vendored `_thorlabs_apt_device`) · **Datasheet:** `HDR50-Manual.pdf` (in `_datasheet/`) · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_BSC203.py`

## When to use this
Pick this driver when an experiment needs to **rotate a sample/optic to a controlled angle** on the Thorlabs HDR50 rotary stage mounted in a BSC203 rack — e.g. angular sweeps for polarization, BRDF/angle-resolved scatter, or pointing a mounted component. It exposes an angle/step abstraction (0.45° per step, 800 steps/revolution) layered on the raw APT motor API. Control is **open loop**: the angle is dead-reckoned in software with no encoder feedback, so it is suitable for repeatable relative moves and coarse absolute positioning that you re-home regularly, **not** for high-accuracy absolute pointing without frequent re-homing. See [runtime & construction](00-runtime-and-construction.md) for the factory/registry mechanics shared by all instruments.

## Construct & tear down
```python
from bsl_universal.instruments import inst

# Factory discovers the FIRST APT controller whose USB serial begins with "70",
# opens it, sets velocity/home params, and performs a BLOCKING initial home.
# The stage WILL physically rotate to mechanical 0 on construction.
stage = inst.BSC203_HDR50()
try:
    stage.step(10)                               # +10 steps = +4.5 deg, blocks until idle
    angle = stage.get_curr_angle(return_angle=True)   # must pass return_angle=True
    print("estimated angle:", angle, "deg")
finally:
    stage.close()
```
**Device selection:** there is no `device_sn` argument on the factory. Selection is by USB **serial-number regex**, which defaults to `"70"` (`serial_number="70"`). The first enumerated APT controller whose serial starts with `70` is opened — in a multi-controller rig this is whichever matching device appears first, with no model check that it is actually an HDR50. To target a specific unit, construct the class directly and pass a more specific `serial_number` / `serial_port` / `location`.

## Most-used operations
Workflow order: construct (auto-homes) → `step` / `set_angle` to move → `get_curr_angle` to read the estimate → `home` periodically → `close`.

### `step(stepnum, called_by_home=False)`
- **Does:** Moves **relative** by `stepnum` increments of 0.45°. `stepnum == 0` just blocks until idle. For `1..100` it moves at normal speed; for `>100` it temporarily raises max velocity (200·`MOTOR_FREV_STEP`) for the move then restores it. Updates the software step counter modulo 800.
- **Args:** `stepnum` (int, unit = 0.45° steps; **no upper bound** — large values spin multiple revolutions). `called_by_home` (bool, internal flag; when True skips speed-shaping and the counter update — do not set this yourself).
- **Returns:** `None` (returns the result of `_blocker()`).
- **Blocks?** Yes — blocks via `_blocker()` until motion flags clear.
- **Readback?** No. Only the software counter `__curr_step` is updated optimistically; hardware position is never read to confirm.
- **Raises:** No typed exception. If the counter is uninitialized (`None`, never homed) the `__curr_step += stepnum` line raises `TypeError`, which a bare `except` swallows and then calls `home()` **after the move already executed** (logs "did not home on startup, homing...").
- **Example:** `stage.step(-1)` ⚠ does **not** move −0.45°; negatives are remapped to `800 - abs(stepnum)`, so `step(-1)` moves **+799 steps (~+359.55°)** with only a warning.

### `set_angle(angle, precision=False)`
- **Does:** Moves to an **absolute** angle. Quantizes the request **down** to the nearest 0.45° step (`doable_step = floor(angle/0.45)`). With `precision=False` it issues a relative move of `doable_step - current_step`. With `precision=True` it first `home()`s, then steps to `doable_step` from 0.
- **Args:** `angle` (degrees; declared `int` but a float is accepted and floored; **no explicit range clamp** in code). `precision` (bool; `False` = do not home first — faster, drift-prone; `True` = home then absolute step — accurate. Default `False`).
- **Returns:** `None` (returns `_blocker()`).
- **Blocks?** Yes. With `precision=True` it also performs a full home first (extra motion + time).
- **Readback?** No. Final position is not verified against hardware; success is only logged.
- **Raises:** With `precision=False`, computes `doable_step - self.__curr_step`; if the stage has **not been homed** (`__curr_step is None`) this subtraction raises `TypeError` **before** `step()` is reached (no guard here — see Audit notes). Prefer `precision=True`, or call `home()` first, if there is any chance the counter is unknown.
- **Example:** `stage.set_angle(45, precision=True)` rotates to ~45.0° after homing. `stage.set_angle(0.5)` warns and moves to 0.45° (floored).

### `home(bay=0, channel=0)`
- **Does:** Optimized re-home. If never homed (`__curr_step is None`) it falls back to a plain mechanical home (`_home`). Otherwise computes `stepnum = 800 - __curr_step`; if `stepnum >= 750` (already near 0) it does a plain `_home()`; else it raises max velocity to **1000·`MOTOR_FREV_STEP`** ("crazy mode"), fast-forwards `stepnum-10` steps, restores velocity, then mechanical-homes. Resets `__curr_step = 0`.
- **Args:** `bay` (int, 0-based; only `0` is valid on this device — `x=1`). `channel` (int, 0-based; only `0` valid). Note: the crazy-mode/speed branch **hardcodes bay=0, channel=0**, so non-zero args are partially ignored.
- **Returns:** `None` (returns `_blocker()`).
- **Blocks?** Yes; can be long. Crazy mode spins at very high velocity.
- **Readback?** No. Sets `__curr_step = 0` unconditionally; does not read `status['homed']` to confirm the home actually completed.
- **Raises:** No longer raises on the un-homed (`None`) path — see Audit notes (Fixed).
- **Example:** `stage.home()` — re-establishes the 0° reference; the marking should point at 0. **Keep the stage clear** (docstring: "DON'T touch the stage").

### `get_curr_angle(return_angle=False)`
- **Does:** Reports the **open-loop estimated** angle from the software counter (`__curr_step * 0.45`) and logs it. Non-blocking. If never homed (counter `None`) logs an error and returns `None`.
- **Args:** `return_angle` (bool; `False` (default) = log only and return `None`; `True` = return the angle as a float).
- **Returns:** `float` degrees when `return_angle=True`; otherwise `None`.
- **Blocks?** No. Docstring warns "do not SPAM" (status is polled in the background).
- **Readback?** No — does **not** query hardware; returns the dead-reckoned estimate only, with no guarantee it matches the physical position.
- **Raises:** None.
- **Example:** `a = stage.get_curr_angle(return_angle=True)` ⚠ `a = stage.get_curr_angle()` silently returns `None`.

### `reset_stage(rehome=True)` / `reconnect(rehome=True)`
- **Does:** Recover motion state. `reset_stage` is a thin alias delegating to `reconnect`. With `rehome=True` calls `home()`; with `rehome=False` just blocks until idle. **Does not re-open the USB/serial port** despite the name.
- **Args:** `rehome` (bool, default `True`; `True` = re-home during recovery, `False` = only wait for idle).
- **Returns:** `bool` — `True` on success, `False` (and logs `type(exc)` only) on any caught exception.
- **Blocks?** Yes when it homes or blocks.
- **Readback?** No.
- **Raises:** Catches all exceptions internally and returns `False`.
- **Example:** `if not stage.reset_stage(): ...` — note this cannot recover a physically dropped connection.

### `close()`
- **Does:** Closes the controller — stops all channels, stops the asyncio loop, joins the background thread, closes the serial port (via `super().close()`), inside a `try/except` that **swallows all errors**.
- **Args:** none.
- **Returns:** `None`.
- **Blocks?** Briefly (thread join / loop stop).
- **Readback?** N/A.
- **Raises:** Never — any teardown failure is silently suppressed (the base `close()` is idempotent, so a double-close is safe).
- **Example:** `stage.close()` — always call in a `finally`.

## Full method index
| name | kind | purpose | key args (units) | returns |
| --- | --- | --- | --- | --- |
| `inst.BSC203_HDR50()` | factory (function) | Discover/open first `"70…"` APT controller, set params, initial blocking home | none | `BSC203_HDR50` driver (open & homed) |
| `BSC203_HDR50(...)` | constructor | Direct construction with explicit matchers | `serial_port, vid, pid, manufacturer, product, serial_number="70", location, home=False, invert_direction_logic=False, swap_limit_switches=True` | instance |
| `step` | method | Relative move in 0.45° steps (speed-shaped >100) | `stepnum` (int, 0.45° steps), `called_by_home` (bool, internal) | `None` |
| `set_angle` | method | Absolute move; floors angle to 0.45° grid | `angle` (deg), `precision` (bool) | `None` |
| `home` | method | Optimized/crazy-mode re-home; resets counter to 0 | `bay=0, channel=0` (0-based; only 0 valid) | `None` |
| `get_curr_angle` | method | Report open-loop estimated angle | `return_angle` (bool) | `float` deg or `None` |
| `reconnect` | method | Recover (re-home or wait); does NOT re-open port | `rehome` (bool) | `bool` |
| `reset_stage` | method | Alias of `reconnect` | `rehome` (bool) | `bool` |
| `close` | method | Teardown; swallows exceptions | none | `None` |
| `status` | attribute (inherited) | Live polled status dict for bay0/ch0 (`moving_forward`, `moving_reverse`, `homed`, `position`, `motion_error`, …) | n/a | `dict` |
| `MOTOR_STAGE_RATIO` | class const | Gearbox ratio | n/a | `66` |
| `MOTOR_FREV_STEP` | class const | Microsteps per motor revolution | n/a | `409600` |
| `MOTOR_RUN_STEP` | class const | Microsteps per 0.45° software step | n/a | `33792` |
| `_home` | method (private, surfaced) | Plain mechanical home; sets counter to 0 | `bay=0, channel=0` | `None` |
| `_is_moving` | method (private, surfaced) | True if `moving_forward`/`moving_reverse` (after 0.3s sleep) | none | `bool` |
| `_blocker` | method (private, surfaced) | Block until motion flags clear (0.3s + 0.1s poll) | none | `None` |
| `set_velocity_params` | method (inherited) | Set acceleration / max_velocity (raw counts) | `acceleration` (counts/s²), `max_velocity` (counts/s), `bay=0, channel=0` | `None` |
| `set_home_params` | method (inherited) | Configure homing velocity/offset/direction | `velocity` (counts/s), `offset_distance` (microsteps), `direction='reverse'`, `bay, channel` | `None` |
| `move_relative` / `move_absolute` | method (inherited) | Raw APT moves in microsteps — **non-blocking**, bypass angle abstraction | `distance`/`position` (microsteps), `now`, `bay, channel` | `None` |
| `stop` | method (inherited) | Stop motion | `immediate` (bool), `bay, channel` | `None` |
| `set_enabled` | method (inherited) | Enable/disable a channel | `state` (bool), `bay, channel` | `None` |
| `set_jog_params` / `move_jog` / `move_velocity` | method (inherited) | Jog / continuous-velocity motion | various, microsteps/counts | `None` |
| `set_power_params` | method (inherited, BSC) | Rest/move power factors | `rest_factor`, `move_factor` (0–100 %) | `None` |
| `set_loop_params` / `set_move_params` / `set_trigger` | method (inherited) | Low-level APT config | various | `None` |

> The inherited APT methods (`move_relative`, `move_absolute`, `stop`, `set_velocity_params`, `set_home_params`, `set_enabled`, jog/velocity, power/loop/trigger) are public and callable but **bypass the angle abstraction and do not update `__curr_step`**. Mixing them with `step`/`home`/`set_angle` corrupts the software angle tracking. `_home`/`_is_moving`/`_blocker` are private helpers surfaced here for completeness — prefer the public `home`/`step`/`set_angle`.

## Units, ranges & limits
- **Angular resolution:** 0.45° per software step; **800 steps per full revolution** (`800 × 0.45° = 360°`).
- **Microsteps:** `MOTOR_STAGE_RATIO = 66`, `MOTOR_FREV_STEP = 409600` microsteps/motor-rev ⇒ `66 × 409600 = 27,033,600` microsteps per stage revolution; `MOTOR_RUN_STEP = int(0.45/360 × 66 × 409600) = 33792` microsteps per 0.45° step.
- **Software counter:** `__curr_step` is tracked modulo 800 (range 0–799). It is `None` until the first successful home.
- **`step` speed shaping:** `stepnum` 1–100 → `max_velocity = 100·MOTOR_FREV_STEP` (= 40,960,000 counts/s); `>100` → `200·MOTOR_FREV_STEP` (= 81,920,000) for the move, then restored.
- **`home` crazy-mode:** `max_velocity = 1000·MOTOR_FREV_STEP` (= 409,600,000 counts/s) when `__curr_step > 50` (i.e. `stepnum = 800 − __curr_step < 750`).
- **Init velocity/home params (set per bay/channel at construction):** `acceleration = MOTOR_FREV_STEP//10 = 40960` counts/s²; `max_velocity = 100·MOTOR_FREV_STEP`; home `velocity = 100·MOTOR_FREV_STEP`, `offset_distance = 224000` microsteps.
- **Channels:** `x = 1` is hardcoded (BSC203 docstring notes "should be x = 3"), so **only bay 0 / channel 0** are enabled and valid; other `bay`/`channel` indices are largely ineffective.
- **Blocking timing:** `_blocker()` sleeps 0.3 s then polls every 0.1 s; `_is_moving()` sleeps 0.3 s before reading flags.
- **`set_angle` quantization:** floors (never rounds up) to the 0.45° grid; e.g. 0.50° → 0.45°.
- **Inherited `set_power_params`:** `rest_factor`/`move_factor` are 0–100 percent.
- No explicit min/max angle clamp exists in the wrapper; `step`/`set_angle` will accept and execute large or out-of-intuition values.

## Safety & gotchas
- **Instantiation moves hardware.** `inst.BSC203_HDR50()` **physically homes the stage to mechanical 0 on construction** via the explicit `_home()` call at the end of `__init__`. (The constructor passes `home=False` to the base APT driver, so the base startup block — which would both `set_enabled(True)` and schedule an async home ~1.0 s after port open — does **not** run; homing is done solely by the explicit `_home()`.) Keep hands/optics/cabling clear before constructing.
- **Open-loop, no readback.** Position is dead-reckoned in software; the driver never reads `status['position']`/`status['homed']` to correct or verify moves. `get_curr_angle` returns an **estimate**, not a measurement. Re-home regularly (the driver itself logs this warning at startup). Missed steps or stalls silently desynchronize the estimate from reality.
- **Negative `step` is a trap.** `step(-1)` does **not** move backward — it remaps to `800 − abs(stepnum)` = +799 steps (~+359.55°). To move backward, home and use absolute positioning, or pass a positive complement deliberately.
- **`get_curr_angle()` returns `None` unless `return_angle=True`.** A bare `a = stage.get_curr_angle()` silently yields `None`.
- **Counter-unknown (`None`) hazard.** `__curr_step` is `None` until the first successful home. `home()` now handles this safely (falls back to a full mechanical home — see Audit notes). `set_angle(precision=False)` does **not** — it will raise `TypeError`. `step()` swallows the error but only **after** moving against an unknown reference. When in doubt, call `home()` first or use `set_angle(..., precision=True)`.
- **Crazy-mode velocity.** `home()` may spin at `1000·MOTOR_FREV_STEP` (very fast). Docstring: "DON'T touch the stage." Ensure the rotation path is clear.
- **Don't mix raw moves with the angle API.** Inherited `move_relative`/`move_absolute`/`stop`/jog/velocity are non-blocking and do **not** update `__curr_step`; mixing them corrupts angle tracking. Stick to `step`/`set_angle`/`home` for tracked motion.
- **`reconnect`/`reset_stage` do not reconnect the transport.** They only re-home or wait for idle; a physically dropped USB connection is not recovered, and failures are logged with `type(exc)` only (message discarded).
- **Silent teardown.** `close()` and `__del__` swallow all exceptions; a failed shutdown (thread/port leak) is invisible. Base `close()` is idempotent, so double-close is safe.
- **Device discovery is by serial prefix `"70"`** with no model verification — in a multi-controller rig it opens whichever matching device enumerates first.
- **Recovery layer.** Use `dev.safe.<method>()` to retry a transient failure of any public method (e.g. `stage.safe.home()`, `stage.safe.set_angle(45)`). `.safe` is **method-only** (not for attribute reads like `status`); see [runtime & construction](00-runtime-and-construction.md). Be aware that on retry, motion-producing methods will move the stage again.

## Audit notes (2026-06-28)
- **Fixed:**
  - `home()` is now safe to call before any successful home: when the open-loop step counter is unknown (`__curr_step is None`), it logs a warning and performs a full mechanical home instead of doing arithmetic on `None`. (Previously this raised `TypeError`.)
- **Known / deferred:**
  - `set_angle(precision=False)` is still **not** guarded against an unknown counter. If the stage has not been homed (`__curr_step is None`), the non-precision branch computes `doable_step - self.__curr_step` and raises `TypeError` (or, more generally, mis-moves against a possibly-drifted estimate). **Do not call `set_angle(..., precision=False)` on a freshly constructed-but-failed or un-homed stage** — call `home()` first, or use `precision=True`, which homes before moving.
