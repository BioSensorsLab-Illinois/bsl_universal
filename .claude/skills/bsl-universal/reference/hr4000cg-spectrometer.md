# HR4000CG Spectrometer — OceanOptics HR4000CG fiber-coupled UV-NIR CCD spectrometer

> **Factory:** `from bsl_universal.instruments import HR4000CG` then `HR4000CG(device_sn: str | None = None)`
> **Transport:** USB-SDK (python-seabreeze / libseabreeze) · **Datasheet:** none on disk · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_HR4000CG.py`

## When to use this
Pick this instrument when you need to capture an optical **spectrum** (intensity vs. wavelength) from light delivered to an OceanOptics HR4000CG over a fiber. Typical uses: measuring emission spectra of LEDs/lamps, transmission/absorption of a sample under a reference source, or verifying the spectral output of an illumination path. It is a USB CCD spectrometer with a fixed grating — you set an integration (exposure) time, then read back a per-pixel wavelength axis and per-pixel intensity array. It does **not** control any light source; pair it with a separate source instrument.

## Construct & tear down
```python
from bsl_universal.instruments import HR4000CG

spec = HR4000CG(device_sn=None)   # None/"" => first available spectrometer on the USB bus
try:
    # Inspect device limits before exposing
    lo_us, hi_us = spec.integration_time_limit_us          # (min_us, max_us)
    print(f"integration range {lo_us}-{hi_us} us, {spec.device_pixel_count} pixels")

    # Set a 100 ms exposure (validate yourself — the setter does NOT range-check)
    exp = 100_000
    if lo_us <= exp <= hi_us:
        spec.set_integration_time_micros(exp)

    wavelengths = spec.get_wavelength()   # nm, no hardware trigger (cached calibration)
    intensities = spec.get_intensity()    # a.u., blocks ~exposure time
finally:
    spec.close()
```
`device_sn` selects which spectrometer to bind to. `None` or `""` connects to the first available unit on the USB bus (`from_first_available()`). A non-empty string must appear within the string repr of `sb.list_devices()`; if matched, the driver opens by serial number (`from_serial_number`). See [runtime & construction](00-runtime-and-construction.md) for the shared lifecycle and the `.safe` recovery layer.

## Most-used operations

### `set_integration_time_micros(exp_us: int) -> None`
- **Does:** Sets the CCD integration (exposure) time. Affects the blocking duration of every subsequent `get_intensity`/`get_spectrum`.
- **Args:** `exp_us: int`, **microseconds (us)**. Valid range is device-defined; read it from `integration_time_limit_us`. The driver does **not** clamp or validate.
- **Returns:** `None`
- **Blocks?** Brief register write only.
- **Readback?** **No.** The value is forwarded to seabreeze with no verification and no driver-side range check. seabreeze has no integration-time getter.
- **Raises:** No typed bsl error here. Out-of-range values fail downstream inside libseabreeze (surfacing as `SeaBreezeError`, not a `bsl_type` exception). Calling after `close()` raises a raw `AttributeError`.
- **Example:** `spec.set_integration_time_micros(100_000)  # 100 ms`

### `get_wavelength() -> numpy.ndarray[float64]`
- **Does:** Returns the per-pixel wavelength calibration axis. Calibration-derived (polynomial vs. pixel index), **not** measured — no hardware acquisition.
- **Args:** none
- **Returns:** `numpy.ndarray` of `float64`, length = `device_pixel_count`, values in **nm**.
- **Blocks?** No (cached read, fast).
- **Readback?** N/A (read-only).
- **Raises:** Raw `AttributeError` if called after `close()` (no None-guard on `self.spec`).
- **Example:** `wl = spec.get_wavelength()`

### `get_intensity(correct_dark_counts: bool = False, correct_nonlinearity: bool = False) -> numpy.ndarray[float64]`
- **Does:** Triggers one hardware acquisition and returns the per-pixel intensity array.
- **Args:**
  - `correct_dark_counts: bool` (default `False`) — subtract the average of electric-dark CCD pixels to remove the non-optical noise floor. Only valid if this unit stores dark pixels.
  - `correct_nonlinearity: bool` (default `False`) — apply EEPROM-stored nonlinearity coefficients. Only valid if the unit stores them.
