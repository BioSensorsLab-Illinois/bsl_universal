# SP-2150 Monochromator — Princeton Instruments / Acton SP-2150i scanning monochromator (serial-controlled grating spectrometer)

> **Factory:** `from bsl_universal.instruments import SP_2150` then `SP_2150(device_sn="")`
> **Transport:** Serial (9600 baud, via `bsl_serial`) · **Datasheet:** `SP-2150i.pdf` (in `_datasheet/`) · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_SP_2150.py`

## When to use this

Pick this instrument when an experiment needs to select a specific output wavelength from a broadband source (e.g. building a tunable monochromatic beam for spectral-response / responsivity sweeps, calibration, or wavelength-resolved illumination). The SP-2150i is a dual-grating scanning monochromator: you command a target wavelength in nm and optionally switch between its two installed gratings to cover different spectral spans / resolutions. It does **not** measure light — pair it with a power meter or detector (e.g. a Thorlabs PM100D/PM400) downstream to read the resulting intensity. Use it whenever a workflow says "set the wavelength" / "scan from λ1 to λ2" against this monochromator.

## Construct & tear down

```python
from bsl_universal.instruments import SP_2150
import time

# Construction auto-discovers the SP-2150i on the serial bus and performs a
# blocking power-on MONO-RESET (~5 s sleep) before returning a ready instrument.
mono = SP_2150(device_sn="")          # "" = first matching SP-2150i found on the bus
try:
    mono.set_grating(1)               # select grating 1 (turret move ~20 s on hardware)
    time.sleep(20)                    # driver does NOT wait for the move — add your own settle delay
    mono.set_wavelength(532)          # command move to 532 nm (no readback, no range check)
    time.sleep(2)                     # allow the move to settle before reading back
    nm = mono.get_wavelength()        # -> float, e.g. 532.0  (confirm the move yourself)
    print("at", nm, "nm on grating", mono.get_grating())
finally:
    mono.close()
```

`device_sn` is an optional substring selector matched against the discovered serial number. `""` (default) picks the **first** SP-2150i found on the serial bus — non-deterministic if more than one unit is connected; pass a specific S/N substring to disambiguate.

## Most-used operations

### `set_wavelength(self, wavelength) -> None`
- **Does:** Commands the monochromator to move to `wavelength`, sending the raw Acton command `"<wavelength> GOTO"` over serial.
- **Args:** `wavelength` (documented as `int`, **unit: nm**). **No range validation and no type coercion in the driver** — the value is string-formatted verbatim into the command. A float serializes with a decimal point (e.g. `500.0 GOTO`), which may not match the device's expected format.
- **Returns:** `None` (does **not** return or verify the achieved wavelength).
- **Blocks?** Sends one command and returns as soon as the device replies `ok`. It does **not** wait for the physical grating move to settle.
- **Readback?** **No.** Does not query `?NM` to confirm. Call `get_wavelength()` yourself after a settle delay.
- **Raises:** `bsl_type.DeviceOperationError` if the device reply does not contain `ok`. Raw `AttributeError` if called after `close()` (see Safety).
- **Example:** `mono.set_wavelength(650)`

### `get_wavelength(self) -> float`
- **Does:** Queries `?NM` and parses the numeric wavelength from the reply.
- **Args:** none.
- **Returns:** `float` — current wavelength in **nm** (e.g. `250.0`).
- **Blocks?** One blocking serial query (transport readline timeout ~0.1 s).
- **Readback?** N/A — this *is* the readback primitive for wavelength.
- **Raises:** `IndexError` (uncaught) if the reply contains no decimal-formatted number — e.g. on a timeout, empty, or garbled response. Raw `AttributeError` if called after `close()`.
- **Example:** `nm = mono.get_wavelength()`

### `set_grating(self, grating) -> None`
- **Does:** Selects grating 1 or 2, sending `"<grating> GRATING"`. Per the device docstring this takes ~20 s and moves to the previous wavelength (or 200 nm default if that wavelength is unreachable by the selected grating).
- **Args:** `grating` — enum **{1, 2}** only (grating index, unitless). Validated: any other value logs `"Grating must be 1 or 2"` and raises `bsl_type.DeviceOperationError`. Note the check is `grating != 1 and grating != 2`, so floats `1.0`/`2.0` slip through and are sent as e.g. `1.0 GRATING`.
- **Returns:** `None`.
- **Blocks?** Returns as soon as the device replies `ok`; does **not** wait for the ~20 s turret move.
- **Readback?** **No.** Does not call `get_grating()` to confirm.
- **Raises:** `bsl_type.DeviceOperationError` (bad grating value, or device did not reply `ok`). Raw `AttributeError` if called after `close()`.
- **Example:** `mono.set_grating(2)`

### `get_grating(self) -> int`
- **Does:** Queries `?GRATING` and parses the grating index from the reply.
- **Args:** none.
- **Returns:** `int` — current grating index (1 or 2).
- **Blocks?** One blocking serial query.
- **Readback?** N/A — this *is* the readback primitive for grating.
- **Raises:** `IndexError` (uncaught) on an empty/garbled reply. Raw `AttributeError` if called after `close()`.
- **Caveat:** parses the **first single digit anywhere** in the reply (`re.findall(r"\d", ...)[0]`); if the device prefixes the grating number with any other digit, the returned value may be wrong.
- **Example:** `g = mono.get_grating()`

### `reset_controller(self) -> bool`
- **Does:** Runs the power-on `MONO-RESET` sequence on demand (same sequence the constructor runs).
- **Args:** none.
- **Returns:** `bool` — `True` on success, `False` if any exception occurred (the error is logged, not raised).
- **Blocks?** Yes — sleeps a fixed 5 s after issuing the reset; physically resets the monochromator.
- **Readback?** No — only checks for `ok` in the reply; the 5 s wait is a blind fixed delay, not a poll.
- **Raises:** Nothing — swallows all exceptions into a `False` return. A dead serial handle therefore returns `False` rather than surfacing the cause.
- **Example:** `if not mono.reset_controller(): ...  # handle failure`

