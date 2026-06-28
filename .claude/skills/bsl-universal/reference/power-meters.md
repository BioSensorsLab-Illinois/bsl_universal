# Thorlabs Optical Power Meters (PM100D / PM400) — bench optical power/energy meter consoles that read a Thorlabs photodiode or thermal sensor head over SCPI

> **Factory:** `from bsl_universal.instruments import PM100D` then `PM100D(device_sn="")` — or `from bsl_universal.instruments import PM400` then `PM400(device_sn="")`
> **Transport:** VISA (SCPI over USB/serial) · **Datasheet:** none on disk · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_PM100D.py`, `bsl_universal/instruments/_inst_lib/instruments/_PM400.py`

One reference covers **both** models. The two drivers are line-for-line identical in API, units, and behavior **except** for one log-string difference (PM100D's `get_measured_power_density` still mislabels its log; PM400's is correct — see Audit notes). Everything below applies to both unless a model is named explicitly.

## When to use this
Pick a PM100D/PM400 when you need a calibrated reading of **optical power (W)**, **power density / irradiance (W/cm²)**, **photodiode current (A)**, or signal **frequency (Hz)** from a Thorlabs sensor head — e.g. measuring laser/LED output power, beam irradiance on a sample, or verifying a source's stability. Set the correction wavelength to match your source before reading power: the meter applies a wavelength-dependent responsivity correction, so a wrong wavelength silently biases every power reading. Use the software-averaging helpers (`get_measured_power_avg`) when you want a host-side mean across several meter readings on top of the meter's own internal averaging.

## Construct & tear down
```python
from bsl_universal.instruments import PM100D   # or: from bsl_universal.instruments import PM400

# device_sn="" selects the FIRST matching power meter on the VISA bus.
# Pass an explicit serial string when more than one meter is connected.
pm = PM100D(device_sn="")                       # PM400(device_sn="") is identical
try:
    pm.set_preset_wavelength(532.0)             # nm — must match your source
    power_W = pm.get_measured_power()           # returns Watts (NOT mW)
    print(f"{power_W * 1e3:.3f} mW  from sensor {pm.get_sensor_id()}")
finally:
    pm.close()                                  # idempotent; safe if already closed
```
Construction connects over VISA with bounded retries (3 attempts, 0.5 s apart), then runs a full ~14-query readback sweep (`run_update_power_meter()`) and logs the attached sensor id. If no meter is found it raises `bsl_type.DeviceConnectionFailed`. `device_sn` is the VISA serial selector; empty string = first matching device.

## Most-used operations
Listed in workflow order: configure → (optionally zero) → read.

### `set_preset_wavelength(wl: np.float64) -> np.float64`
- **Does:** Sets the meter's correction wavelength (SCPI `SENS:CORR:WAV`), sleeps 5 ms, then reads it back.
- **Args:** `wl` — np.float64, **nm**. NOT validated in the driver; valid span is sensor-dependent and enforced only by the hardware (out-of-range values are sent verbatim and may be clamped/rejected by the meter).
- **Returns:** np.float64, **nm** — the read-back wavelength from `get_preset_wavelength()`.
- **Blocks?** Yes, briefly (one write + 5 ms sleep + one query; write retried up to 10× with 0.1 s sleeps on failure).
- **Readback?** Returns the hardware read-back, but does **not** assert it equals `wl`. A silent clamp is not flagged — compare yourself if the exact value matters.
- **Raises:** `bsl_type.DeviceOperationError` after 10 failed write attempts.
- **Example:** `wl = pm.set_preset_wavelength(635.0)`

### `set_average_count(cnt: int) -> int`
- **Does:** Sets how many ~3 ms samples the meter averages per reading (SCPI `SENS:AVER:COUNT`), then reads it back.
- **Args:** `cnt` — int, **count** (each sample ≈ 3 ms). NOT validated; hardware minimum is typically 1. `cnt <= 0` is forwarded unchecked.
- **Returns:** int, **count** — read-back from `get_average_count()`.
- **Blocks?** No (one write + one query).
- **Readback?** Returns the read-back but does **not** assert it equals `cnt`.
- **Raises:** none specific (a parse/transport error propagates raw).
- **Example:** `pm.set_average_count(10)   # ~30 ms per power reading`