- **Returns:** `numpy.ndarray` of `float64`, length = pixel count, intensities in **a.u.** (ADC counts).
- **Blocks?** **Yes** — for roughly the current integration time plus USB transfer. Long exposures stall the calling thread.
- **Readback?** N/A (this is the readout).
- **Raises:** seabreeze `SeaBreezeError` if a correction flag is set but unsupported by the device (not wrapped into a `bsl_type` exception). Raw `AttributeError` after `close()`.
- **Example:** `y = spec.get_intensity(correct_dark_counts=True)`

### `get_spectrum(correct_dark_counts: bool = False, correct_nonlinearity: bool = False) -> numpy.ndarray[float64]`
- **Does:** Performs one hardware acquisition and returns wavelengths and intensities stacked together.
- **Args:** same two correction flags as `get_intensity` (both default `False`, same support caveats).
- **Returns:** `numpy.ndarray` of `float64`, shape `(2, pixel_count)`: row 0 = wavelengths (**nm**), row 1 = intensities (**a.u.**). Unpack as `(wavelengths, intensities) = spec.get_spectrum()`.
- **Blocks?** **Yes** — ~one integration time plus USB transfer (single acquisition; see Audit notes).
- **Readback?** N/A.
- **Raises:** `SeaBreezeError` on unsupported correction flag; raw `AttributeError` after `close()`.
- **Example:** `wl, y = spec.get_spectrum()`

### `integration_time_limit_us -> tuple[int, int]` (property)
- **Does:** Returns the hardware `(min, max)` allowable integration times.
- **Args:** none
- **Returns:** `tuple[int, int]` = `(min_us, max_us)` in **microseconds**.
- **Blocks?** No (device feature query).
- **Readback?** N/A (query).
- **Raises:** Raw `AttributeError` after `close()`.
- **Example:** `lo, hi = spec.integration_time_limit_us`

### `device_max_intensity -> float` (property)
- **Does:** Returns the ADC full-scale (maximum reportable) intensity. The detector can saturate optically **below** this value.
- **Args:** none
- **Returns:** `float`, intensity in **a.u.**
- **Blocks?** No (query).
- **Readback?** N/A.
- **Raises:** Raw `AttributeError` after `close()`.
- **Example:** `sat = spec.device_max_intensity`

### `device_pixel_count -> int` (property)
- **Does:** Returns the number of detector pixels (= length of the wavelength/intensity arrays).
- **Args:** none
- **Returns:** `int` (pixels).
- **Blocks?** No (query).
- **Readback?** N/A.
- **Raises:** Raw `AttributeError` after `close()`.
- **Example:** `n = spec.device_pixel_count`

### `close() -> None`
- **Does:** Releases the seabreeze USB handle and sets `self.spec = None`. Safe to call multiple times.
- **Args:** none
- **Returns:** `None`
- **Blocks?** Brief.
- **Readback?** N/A.
- **Raises:** Never (teardown errors are swallowed). Logs a `CLOSED ... success` line on **every** call (see gotchas).
- **Example:** `spec.close()`

## Full method index
| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `HR4000CG(device_sn=None)` | constructor | Connect to spectrometer; retries 3× / 0.5 s; populates `device_id`, `device_model` | `device_sn: str\|None` (serial; None/"" = first available) | `HR4000CG` instance |
| `reconnect(device_sn=None)` | method | Close then reconnect; if `device_sn` given it **permanently** overrides the stored target | `device_sn: str\|None` | `bool` (True = live handle) |
| `reset_connection()` | method | Reconnect using the currently stored selector (wraps `reconnect`) | none | `bool` |
| `get_wavelength()` | method | Per-pixel wavelength axis (cached, no trigger) | none | `ndarray[float64]` (nm) |
| `get_intensity(...)` | method | Trigger one acquisition; per-pixel intensities | `correct_dark_counts: bool=False`, `correct_nonlinearity: bool=False` | `ndarray[float64]` (a.u.) |
| `get_spectrum(...)` | method | One acquisition; stacked `(2,N)` wavelengths+intensities | `correct_dark_counts: bool=False`, `correct_nonlinearity: bool=False` | `ndarray[float64]` shape (2,N): row0 nm, row1 a.u. |
| `set_integration_time_micros(exp_us)` | method | Set CCD exposure time (no validation, no readback) | `exp_us: int` (us) | `None` |
| `integration_time_limit_us` | property | Hardware (min,max) integration time | none | `tuple[int,int]` (us) |
| `device_max_intensity` | property | ADC full-scale intensity | none | `float` (a.u.) |
| `device_pixel_count` | property | Number of detector pixels | none | `int` (pixels) |
| `close()` | method | Release USB handle | none | `None` |
| `reset_connection` / `reconnect` | method | (see above) recovery helpers | — | `bool` |
| `__del__` | private/internal | GC-time best-effort `close()`; swallows all exceptions — do **not** rely on for deterministic cleanup | — | `None` |
| `__connect_spectrometer` | private/internal | Underlying connect-with-retry routine called by constructor/reconnect | — | `None` (raises `DeviceConnectionFailed`) |

