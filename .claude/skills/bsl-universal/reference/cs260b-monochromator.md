# CS260B — Newport/Oriel Cornerstone CS260B-Q-MC-D scanning monochromator (wavelength selector with grating turret, filter wheel, input shutter, and dual output ports)

> **Factory:** `from bsl_universal.instruments import CS260B` then `CS260B(device_sn="")`
> **Transport:** VISA (ASCII Cornerstone command set over an internal `_bsl_visa` wrapper) · **Datasheet:** `CS260B-Datasheet-121020.pdf` and `Cornerstone_CS260B_User_Manual.pdf` (both in `_datasheet/`) · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_CS260B.py`

## When to use this
Pick the CS260B when an experiment needs a **single, tunable narrow band of light** selected from a broadband source: spectral response / quantum-efficiency sweeps, wavelength-dependent characterization of detectors or biosensors, or any measurement that scans wavelength from ~250 nm to 2500 nm. The driver handles grating and order-sorting-filter selection automatically as a function of the requested wavelength, so in the common case you only call `set_wavelength()`, then `open_shutter()`, then read back. Use the dedicated detector/power-meter drivers (e.g. PM100D) to measure the light this instrument produces. See [runtime & construction](00-runtime-and-construction.md) for the factory/registry mechanics and the `.safe` recovery layer.

## Construct & tear down
```python
from bsl_universal.instruments import CS260B

# device_sn selects WHICH CS260B to bind when several are attached; "" auto-selects
# the first matching unit. NOTE: constructing the object immediately performs HARDWARE
# MOTION — it homes the grating, moves to 450 nm, and cycles gratings 1->2->3->4 during
# init (see __equipmnet_init). Make sure the optical path can tolerate that before connecting.
mono = CS260B(device_sn="")            # or CS260B("your_serial_here")

try:
    # Move to 532 nm. Grating and order-sorting filter are auto-selected from the
    # wavelength. RETURN IS A STATUS CODE (0 ok / -1 out-of-range), NOT a wavelength.
    status = mono.set_wavelength(532.0, auto_grating=True, auto_filter=True)
    if status != 0:
        raise RuntimeError("wavelength out of range")

    mono.open_shutter()                # exposes light; verified via readback
    print("wavelength:", mono.get_wavelength(), "nm")
    print("grating:", mono.get_grating(), " filter:", mono.get_filter())
finally:
    mono.close()                       # writes SHUTTER 0 (closes shutter) THEN releases the port
```
`close()` is not a pure resource release: it best-effort calls `close_shutter()` (a real hardware write) before closing the transport, then sets `_com = None`. It is also invoked from `__del__`.

## Most-used operations

### `set_wavelength(wavelength: float = 0.0, auto_grating: bool = True, auto_filter: bool = True) -> int`
- **Does:** Sends `GOWAVE {wavelength:.3f}` to move the wavelength drive. If `auto_grating`, selects the grating from the wavelength first; if `auto_filter`, selects the order-sorting filter first. Blocks until idle, then verifies via readback.
- **Args:** `wavelength`: float, **nm**, accepted range `0 <= wavelength <= 2500` inclusive (validated as `wavelength < 0 or wavelength > 2500`); `0.0` requests broad-spectrum / zero-order; docstring notes recommended optical range 250–2500 nm. `auto_grating`: bool, default True. `auto_filter`: bool, default True (note: the docstring text says "Default: False" but the code default is True).
- **Returns:** `int` status code — `0` on success, `-1` if out of range. NOT the achieved wavelength. (Source annotation reads `-> int` after the 2026-06-28 audit; see Audit notes.) To read the real value call `get_wavelength()`.
- **Blocks?** Yes — calls `get_idle(blocking=True)` (and moves grating/filter, which each block too).
- **Readback?** Yes — compares `round(get_wavelength())` to `round(wavelength)`; raises on mismatch. Verification rounds to integer nm, so sub-0.5 nm positioning errors pass silently.
- **Raises:** `bsl_type.DeviceInconsistentError` on readback mismatch; `bsl_type.DeviceTimeOutError` if idle wait times out. Out-of-range input does **not** raise — it returns `-1`.
- **Example:** `mono.set_wavelength(880.0)  # auto grating G3, auto filter F2`

