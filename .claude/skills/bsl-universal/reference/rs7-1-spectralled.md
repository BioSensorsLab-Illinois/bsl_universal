# RS-7-1 SpectralLED — Gamma Scientific RS-7-1 tunable multi-LED light source (46 installed LED channels, ~360–1100 nm, programmable spectrum)

> **Factory:** `from bsl_universal.instruments import RS_7_1` then `RS_7_1(device_sn="", power_on_test=True)`
> **Transport:** Serial (ASCII command/response over `_bsl_serial`) · **Datasheet:** `SpectralLED-RS-7-User-Manual.pdf` (in `_datasheet/`) · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_RS_7_1.py`

## When to use this
Pick this instrument when an experiment needs a programmable, spectrally tunable light source: driving individual narrowband LED channels at a chosen wavelength, synthesizing an arbitrary target spectrum (raw spectrum, blackbody, CIE x,y, RGB, HSV, or Pantone color), or producing a calibrated photometric/radiometric output. It can read back its own output power, chromaticity, tristimulus, correlated color temperature, and per-channel or full spectrum. Use it for illumination/calibration work where you control the spectral content of the light, not for measuring an external source (use a spectrometer/power meter for that). It is the source you tune; always verify the produced light with `get_*` readbacks or external instruments because fitted output accuracy is not guaranteed.

## Construct & tear down
```python
from bsl_universal.instruments import RS_7_1

# device_sn="" auto-detects the first matching RS-7-1; pass a serial string to pick a specific unit.
# power_on_test=True reboots the device and runs self-tests (>8 s, blocking). Use False to skip.
light = RS_7_1(device_sn="", power_on_test=False)
try:
    # Drive the LED channel(s) nearest 500 nm at 40% power (PERCENTAGE is the default unit).
    chans, wl, fwhm = light.find_closest_chan(wavelength=500)
    light.set_power_chans(chans, powers=40)

    # Read back what the source is actually producing.
    print(light.get_power_output(RS_7_1.POWER_UNIT.RADIANCE))   # measured radiance
    print(light.get_chromaticity_output())                      # (CIEx, CIEy)
finally:
    light.close()   # zeros all channels, fully closes the iris, releases the serial handle (~3 s)