## Units, ranges & limits
- **Wavelength axis:** nm, per-pixel, length = `device_pixel_count`. Span and pixel count are read from hardware at runtime — the driver does **not** hardcode them. Query `get_wavelength()[0]` / `[-1]` and `device_pixel_count` for the actual values of the connected unit.
- **Intensity:** arbitrary units (a.u. = ADC counts). Full-scale = `device_max_intensity` (read from device). Optical saturation can occur below this value.
- **Integration time:** microseconds (us), `int`. Valid `(min, max)` is device-defined and exposed only via `integration_time_limit_us`; not hardcoded and not validated by the setter.
- **Correction flags:** `correct_dark_counts`, `correct_nonlinearity` — `bool`, default `False`. Effective only if the specific unit stores dark pixels / nonlinearity coefficients in EEPROM.
- **Connection constants (class-level):** `CONNECT_RETRY_COUNT = 3`, `CONNECT_RETRY_DELAY_SEC = 0.5`. Constructor blocking time grows up to ~1.5 s if all 3 attempts are exhausted.
- **No grating/filter/channel selection** — this is a single fixed-grating, single-channel spectrometer; there are no grating or filter IDs to set.

## Safety & gotchas
- **Recovery layer:** `spec.safe.<method>()` retries a transient failure for any method (e.g. `spec.safe.get_intensity()`). `.safe` is **method-only** — it does not wrap properties (`integration_time_limit_us`, `device_max_intensity`, `device_pixel_count`). See [runtime & construction](00-runtime-and-construction.md).
- **No None-guard on `self.spec`:** after `close()` or a failed `reconnect`, every accessor/setter/property (`get_wavelength`, `get_intensity`, `get_spectrum`, `set_integration_time_micros`, `integration_time_limit_us`, `device_max_intensity`, `device_pixel_count`) dereferences `self.spec` directly and raises a raw `AttributeError` (`'NoneType' object has no attribute ...`), **not** a typed `bsl_type` exception. Do not call these after closing.
- **`set_integration_time_micros` has no readback and no range check.** It does not verify the hardware accepted the value, and seabreeze exposes no getter to confirm it. Always validate `exp_us` against `integration_time_limit_us` yourself before calling; out-of-range only fails downstream as a `SeaBreezeError`.
- **`get_intensity` / `get_spectrum` block** for ~the integration time plus USB transfer. Long exposures stall the calling thread — size your timeouts accordingly.
- **`get_wavelength` does not cost an exposure** (cached calibration), but `get_intensity` / `get_spectrum` each trigger a fresh hardware acquisition.
- **Correction flags can raise:** setting `correct_dark_counts` / `correct_nonlinearity` on a unit that lacks the EEPROM data raises a `SeaBreezeError` that this driver does **not** wrap.
- **Serial selection is substring containment**, not an exact match: line 69 tests `device_sn in str(sb.list_devices())` against the repr of the whole device list. An ambiguous/partial serial can false-match or bind the wrong unit. Prefer an exact, full serial string.
- **`reconnect(device_sn=...)` permanently mutates** the stored target serial — all later `reconnect()` / `reset_connection()` calls use the new value.
- **`reconnect()` / `reset_connection()` swallow exceptions and return `False`** instead of raising. Always check the returned boolean.
- **`close()` logs `CLOSED ... success` on every call**, including no-ops and after a failed connect (via `__del__`). Do not treat that log line as proof a handle was actually open.
- **Missing dependency:** if the `seabreeze` package is not importable, the module sets `sb = None` and the constructor raises `bsl_type.DeviceConnectionFailed`.
- **Pixel edges:** the first/last pixels of the array may be optically inactive — interpret edge values with care.
- No destructive actions: this device emits no light and performs no motion.

## Audit notes (2026-06-28)
- **Fixed:**
  - `get_spectrum()` now performs exactly **one** hardware acquisition. Previously it triggered two acquisitions and discarded the first (doubling the block time and returning the second frame); it now returns the single acquired spectrum directly, so the returned data corresponds to one exposure of expected duration.
- **Known / deferred:** No outstanding issues recorded for this module.