### `set_grating(grating: int) -> int`
- **Does:** Sends `GRATing {grating}` to rotate the grating turret. No-op (returns 0) if already on that grating. Blocks until idle, then verifies. Normally driven automatically by `set_wavelength`; manual use is discouraged in the docstring.
- **Args:** `grating`: int, dimensionless, valid `1..4` inclusive (`grating < 1 or grating > 4`). All four are 600 lines/mm; blaze wavelengths G1=400 nm, G2=600 nm, G3=1000 nm, G4=1850 nm.
- **Returns:** `int` — `0` success, `-1` out of range.
- **Blocks?** Yes (`get_idle(blocking=True)`).
- **Readback?** Yes — `get_grating()`; raises on mismatch.
- **Raises:** `bsl_type.DeviceInconsistentError` on mismatch; `DeviceTimeOutError` on idle timeout. Out-of-range returns `-1`, no raise.
- **Example:** `mono.set_grating(3)`

### `set_filter(filter: int = 5) -> int`
- **Does:** Sends `FILTER {filter}` to rotate the filter wheel. No-op (returns 0) if already there. Blocks until idle, then verifies.
- **Args:** `filter`: int, dimensionless, valid `1..6` inclusive (`filter < 1 or filter > 6`). F1=335 nm long-pass, F2=590 nm long-pass, F3=1000 nm long-pass, F4=1500 nm long-pass, F5/F6=open (no filter). Default `5` = open.
- **Returns:** `int` — `0` success, `-1` out of range.
- **Blocks?** Yes.
- **Readback?** Yes — `get_filter()`; raises on mismatch.
- **Raises:** `bsl_type.DeviceInconsistentError` on mismatch; `DeviceTimeOutError` on idle timeout. Out-of-range returns `-1`, no raise.
- **Example:** `mono.set_filter(2)`

### `open_shutter() -> int`
- **Does:** Sends `SHUTTER 1` to open the input shutter (light passes), blocks until idle, then verifies.
- **Args:** none.
- **Returns:** `int` — `0` on success.
- **Blocks?** Yes (`get_idle(blocking=True)`).
- **Readback?** Yes — `get_shutter_status()`; raises if not `1`.
- **Raises:** `bsl_type.DeviceInconsistentError` if the shutter did not report open; `DeviceTimeOutError` on idle timeout.
- **Example:** `mono.open_shutter()`

### `close_shutter() -> bool`
- **Does:** Sends `SHUTTER 0` to close the input shutter, blocks until idle, then verifies. Also called automatically by `close()`.
- **Args:** none.
- **Returns:** `int` `0` on success (annotation says `bool`, but the body returns `0`).
- **Blocks?** Yes.
- **Readback?** Yes — `get_shutter_status()`; raises if not `0`.
- **Raises:** `bsl_type.DeviceInconsistentError` if the shutter did not report closed; `DeviceTimeOutError` on idle timeout.
- **Example:** `mono.close_shutter()`

### `get_wavelength() -> float`
- **Does:** Queries `WAVE?` and parses the reply as float. Read-only — this is the safe way to read the actual current wavelength.
- **Args:** none.
- **Returns:** `float`, **nm**.
- **Blocks?** No (single query).
- **Readback?** N/A (this *is* the readback).
- **Raises:** propagates transport/parse errors (e.g. `float()` failure).
- **Example:** `wl = mono.get_wavelength()`

### `get_idle(blocking: bool = False, timeout_sec: int = 15) -> int`
- **Does:** Queries `IDLE?` for motion/operation status. If `blocking=True`, polls every 0.5 s (2 Hz) until READY or timeout. Called internally after every state-changing write to serialize motion.
- **Args:** `blocking`: bool, default False. `timeout_sec`: int, **seconds**, default 15.
- **Returns:** `int` — `0` BUSY, `1` READY.
- **Blocks?** Yes when `blocking=True` (up to `timeout_sec`).
- **Readback?** N/A.
- **Raises:** `bsl_type.DeviceTimeOutError` if `timeout_sec` is exceeded while blocking.
- **Example:** `mono.get_idle(blocking=True, timeout_sec=30)`

### `get_errors() -> int`
- **Does:** Drains the device error queue by querying `SYSTEM:ERROR?` repeatedly (up to 10 reads). Returns `0` if the queue is clean (first code `'0'` or `'501'`, or it drains to clean within the loop); otherwise raises. Called during init (`__equipmnet_init`).
- **Args:** none.
- **Returns:** `int` `0` when the queue is clean.
- **Blocks?** Effectively no (a bounded query loop, no `get_idle`).
- **Readback?** N/A.
- **Raises:** `bsl_type.DeviceOperationError` if the queue never clears within ~10 reads.
- **Example:** `mono.get_errors()`