### `set_auto_range(auto: bool = True) -> None`
- **Does:** Enables/disables auto power-ranging (`SENS:POW:RANG:AUTO ON`/`OFF`).
- **Args:** `auto` — bool, default `True`. `True` → ON, `False` → OFF.
- **Returns:** None.
- **Blocks?** No (one write).
- **Readback?** **No** — fire-and-forget; does not call `get_auto_range_status()` to confirm. Verify separately if needed.
- **Raises:** none specific.
- **Example:** `pm.set_auto_range(True)`

### `run_zero() -> None`
- **Does:** Triggers a zero / dark-offset calibration (`SENS:CORR:COLL:ZERO:INIT`), then sleeps 0.2 s.
- **Args:** none.
- **Returns:** None.
- **Blocks?** Yes — fixed 0.2 s sleep only; it does **not** poll for completion, so a slow sensor may not have finished when the call returns.
- **Readback?** **No** — does not check `get_zero_state()` / `get_zero_magnitude()` afterward.
- **Raises:** none specific.
- **Safety:** **Block the beam / cover the sensor first.** Zeroing with light present corrupts every subsequent reading. The driver does not enforce this.
- **Example:** `pm.run_zero()`

### `get_measured_power() -> np.float64`
- **Does:** One averaged power reading (`MEAS:POW?`), averaged over the meter's internal `average_count`.
- **Args:** none.
- **Returns:** np.float64, **W** (Watts). The log line prints mW (`× 1000`) but the returned value is W — do not re-scale.
- **Blocks?** Yes, ≈ `3 ms × average_count`.
- **Readback?** n/a (pure read).
- **Raises:** none specific.
- **Example:** `p_W = pm.get_measured_power()`