```
`device_sn` selects which physical RS-7-1 to open by serial number; an empty string auto-picks the first RS-7-1 the serial layer finds. Construction is via the package factory only — do **not** instantiate the raw class. See [runtime & construction](00-runtime-and-construction.md).

## Most-used operations

### `find_closest_chan(wavelength: float) -> tuple[list[int], float, float]`
- **Does:** Pure table lookup for the installed LED channel(s) whose center wavelength is nearest `wavelength`.
- **Args:** `wavelength` (float, nm, useful range ~360–1100). No hardware I/O.
- **Returns:** `(channel_numbers, matched_wavelength_nm, matched_FWHM_nm)` — `channel_numbers` is a `list[int]` of **1-based** channel numbers (all channels sharing the nearest wavelength); the wavelength and FWHM are floats in nm.
- **Blocks?** No.
- **Readback?** No (lookup against `LED_CHANNELS.WAVELENGTH`/`FWHM` tables).
- **Raises:** None.
- **Example:** `chans, wl, fwhm = light.find_closest_chan(650)` → feed `chans` into `set_power_chans`.

### `set_power_chans(chans, powers, unit=POWER_UNIT.PERCENTAGE, irr_distance_mm=0) -> None`
- **Does:** Sets per-channel output power with one-to-one `chans`↔`powers` correspondence.
- **Args:** `chans` (int | list[int] | NDArray[int], channel numbers, each MUST be in `LED_CHANNELS.LEN_CHANS`); `powers` (float | list[float] | NDArray[float], value in `unit` units — percent if PERCENTAGE; a single scalar is broadcast to all channels); `unit` (POWER_UNIT enum); `irr_distance_mm` (int, mm, only used for IRRADIANCE/ILLUMINANCE).
- **Returns:** None.
- **Blocks?** One serial round-trip plus the unit-set commands.
- **Readback?** No — only confirms the device `Ok` ack.
- **Raises:** `bsl_type.DeviceOperationError` if `len(chans) != len(powers)` (after scalar broadcast) or if any channel is not in `LEN_CHANS`.
- **Example:** `light.set_power_chans([13, 16], [40.0, 25.0])`

### `set_power_all(power, unit=POWER_UNIT.PERCENTAGE, irr_distance_mm=0) -> None`
- **Does:** Sets the same output level on ALL channels at once (sends `SCP 0,<power>`; channel 0 = all).
- **Args:** `power` (float, in `unit` units — e.g. 0–100 for %); `unit` (POWER_UNIT); `irr_distance_mm` (int, mm, IRRADIANCE/ILLUMINANCE only).
- **Returns:** None.
- **Blocks?** One round-trip plus unit-set commands.
- **Readback?** No — only the `Ok` ack.
- **Raises:** Propagates `DeviceOperationError` from the underlying command on a non-`Ok` response.
- **Example:** `light.set_power_all(10, RS_7_1.POWER_UNIT.PERCENTAGE)`

### `set_power_output(power, unit=POWER_UNIT.RADIANCE, irr_distance_mm=0, match_chrom=False) -> None`
- **Does:** Sets the overall output level via the `OUT` command, optionally re-applying chromaticity correction afterward.
- **Args:** `power` (float, in `unit` units); `unit` (POWER_UNIT, default RADIANCE); `irr_distance_mm` (int, mm); `match_chrom` (bool — when True, re-issues `CCS` to hold chromaticity after the level change).
- **Returns:** None.
- **Blocks?** Multiple round-trips (always reads chromaticity first via `OXY`).
- **Readback?** Reads chromaticity (`get_chromaticity_output`) before changing, but does NOT verify the resulting power — call `get_power_output()` to confirm.
- **Raises:** `DeviceOperationError` on a bad command ack; the unconditional `get_chromaticity_output()` call can raise on a malformed `OXY` response.
- **Example:** `light.set_power_output(20, RS_7_1.POWER_UNIT.RADIANCE)`
- **WARNING (from source docstring):** with `match_chrom=True` the chromaticity correction can silently LOWER the output level with NO error or warning raised. Always verify with `get_power_output()` / `get_spectrum_output()`.

### `set_spectrum_raw(spectrum, *, power=0, power_unit=POWER_UNIT.RADIANCE, include_white=True, fit_max_pwr=False, chroma_correction=False, irr_distance_mm=0) -> float`
- **Does:** Uploads a target spectrum (1 nm step) and fits it on the source (`TSP` → optional `STS` → `FTS[W][M]` → optional `CCS`). All args after `spectrum` are keyword-only.
- **Args:** `spectrum` (list/NDArray of float, radiance or irradiance units, **length must equal `_wavelength_max - _wavelength_min + 1` = 741** for the default 360–1100 nm range, one value per nm); `power` (float, scale target; 0 = skip `STS` scaling); `power_unit` (POWER_UNIT — **RADIANCE or IRRADIANCE ONLY**); `include_white` (bool, appends `W` to `FTS`); `fit_max_pwr` (bool, appends `M` to fit max achievable power); `chroma_correction` (bool, runs `CCS` after fit); `irr_distance_mm` (int, mm).
- **Returns:** float — RMS fit error (`RPE`) of fitted vs. requested spectrum; **-1** on parse failure.
- **Blocks?** Several round-trips (large `TSP` payload + fit).
- **Readback?** Yes — returns the device-reported RMS error.
- **Raises:** `DeviceOperationError` if `power_unit` is PERCENTAGE, or if the spectrum length does not match the configured wavelength span.
- **Example:** `rms = light.set_spectrum_raw(my_741pt_spectrum, power=30, power_unit=RS_7_1.POWER_UNIT.RADIANCE)`

### `get_power_output(unit=POWER_UNIT.RADIANCE, irr_distance_mm=0) -> float`
- **Does:** Reads the total measured output power in the requested unit (`OUTA` query).
- **Args:** `unit` (POWER_UNIT); `irr_distance_mm` (int, mm, IRRADIANCE/ILLUMINANCE only).
- **Returns:** float — measured power in the unit's units (uW/cm^2/sr, uW/cm^2, nits, lux, or %).
- **Blocks?** One round-trip (sets unit, then queries).
- **Readback?** Yes — this IS the readback path for output power.
- **Raises:** Will raise on a non-numeric/empty `OUTA` response (`float()` cast is unguarded).
- **Example:** `p = light.get_power_output(RS_7_1.POWER_UNIT.IRRADIANCE, irr_distance_mm=100)`

### `get_spectrum_output(power_unit=POWER_UNIT.RADIANCE) -> tuple[np.ndarray, list[float]]`
- **Does:** Reads the fitted output spectrum (`OSP`), 741 points at 1 nm.
- **Args:** `power_unit` (POWER_UNIT — **RADIANCE or IRRADIANCE ONLY**).
- **Returns:** `(wavelengths, spectrum)` — `wavelengths` is `np.linspace(360, 1100, 741)` (nm); `spectrum` is `list[float]` in the requested unit.
- **Blocks?** One round-trip (large payload).
- **Readback?** Yes.
- **Raises:** `DeviceOperationError` if `power_unit` is not RADIANCE/IRRADIANCE.
- **Example:** `wl, spec = light.get_spectrum_output(RS_7_1.POWER_UNIT.RADIANCE)`

### `get_chromaticity_output() -> tuple[float, float]`
- **Does:** Reads CIE 1931 x,y chromaticity of the current output (`OXY` query).
- **Args:** None.
- **Returns:** `(CIEx, CIEy)` floats (dimensionless).
- **Blocks?** One round-trip.
- **Readback?** Yes.
- **Raises:** No internal guard — a malformed/empty `OXY` response raises `ValueError`/`IndexError`.
- **Example:** `x, y = light.get_chromaticity_output()`

### `set_iris_position(percentage=0) -> None`
- **Does:** Sets the iris aperture as percent **CLOSED** (`IRI` command). 0 = fully open, 100 = fully closed.
- **Args:** `percentage` (int, percent closed, **0–100 inclusive**).
- **Returns:** None.
- **Blocks?** Yes — sleeps **3 s** after the command (mechanical iris move).
- **Readback?** No — only the `Ok` ack.
- **Raises:** `bsl_type.DeviceOperationError` if `percentage < 0` or `> 100`.
- **Example:** `light.set_iris_position(0)`  *(set the iris BEFORE setting output power in irradiance mode).*

### `close() -> None`
- **Does:** Safe shutdown — zeros all channel power (`set_power_all(0)`), fully closes the iris (`set_iris_position(100)`), releases the serial handle, sets `self._com = None`.
- **Args:** None.
- **Returns:** None.
- **Blocks?** Yes — ~3 s from the iris move inside `set_iris_position(100)`.
- **Readback?** No.
- **Raises:** None — each step is wrapped in try/except; always logs `CLOSED` (even if the underlying close failed). Idempotent (subsequent calls skip I/O).
- **Example:** `light.close()`

## Full method index

| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `RS_7_1` (factory) | function | Construct & connect the driver | `device_sn: str=""`, `power_on_test: bool=True` | connected `RS_7_1` instance |
| `reconnect` | method | Close & re-open serial with retry (3×, 1.0 s delay) | `device_sn: str=""`, `power_on_test: bool=False` | `bool` (True on success) |
| `reset_system` | method | Reboot device (`RST`) & re-init runtime settings | `power_on_test: bool=False` | `bool` (True on success) |
| `find_closest_chan` | method | LED channel(s) nearest a wavelength | `wavelength: float` (nm) | `(list[int] channels, float wl_nm, float fwhm_nm)` |
| `set_iris_position` | method | Set iris % closed (blocks 3 s) | `percentage: int=0` (%, 0–100) | None |
| `set_standard_observer_angle` | method | Set CIE observer angle (2°/10°) | `angle: OBSERVER_ANGLE=DEG_2` | None |
| `set_power_all` | method | Set power on ALL channels | `power: float`, `unit: POWER_UNIT=PERCENTAGE`, `irr_distance_mm: int=0` | None |
| `set_power_chans` | method | Per-channel power | `chans`, `powers`, `unit=PERCENTAGE`, `irr_distance_mm: int=0` | None |
| `set_power_led_random` | method | Random per-channel powers on non-white LEDs | `power_percentage: int=5` (%) | None |
| `set_power_output` | method | Set overall level via `OUT` | `power: float`, `unit=RADIANCE`, `irr_distance_mm: int=0`, `match_chrom: bool=False` | None |
| `set_power_fixed_spectrum` | method | Rescale power, keep current spectral shape | `power: float`, `unit=RADIANCE`, `irr_distance_mm: int=0` | None |
| `set_spectrum_raw` | method | Upload & fit a target spectrum (741 pts) | `spectrum`, `*`, `power=0`, `power_unit=RADIANCE`, `include_white=True`, `fit_max_pwr=False`, `chroma_correction=False`, `irr_distance_mm=0` | `float` (RMS err; -1 on fail) |
| `set_spectrum_CIExy` | method | Fit to CIE 1931 x,y chromaticity | `CIEx: float`, `CIEy: float`, `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `(float, float)` actual (x,y) |
| `set_spectrum_black_body` | method | Fit a Planck blackbody spectrum | `temp: int` (K), `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `float` (resulting CCT, K) |
| `set_spectrum_hsv` | method | HSV→RGB→fit | `H: float` (0–360°), `S: float` (0–100%), `V: float` (0–100%), `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `float` (RMS err) |
| `set_spectrum_rgb` | method | 8-bit RGB→CIExy→fit | `r,g,b: int` (0–255), `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `float` (RMS err) |
| `set_spectrum_rgb_random` | method | Fit a random RGB color | `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `float` (RMS err) |
| `set_spectrum_pantone` | method | Fit a Pantone color by (partial) name | `color_name: str`, `power=0`, `power_unit=RADIANCE`, `irr_distance_mm=0` | `float` (RMS err) |
| `get_optical_feedback_gain` | method | Read optical feedback gain (`FBG`, ~1) | none | `float` |
| `get_power_output` | method | Measured total output power (`OUTA`) | `unit=RADIANCE`, `irr_distance_mm: int=0` | `float` (power in unit) |
| `get_power_all_chans` | method | (channels, powers) of all ON channels (`SCP` query) | `unit=PERCENTAGE`, `irr_distance_mm: int=0` | `(list[str] chans, list[str] powers)` — see gotcha |
| `get_color_temp` | method | Correlated color temperature (`CCT`) | none | `float` (K; 0=empty, -1=parse fail) |
| `get_E_rms_fitted_spectrum` | method | RMS error of last fit (`RPE`) | none | `float` (-1 on fail) |
| `get_chromaticity_output` | method | CIE 1931 x,y of output (`OXY`) | none | `(float, float)` |
| `get_tristimulus_output` | method | CIE XYZ tristimulus (`OXYZ`) | none | `(float, float, float)` |
| `get_spectrum_output` | method | Fitted output spectrum (`OSP`, 741 pts) | `power_unit=RADIANCE` (RADIANCE/IRRADIANCE) | `(ndarray wl, list[float] spec)` |
| `get_spectrum_led` | method | One LED channel's spectrum (`OSP<chan>`) | `led_chan: int`, `power_unit=RADIANCE` | `list[float]` (741 pts) |
| `get_distinct_led_channel_id` | method | Unique non-white channel IDs with distinct nonzero center wavelengths | none | `(list[int] ids, list[float] wl_nm)` |
| `close` | method | Zero power, close iris, release handle | none | None |
| `POWER_UNIT` | enum (attr) | Output-unit selector + `UNITS` strings | RADIANCE/IRRADIANCE/LUMINANCE/ILLUMINANCE/PERCENTAGE | enum members |
| `OBSERVER_ANGLE` | enum (attr) | CIE observer angle | DEG_2 / DEG_10 | enum members |
| `LED_CHANNELS` | enum (attr) | Channel/wavelength/FWHM lookup tables | LEN_CHANS, LEN_CHANS_NO_WHITE, WAVELENGTH, FWHM | list tables |
| `MACBECH_COLOR` | enum (attr) | Macbeth CIE x,y table (19 patches) — **unused, do not rely on** | CIExy | list of (x,y) |