## Full method index
| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `CS260B(device_sn="")` | constructor / factory | Connect, retry up to 3×, run startup init (homes grating, sets 450 nm, cycles gratings 1–4) | `device_sn`: str (serial selector; `""`=first match) | `CS260B` instance |
| `reconnect(device_sn="", run_init=True)` | method | `close()` then re-open VISA; optionally rerun init | `device_sn`: str; `run_init`: bool | `bool` (True on success) |
| `reset_controller(run_init=True)` | method | Recover to ready: wait idle, home grating, optionally rerun init | `run_init`: bool | `bool` (True on success; False on any caught exception) |
| `set_wavelength(wavelength=0.0, auto_grating=True, auto_filter=True)` | method | Move wavelength drive; auto grating/filter; verify | `wavelength`: float (nm, 0–2500); `auto_grating`/`auto_filter`: bool | `int` (0 ok / -1 range) |
| `set_grating(grating)` | method | Select grating turret position; verify | `grating`: int (1–4) | `int` (0 ok / -1 range) |
| `set_filter(filter=5)` | method | Select filter-wheel position; verify | `filter`: int (1–6; 5/6=open) | `int` (0 ok / -1 range) |
| `set_output_axial()` | method | Route output to AXIAL port (writes `OUTPORT L`, see swap note); verify | none | `int` (0 ok) |
| `set_output_lateral()` | method | Route output to LATERAL port (writes `OUTPORT A`, see swap note); verify | none | `int` (0 ok) |
| `open_shutter()` | method | Open input shutter (`SHUTTER 1`); verify | none | `int` (0 ok) |
| `close_shutter()` | method | Close input shutter (`SHUTTER 0`); verify | none | `int` 0 (annotated `bool`) |
| `get_wavelength()` | method | Query current wavelength (`WAVE?`) | none | `float` (nm) |
| `get_grating()` | method | Query current grating (`GRATing?`, field 0 of CSV reply) | none | `int` (1–4) |
| `get_filter()` | method | Query current filter position (`FILTER?`) | none | `int` (1–6) |
| `get_shutter_status()` | method | Query shutter state (`SHUTTER?`): `'O'`→1, `'C'`→0, else −1 | none | `int` (1 open / 0 closed / −1 unknown) |
| `get_idle(blocking=False, timeout_sec=15)` | method | Query motion status (`IDLE?`); optionally block-poll | `blocking`: bool; `timeout_sec`: int (s) | `int` (0 BUSY / 1 READY) |
| `get_output_port()` | method | Query active port (`OUTPORT?`): 1=LATERAL, 2=AXIAL (driver labelling) | none | `int` (1 or 2) |
| `get_error_legacy()` | method | Query single legacy error byte (`ERROR?`); log + raise if non-zero | none | `int` (0 = no error) |
| `get_errors()` | method | Drain system error queue (`SYSTEM:ERROR?`); raise if it won't clear | none | `int` (0 = clean) |
| `close()` | method | Best-effort `close_shutter()`, then close transport, set `_com=None` | none | `None` |
| `CONNECT_RETRY_COUNT` | class attr | Connection retry count | — | `int` = 3 |
| `CONNECT_RETRY_DELAY_SEC` | class attr | Delay between connection retries (s) | — | `float` = 0.75 |

Private/internal helpers (do **not** call directly; surfaced for understanding only): `__visa_connect()` (VISA connect with bounded retries), `__equipmnet_init()` (startup sequence — note the misspelled name), `__set_gethome()` (issues `FINDHOME`), `__auto_grating(wavelength)`, `__auto_filter(wavelength)`, `__del__`.

## Units, ranges & limits
- **Wavelength:** float, nm. Accepted by `set_wavelength`: `0 <= wl <= 2500`. `0.0` = broad-spectrum / zero order. Recommended optical range per docstring: 250–2500 nm.
- **Auto-grating thresholds** (`__auto_grating`): `wl < 558` → G1; `< 746` → G2; `< 1350` → G3; else (≥1350) → G4.
- **Auto-filter thresholds** (`__auto_filter`): `wl < 355` → F5 (open); `< 610` → F1; `< 1020` → F2; `< 1520` → F3; `< 2000` → F4; **`wl >= 2000` → no branch fires** (filter left at whatever it was).
- **Gratings:** ids `1..4`, all 600 lines/mm. Blaze: G1=400 nm, G2=600 nm, G3=1000 nm, G4=1850 nm. Mechanical operation order is `#1 -> #3 -> #2 -> #4` (per docstring), not numeric order.
- **Filters:** ids `1..6`. F1=335 nm LP (worst-case cuton 315 nm), F2=590 nm LP (570 nm), F3=1000 nm LP (980 nm), F4=1500 nm LP (cuton unknown), F5/F6=open (no filter). Default filter arg = 5.
- **Output ports:** `get_output_port()` returns 1 = LATERAL, 2 = AXIAL (driver labelling). Only one port is active at a time.
- **Shutter status:** 1 = open, 0 = closed, −1 = unknown/unexpected reply.
- **Idle / timing:** `get_idle` returns 0 BUSY / 1 READY; default `timeout_sec = 15`; blocking poll interval 0.5 s.
- **Connection retries:** `CONNECT_RETRY_COUNT = 3`, `CONNECT_RETRY_DELAY_SEC = 0.75` s.
- **Init setpoint:** construction sets wavelength to **450.0 nm** and cycles gratings 1→2→3→4.