### `get_measured_power_avg(avg: int = 1) -> np.float64`
- **Does:** Issues `avg` separate `MEAS:POW?` queries and returns the host-side mean (this averaging is **on top of** the meter's own `average_count`).
- **Args:** `avg` — int, **count**, default 1. **Must be ≥ 1** (validated as of the 2026-06-28 audit).
- **Returns:** np.float64, **W**.
- **Blocks?** Yes, ≈ `avg × 3 ms × average_count`.
- **Readback?** n/a.
- **Raises:** `bsl_type.DeviceOperationError("avg must be >= 1")` if `avg < 1`.
- **Example:** `p_W = pm.get_measured_power_avg(avg=5)`

### `get_measured_power_density() -> np.float64`
- **Does:** One averaged power-density/irradiance reading (`MEAS:PDEN?`).
- **Args:** none.
- **Returns:** np.float64, **W/cm²**.
- **Blocks?** Yes, ≈ `3 ms × average_count`.
- **Readback?** n/a.
- **Raises:** none specific.
- **Gotcha:** On **PM100D** the log line still mislabels this as `...mW` (cosmetic only; return value is W/cm²). On **PM400** the log is correct.
- **Example:** `pden = pm.get_measured_power_density()   # W/cm^2`

### `get_measured_power_density_avg(avg: int = 1) -> np.float64`
- **Does:** Host-side mean of `avg` separate `MEAS:PDEN?` reads.
- **Args:** `avg` — int, **count**, default 1. **Must be ≥ 1** (validated as of the 2026-06-28 audit).
- **Returns:** np.float64, **W/cm²**.
- **Blocks?** Yes, ≈ `avg × 3 ms × average_count`.
- **Readback?** n/a.
- **Raises:** `bsl_type.DeviceOperationError("avg must be >= 1")` if `avg < 1`.
- **Gotcha:** The averaged variant's log line labels the value `...mW` on **both** models (cosmetic; return is W/cm²).
- **Example:** `pden = pm.get_measured_power_density_avg(avg=5)`

### `get_sensor_id() -> str`
- **Does:** Queries the attached sensor identity (`SYST:SENS:IDN?`) and returns the first comma-delimited field (the model/name).
- **Args:** none.
- **Returns:** str — sensor name only (serial/cal-date fields are dropped).
- **Blocks?** No (one query).
- **Readback?** n/a.
- **Raises:** none specific; with no sensor attached the query may error or return an unexpected reply.
- **Example:** `name = pm.get_sensor_id()`

## Full method index
Identical for PM100D and PM400 (class methods on the driver object). All getters return `np.float64` unless noted.

| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `PM100D` / `PM400` (factory) | function | Construct + connect + full readback sweep; returns the driver instance | `device_sn: str = ""` (VISA serial; ""=first match) | driver instance |
| `reconnect` | method | Close then reconnect (bounded retries) | `device_sn: str = ""` | `bool` (True on success; does NOT raise) |
| `reset_meter` | method | SCPI `*RST`, sleep 0.2 s, optionally re-run readback sweep | `run_update: bool = True` | `bool` (True ok; False on any exception) |
| `run_update_power_meter` | method | Query+log all ~14 parameters (refresh) | none | `None` (values logged, not returned) |
| `run_zero` | method | Trigger dark/zero calibration, sleep 0.2 s | none | `None` |
| `get_preset_wavelength` | method | Read correction wavelength | none | `np.float64` (nm) |
| `set_preset_wavelength` | method | Set correction wavelength + read back | `wl` (nm) | `np.float64` (nm, read-back) |
| `get_attenuation_dB` | method | Read input attenuation/gain | none | `np.float64` (dB) |
| `get_average_count` | method | Read averaging sample count | none | `int` (count) |
| `set_average_count` | method | Set averaging count + read back | `cnt` (count) | `int` (count, read-back) |
| `get_measured_power` | method | One averaged power reading | none | `np.float64` (W) |
| `get_measured_power_avg` | method | Host-side mean of `avg` power reads | `avg: int = 1` (≥1) | `np.float64` (W) |
| `get_measured_power_density` | method | One averaged irradiance reading | none | `np.float64` (W/cm²) |
| `get_measured_power_density_avg` | method | Host-side mean of `avg` irradiance reads | `avg: int = 1` (≥1) | `np.float64` (W/cm²) |
| `get_power_measuring_range` | method | Read upper power-range bound (**`#un tested`**) | none | `np.float64` (W) — see note |
| `set_power_range` | method | Set upper power-range bound (**`#un tested`**) | `range: np.float64` (W) | `None` |
| `get_auto_range_status` | method | Read auto-range on/off | none | `bool` |
| `set_auto_range` | method | Enable/disable auto-range (no readback) | `auto: bool = True` | `None` |
| `get_measured_frequency` | method | Read measured signal frequency | none | `np.float64` (Hz) |
| `get_zero_magnitude` | method | Read stored zero/dark magnitude | none | `np.float64` (W) |
| `get_zero_state` | method | Read whether zero correction is active | none | `bool` |
| `get_photodiode_response` | method | Read sensor responsivity | none | `np.float64` (A/W) |
| `get_measured_current` | method | Read photodiode current | none | `np.float64` (A) |
| `get_current_range` | method | Read upper current-range bound | none | `np.float64` (A) |
| `get_sensor_id` | method | Read attached sensor name | none | `str` |
| `close` | method | Close VISA session; idempotent | none | `None` |
| `reconnect` / `reset_meter` / `__init__` / `__del__` | method | (see above; `__del__` calls `close()` on GC) | — | — |
| `_com_connect` | method *(private)* | Internal: VISA connect with bounded retries (used by `__init__`/`reconnect`) | `device_sn: str` | `bool` |

`CONNECT_RETRY_COUNT` (=3) and `CONNECT_RETRY_DELAY_SEC` (=0.5) are class constants, not methods.

## Units, ranges & limits
- **Return units are SI base units**, regardless of the mW/mA shown in log lines (logs multiply by 1000 cosmetically — never divide the returned value):
  - power → **W**, power density → **W/cm²**, current → **A**, current range → **A**, zero magnitude → **W**, responsivity → **A/W**, frequency → **Hz**, wavelength → **nm**, attenuation → **dB**, average count → integer **count**.
- **Wavelength:** nm; **no client-side validation** — valid span is sensor-dependent and enforced only by the meter.
- **Attenuation:** docstring/comment notes a +60 dB to −60 dB gain/attenuation span, default 0 dB. **Read-only here** — there is no attenuation setter in either driver.
- **Average count:** each sample ≈ 3 ms; total reading time ≈ `3 ms × average_count`; `*_avg(avg=...)` multiplies that by `avg`.
- **Power range (`get`/`set_power_range`):** Watts; **no validation**, sensor-dependent, and marked `#un tested` in source — treat as experimental.
- **`avg` (both `*_avg` helpers):** int, default 1, **must be ≥ 1** (enforced — raises on `avg < 1`).
- **Connection:** 3 retry attempts, 0.5 s apart; failure raises `bsl_type.DeviceConnectionFailed`.
- **Fixed sleeps:** `*RST` 0.2 s; `run_zero` 0.2 s; `set_preset_wavelength` 0.005 s; wavelength get/set retry loops sleep 0.1 s between up to 10 attempts.
- **Single sensor** per meter; identified by `get_sensor_id()` (first field of `SYST:SENS:IDN?`).

## Safety & gotchas
- **Recovery layer:** for transient-fault retries call `dev.safe.<method>()` (e.g. `pm.safe.get_measured_power()`). `.safe` is **method-only** — it wraps method calls, not attribute access. See [runtime & construction](00-runtime-and-construction.md).
- **Use the public factory** (`from bsl_universal.instruments import PM100D` / `PM400`), not the private `_PM100D`/`_PM400` classes, so health-hub registration and the runtime hooks (`.safe`, `.invoke`, `.reconnect_safe`, `.reset_safe`, idempotent `close`) are attached.
- **Return units ≠ log units.** Power/current/responsivity logs print mW/mA/(mA/W) after `× 1000`; the returned values are W/A/(A/W). Do not re-scale.
- **Zero with the beam blocked.** `run_zero()` does not check for light and does not verify completion (fixed 0.2 s sleep only) — block/cover the sensor first, and re-read `get_zero_state()` if you need confirmation.
- **Setters mostly do not verify.** `set_auto_range` and `set_power_range` perform **no** readback. `set_preset_wavelength` and `set_average_count` return a read-back but do **not** assert it equals the request — a silent hardware clamp (especially of wavelength, which biases all power readings) is not flagged. Compare the returned value yourself when correctness matters.
- **`*RST` wipes config.** `reset_meter()` resets wavelength, averaging, ranging, and zero to defaults, and **swallows all exceptions, returning `False`** instead of raising — check the bool.
- **`reconnect()` does not refresh.** Unlike `__init__`, it does not re-run `run_update_power_meter()`. After a reconnect, call the getters (or `run_update_power_meter()`) you need to re-read state.
- **After `close()`, the transport is `None`.** Any further method that touches `self._com` raises a raw `AttributeError` (not a typed `bsl_type` error). `close()` is idempotent and safe to call twice; `__del__` also calls it on GC.
- **`#un tested` methods:** `get_power_measuring_range` and `set_power_range` are flagged untested in source — prefer auto-ranging (`set_auto_range(True)`) over manual range control. `set_power_range` does not disable auto-range, so a manual range may be overridden while auto-range is ON.
- **No optical interlock.** These are passive meters; they do not control the light source. Over-driving the sensor beyond its rated input can damage the sensor head — that limit lives in the sensor's datasheet, not in this driver.
- **`get_sensor_id`** returns only the first comma field; if no sensor is attached the query may error or return an unexpected string.

## Audit notes (2026-06-28)
- **Fixed:**
  - `get_measured_power_avg(avg)` now rejects `avg < 1` with `bsl_type.DeviceOperationError` — it no longer divides by zero (was `ZeroDivisionError` at `avg=0`) or silently returns 0 for negative `avg`.
  - `get_measured_power_density_avg(avg)` got the identical guard — `avg < 1` now raises instead of crashing or returning garbage.
  - `get_power_measuring_range` return-type annotation was corrected to match the actual `np.float64` (Watts) return value (was annotated `int` while returning `np.float64`).
  - **PM400 only:** `get_measured_power_density` now logs its value correctly as `W/cm^2` (previously logged a `× 1000` value labeled `mW`).
- **Known / deferred:**
  - `set_power_range` still has a **unit mismatch**: the SCPI command sends the value as Watts (`SENS:POW:RANG:UPP`) but the log line claims `mW`, and no conversion is applied — do **not** trust its log, and do not rely on this method (it is also `#un tested` and its `range` parameter shadows the Python builtin). Prefer auto-ranging.
  - **PM100D only:** `get_measured_power_density` (the non-averaged variant) still logs its W/cm² value mislabeled as `mW`. The **returned value is correct (W/cm²)** — only the log string is wrong. The averaged variant `get_measured_power_density_avg` logs `mW` on **both** models; same caveat (return value is correct).