Internal helpers (underscore-prefixed) — surfaced here only so an agent recognizes them; **do not drive directly**: `_serial_connect`, `_system_restart`, `_wait_ready_after_restart`, `_system_init`, `_run_integrity_check`, `_run_basic_assurance_test`, `_set_UNI_unit`, `_set_irr_distance`, `_set_power_unit`, `_set_optical_feedback`, `_set_spectrum_transfer_format`, `_set_wavelength_range`, `_black_body_spectrum`, `_planck`, `_com_query`, `_com_cmd`, `_readline_nonempty`.

## Units, ranges & limits
- **Wavelength span:** default 360–1100 nm, 1 nm step → **741 points**. Set by `_set_wavelength_range(360, 1100)` during init. `set_spectrum_raw` requires `len(spectrum) == _wavelength_max - _wavelength_min + 1`.
- **POWER_UNIT enum values & units** (`POWER_UNIT.UNITS`): `RADIANCE=0` → `uW/cm^2/sr`; `IRRADIANCE=1` → `uW/cm^2`; `LUMINANCE=2` → `nits`; `ILLUMINANCE=3` → `lux`; `PERCENTAGE=4` → `%`.
- **Spectrum set/read methods accept ONLY RADIANCE or IRRADIANCE** (`set_spectrum_raw`, `get_spectrum_output`, `get_spectrum_led`). PERCENTAGE/LUMINANCE/ILLUMINANCE raise `DeviceOperationError`.
- **Installed channels (`LED_CHANNELS.LEN_CHANS`, 46 channels):** 3,4,5,6,7,8,11,13,14,16,19,20,21,22,23,24,26,27,28,29,30,31,33,34,36,37,38,39,41,42,43,45,46,47,49,51,52,53,54,55,57,59,60,61,62,63. Channel numbers are **1-based**; `WAVELENGTH`/`FWHM` tables are 0-based, so `table_index = channel_number - 1`. `set_power_chans`/`get_spectrum_led` only accept members of `LEN_CHANS`.
- **Non-white channels (`LEN_CHANS_NO_WHITE`, 40 channels):** used by `set_power_led_random` and `get_distinct_led_channel_id`.
- **Iris:** percent **closed**, 0–100 inclusive. 0 = fully open, 100 = fully closed. `set_iris_position` blocks 3 s.
- **Observer angle:** `OBSERVER_ANGLE.DEG_2` (2°) or `DEG_10` (10°); power-on default is always 2°.
- **RGB:** each of r/g/b is 8-bit, 0–255 inclusive (out-of-range raises). **HSV:** H 0–360°, S 0–100%, V 0–100% (no explicit bounds enforcement in code).
- **Default serial read timeout:** 0.5 s (set at construction and on reconnect). `_com_query`/`_com_cmd` default per-call timeout 1.0 s; integrity/assurance commands (`ICK`/`BAT`) use 5 s.
- **Reconnect retry:** `CONNECT_RETRY_COUNT = 3`, `CONNECT_RETRY_DELAY_SEC = 1.0`.
- **Reboot blocking sleep:** `_system_restart` sleeps **8 s** after `RST`. `_wait_ready_after_restart` default `timeout_sec = 8.0`.
- **Optional dependencies:** `pycolorname` (Pantone) and `scikit-image` (RGB→XYZ) are imported in try/except; if missing they are `None` and the RGB/Pantone methods raise `DeviceOperationError` at call time (not at import).