### `reconnect(self, device_sn: str = "", reset_controller: bool = True) -> bool`
- **Does:** Closes the current serial connection and re-establishes it, optionally re-running `MONO-RESET`.
- **Args:** `device_sn: str` selector override (`""` keeps the existing target); `reset_controller: bool` (default `True`) — if `True`, runs the power-on reset after reconnecting.
- **Returns:** `bool` — `True` on success, `False` if all retry attempts fail (does **not** raise).
- **Blocks?** Yes — closes then reopens serial; with `reset_controller=True` also sleeps 5 s. Retries up to 3 attempts × 2 s delay.
- **Readback?** No.
- **Raises:** Returns `False` instead of raising on connection failure — the caller must check the return value.
- **Example:** `mono.reconnect(reset_controller=False)  # restore a closed handle without a hardware reset`

### `close(self) -> None`
- **Does:** Closes the underlying serial resource (best-effort) and nulls the handle (`self._com = None`).
- **Args:** none.
- **Returns:** `None`.
- **Blocks?** No.
- **Readback?** N/A.
- **Raises:** Safe to call when the handle is already missing/`None` (uses `getattr` + try/except). **Does not** make the object reusable — after `close()`, any `set_*`/`get_*` call raises a raw `AttributeError`; use `reconnect()` to restore.
- **Example:** `mono.close()`

## Full method index

| name | kind | purpose | key args (units) | returns |
| --- | --- | --- | --- | --- |
| `SP_2150` (factory) | function | Construct + connect the driver (intended public entry point) | `device_sn: str = ""` (S/N substring) | connected `SP_2150` (factory-wrapped) |
| `__init__` | method | Driver constructor; connect w/ retry + power-on reset | `device_sn: str = ""` | `None` (raises `DeviceConnectionFailed`) |
| `set_wavelength` | method | Command move to a wavelength (`<nm> GOTO`) | `wavelength` (nm; **no validation**) | `None` |
| `get_wavelength` | method | Query current wavelength (`?NM`) | none | `float` (nm) |
| `set_grating` | method | Select grating (`<n> GRATING`) | `grating` (enum {1,2}) | `None` |
| `get_grating` | method | Query current grating (`?GRATING`) | none | `int` (1 or 2) |
| `reset_controller` | method | On-demand power-on `MONO-RESET` | none | `bool` |
| `reconnect` | method | Close + re-open serial, optional reset | `device_sn: str = ""`, `reset_controller: bool = True` | `bool` |
| `close` | method | Close serial + null handle | none | `None` |
| `device_id` | attribute | Discovered device id string (set on connect) | — | `str` |
| `inst` | attribute | Instrument metadata record (`inst.SP_2150`) | — | metadata obj |
| `logger` | attribute | `bsl_logger` instance for this device | — | logger obj |
| `CONNECT_RETRY_COUNT` | class const | Connect retry attempts (= 3) | — | `int` |
| `CONNECT_RETRY_DELAY_SEC` | class const | Delay between retries (= 2 s) | — | `int` |
| `_serial_connect` | method *(internal)* | Build the `bsl_serial` transport | none | `bsl_serial` or `None` |
| `_com_query` | method *(internal)* | Write a command, read a line reply | `msg`, `timeout=0.5` *(timeout unused)* | `str` |
| `_com_cmd` | method *(internal)* | Write a command, require `ok` reply | `msg`, `timeout=0.5` *(timeout unused)* | `int` (0) |