## Safety & gotchas
- **Construction moves hardware.** `CS260B(...)` runs `__equipmnet_init`: homes the grating (`FINDHOME`), moves to 450 nm, then sequentially sets gratings 1,2,3,4. Physical motion (seconds to tens of seconds, blocking) happens on connect — ensure the optical path is safe before instantiating.
- **`close()` writes to hardware.** It best-effort closes the shutter (`SHUTTER 0`) before releasing the port, and is called from `__del__`. It is not a pure resource release.
- **Return values are status codes, not readings.** `set_wavelength` / `set_grating` / `set_filter` return `0`/`-1`, NOT the achieved value. Use `get_wavelength()` / `get_grating()` / `get_filter()` to read actual state.
- **Out-of-range does not raise.** `set_wavelength`/`set_grating`/`set_filter` return `-1` (and log) for out-of-range args without raising. You MUST check the return value. Only readback mismatches raise `DeviceInconsistentError`.
- **Wavelength verification rounds to integer nm.** `round(cur) != round(target)` means positioning errors up to ~0.5 nm pass silently — do not rely on this check for sub-nm accuracy.
- **Auto-filter has a coverage gap.** For `wl >= 2000` nm (still inside the accepted 0–2500 range) `__auto_filter` makes **no** `set_filter` call, so the filter wheel keeps its prior position — potentially the wrong order-sorting filter for a 2000–2500 nm setpoint. Set the filter explicitly in that band, or pass `auto_filter=False` and manage it yourself.
- **Output-port command letters are deliberately swapped.** `set_output_axial()` sends `OUTPORT L` and `set_output_lateral()` sends `OUTPORT A` — intentional per an in-code note about a datasheet/firmware label inconsistency (axial expects readback `2`, lateral expects `1`). Verify against your physical hardware before trusting port routing.
- **Blocking is pervasive.** Nearly every state-changer calls `get_idle(blocking=True)` (default 15 s timeout, 2 Hz poll) and so blocks the calling thread; on timeout they raise `DeviceTimeOutError`.
- **No `_com` None-guard on operational methods.** Calling any command/query method after `close()` (when `_com` is `None`) raises a raw `AttributeError`, not a typed `bsl_type` exception. Reconnect with `reconnect()` instead of reusing a closed handle.
- **Mislabeled / misspelled log and docstring text.** E.g. `close_shutter` logs "Failed to open the input shutter!" on a failed close; `get_error_legacy` logs code 3 as "Error 2"; the init helper is spelled `__equipmnet_init`. Do not rely on log text for code identity.
- **Recovery layer:** wrap a call in `dev.safe.<method>()` to get the runtime's retry behavior (e.g. `mono.safe.set_wavelength(532.0)`). `.safe` is method-only — see [runtime & construction](00-runtime-and-construction.md). Use `reset_controller()` (wait idle → home → re-init) or `reconnect()` for deeper recovery; note `reset_controller` swallows exceptions and only returns `True`/`False`.
- **Prefer the public factory** `bsl_universal.instruments.CS260B` over importing the private `_CS260B` module path.

## Audit notes (2026-06-28)
- **Fixed:**
  - `get_errors()` raises `bsl_type.DeviceOperationError` only CONDITIONALLY — when the system error queue never clears within ~10 reads. It returns `0` (clean success path) if the first reply code is `'0'` or `'501'`, or if the queue drains to clean within the loop (post-loop `return 0`). A clean queue is a normal, non-raising success; treat a raised `get_errors()` as "the error queue would not clear."
  - `set_wavelength`'s return annotation is now `-> int` (it returns an int status code, `0` on success / `-1` out of range), not `-> float`. Do not treat its return as the achieved wavelength; read the actual value with `get_wavelength()`.
- **Known / deferred:**
  - No outstanding issues recorded for this module.