## Safety & gotchas
- **Recovery layer:** for transient serial faults call `dev.safe.<method>()` to get automatic retry (e.g. `light.safe.set_power_chans(chans, powers)`). `.safe` is **method-only** (it wraps callables, not attribute/enum access) — see [runtime & construction](00-runtime-and-construction.md).
- **Construction blocks >8 s when `power_on_test=True`** (device reboot `RST` + 8 s sleep + integrity + basic-assurance tests). Pass `power_on_test=False` for fast connects. `reset_system()` and `reconnect(power_on_test=True)` likewise block ≥8 s.
- **`close()`/shutdown blocks ~3 s** because it issues `set_iris_position(100)` (3 s sleep) and `set_power_all(0)`. `__del__` calls `close()`, so garbage collection / interpreter exit can stall. `close()` always logs `CLOSED` even if the underlying handle close failed.
- **Readback caveat — most setters do NOT verify hardware echoed the value.** `set_power_*`, `set_iris_position`, `set_standard_observer_angle` only confirm an `Ok` ack. To confirm the produced light, call `get_power_output()`, `get_spectrum_output()`, `get_chromaticity_output()`, or use an external meter. The driver's own docstrings warn that fitted spectrum/chromaticity accuracy is "unknown."
- **`set_power_output(match_chrom=True)` can silently reduce output power** with no error/warning — always verify with `get_power_output()`.
- **`set_spectrum_CIExy` has a unit side effect:** it first calls `set_power_all(0.1)`, which switches the system into PERCENTAGE unit before applying `CCS`. The unit is only re-applied if `power != 0`. Re-set your unit explicitly afterward if needed.
- **`get_power_all_chans` returns raw strings, not numbers** (channel and power lists are un-cast `str`), despite the documented `tuple[list[int], list[float]]`. Its continuation read loop (`self._com.readline()`) is unbounded and will raise `IndexError` on a line without a comma — cast/validate yourself and avoid relying on it in unattended runs.
- **`get_chromaticity_output` / `get_tristimulus_output` have no parse-error handling** — an empty/malformed `OXY`/`OXYZ` response raises. Because `set_power_output` calls `get_chromaticity_output()` unconditionally, a transient bad response there can abort a power set.
- **`get_color_temp` returns magic sentinels:** `0` when the device returns empty, `-1` when the value cannot be parsed — both formatted as "Kelvins." Check for these before trusting a CCT.
- **`find_closest_chan` can return spurious wavelengths:** the `WAVELENGTH`/`FWHM` tables contain physically implausible entries (e.g. 5990.9, 2937.8, 2747.6, 959.3 nm) at certain positions; out-of-band requests may select one. Constrain requests to ~360–1100 nm.
- **No `None` guard after `close()`:** once `close()` sets `self._com = None`, further calls (`set_*`, `get_*`, `reset_system`) raise `AttributeError` rather than a typed exception. Use `reconnect()` to re-establish (it guards `_com`).
- **Destructive/physical actions:** this is a high-power LED source — output light may be intense and could damage sensors or eyes; the iris moves mechanically; `RST` reboots the unit. Always `close()` (or `set_power_all(0)`) before leaving the device, and set the iris before setting power in irradiance mode.
- **Construct only via the factory** `bsl_universal.instruments.RS_7_1(...)`; do not instantiate the raw `_RS_7_1.RS_7_1` class.

## Audit notes (2026-06-28)
- **Fixed:**
  - `get_distinct_led_channel_id` now indexes the wavelength table with `id-1`, converting a 1-based channel number to the correct 0-based table position. It previously read the wrong (off-by-one) channel and could pick up zero/spurious wavelengths; the returned `(channel_ids, wavelengths_nm)` pairs are now correct.
  - `set_power_led_random` is now correctly typed and documented as returning `None`. It applies a random per-channel spectrum (upper-bounded by `power_percentage`, in percent) and returns nothing — do not expect a `list[float]` back as the old signature implied.
- **Known / deferred:** No outstanding issues recorded for this module.