(`__init_reset`, `__del__` are name-mangled / dunder internals; not agent-callable.)

## Units, ranges & limits

- **Wavelength:** nm. The driver imposes **no min/max bounds** — any value (including negative, zero, or wavelengths unreachable by the active grating) is sent verbatim. Hard wavelength limits live in the hardware/grating, not in this code; consult `SP-2150i.pdf`.
- **Grating:** integer index, valid set **{1, 2}** (enforced for ints; floats `1.0`/`2.0` are not rejected).
- **Grating switch time:** ~20 s on hardware (per docstring); the driver does **not** wait.
- **Constructor / reset delay:** fixed `time.sleep(5)` after `MONO-RESET`.
- **Connect retries:** `CONNECT_RETRY_COUNT = 3`, `CONNECT_RETRY_DELAY_SEC = 2` s between attempts.
- **Baud rate:** fixed at 9600 (instrument header). The `timeout=0.5` parameter on `_com_query`/`_com_cmd` is **dead code** — it does not change the serial read timeout (transport uses its own ~0.1 s readline timeout).
- **Protocol commands used:** `GOTO`, `?NM`, `GRATING`, `?GRATING`, `MONO-RESET` (Acton/Princeton serial protocol).

## Safety & gotchas

- **Construction moves hardware.** Every `SP_2150()` performs a physical power-on `MONO-RESET` and blocks ~5 s (plus up to 3 × 2 s connect retries). This is **not** a pure "open handle" call — do not construct it casually mid-experiment.
- **No motion blocking and no readback on set operations.** `set_wavelength` and `set_grating` return as soon as the device replies `ok`; they do **not** wait for the physical move (a grating change is ~20 s) and do **not** verify the result. **You must add your own settle delay and confirm with `get_wavelength()` / `get_grating()`.** Subsequent commands can otherwise race an in-progress move.
- **No wavelength range check.** Out-of-range or wrong-grating wavelengths are sent straight to the hardware. Keep the requested wavelength within the active grating's usable span (see datasheet) — the driver will not protect you.
- **Parsing fragility on bad replies.** `get_wavelength` (`\d+\.\d+`) and `get_grating` (`\d`) index `[0]` with no guard — a timed-out/empty/garbled reply raises an uncaught `IndexError` (not a typed `bsl_type` exception). `get_grating` returns the *first digit anywhere* in the reply, so a noisy or unexpectedly-formatted response can yield the wrong grating.
- **Float grating values bypass validation.** `set_grating(1.0)` passes the `!= 1 and != 2` check and is sent as `1.0 GRATING`, which the device may reject. Always pass plain ints.
- **Object is not reusable after `close()`.** `close()` sets `self._com = None`; any later `set_*`/`get_*` raises a raw `AttributeError`. Use `reconnect()` to restore a working handle. `close()` also emits a `"CLOSED - Monochromator"` success log even when nothing was open (e.g. double-close).
- **Recovery layer.** The factory-wrapped instrument exposes a method-only recovery namespace: call `mono.safe.<method>(...)` (e.g. `mono.safe.set_wavelength(532)`) to retry a transient failure through the managed runtime. `.safe` is **method-only** (not for attribute access) — see [runtime & construction](00-runtime-and-construction.md).
- **Selector ambiguity.** `device_sn=""` selects the first SP-2150i on the bus; with multiple units this is non-deterministic. Pass a specific S/N substring.

## Audit notes (2026-06-28)

- **Fixed:**
  - `_com_query` no longer mis-detects an empty response as a command echo. Previously the reversed/fragile substring check `if resp in msg` treated an empty/blank reply (which is a substring of any string) as an echo and issued an extra blocking `readline()`, so a serial timeout could swallow the real reply or block; reads on `?NM`/`?GRATING` are now more robust against empty/timed-out responses.

- **Known / deferred:**
  - `set_wavelength` still has **no range validation and no readback verification**. Do not rely on it to reject bad wavelengths or to confirm the move — always (a) keep the requested wavelength within the active grating's span yourself, and (b) call `get_wavelength()` after a settle delay to verify the hardware actually reached the target before trusting any downstream measurement.
