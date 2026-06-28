# USB_520 — Futek USB-520 USB load-cell / force-sensor digital interface (reads force in grams over a serial ASCII stream)

> **Factory:** `from bsl_universal.instruments import USB_520` then `USB_520(device_sn='', tear_on_startup=True, reverse_negative=True)`
> **Transport:** Serial (pyserial via `bsl_serial`; device enumerates as a USB virtual COM port) · **Datasheet:** none on disk · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_Futek_USB_520.py`

## When to use this
Pick this driver when you need to read **force / load measurements in grams** from a Futek load cell wired through a USB-520 digital DAC. It is a **read-only** sensor interface: it streams ASCII lines like `+12.345 g`, parses the float, and returns it. Use it for force-vs-time logging, contact-force monitoring during alignment/indentation, or any experiment that needs a tared (zeroed) load reading. There is no actuation here — it never commands the device, only listens.

## Construct & tear down
```python
from bsl_universal.instruments import USB_520

# device_sn selects which physical unit to talk to:
#   ''      -> auto-probe the four hard-coded lab channels CH1..CH4 in order, take the first that responds
#   'CH1'.. -> channel alias, resolved through USB_520_SN to a numeric serial number
#   '1066656' (raw numeric SN string) -> connect to that exact device
sensor = USB_520(device_sn="CH1", tear_on_startup=True, reverse_negative=True)
try:
    force_g = sensor.get_new_measurement(timeout_ms=5000, enable_tear=True)
    print(f"Force: {force_g:.3f} g")
finally:
    sensor.close()
```
`device_sn` chooses the target. Note the constructor **blocks**: with `tear_on_startup=True` it averages 10 reads, each able to block up to the 10 s default timeout, so a silent sensor can hang the constructor for ~100 s before `DeviceTimeOutError` propagates. See [runtime & construction](00-runtime-and-construction.md) for the shared lifecycle and `.safe` recovery layer.

## Most-used operations

### `USB_520(device_sn='', tear_on_startup=True, reverse_negative=True)`
- **Does:** Resolves a `CHx` alias to a numeric SN (only if the string contains the substring `"CH"`), opens the serial transport with bounded retries (3 attempts, 0.5 s apart), and — if `tear_on_startup` — runs a 10-sample averaged tare. Stores `self.flip_result = reverse_negative`.
- **Args:**
  - `device_sn: str` — unitless identifier. `''` = auto-probe CH1..CH4; a string containing `"CH"` (e.g. `'CH1'..'CH4'`) = alias looked up in `USB_520_SN` (unknown alias raises); otherwise treated as a raw numeric SN string (e.g. `'1066656'`).
  - `tear_on_startup: bool` — default `True`. If True, calls `set_tear_calibration()` (10 samples) at startup.
  - `reverse_negative: bool` — default `True`. If True, **every** returned force is multiplied by -1 (the docstring's "for positive values" is wrong; the sign flip is unconditional).
- **Returns:** A connected `USB_520` instance. (The docstring's "status int 0" is wrong — `__init__` returns `None` or raises.)
- **Blocks?** Yes — connection plus (optionally) up to ~100 s of tare reads.
- **Readback?** Connection only: validates `serial_port is not None` and `serial_port.is_open`. No force-state to verify (device is read-only).
- **Raises:** `bsl_type.DeviceConnectionFailed` (unknown `CHx` alias, or no device responds after retries / across all auto-probe channels); `bsl_type.DeviceTimeOutError` can escape from the startup tare.
- **Example:** `s = USB_520("1066658", tear_on_startup=False)`

### `get_new_measurement(timeout_ms=10000, enable_tear=True) -> float`
- **Does:** Sets the serial read timeout, flushes the read buffer, then reads lines until one contains a `g` token; parses the float grams value, applies sign flip if `reverse_negative` was set at construction, subtracts the stored tare if `enable_tear`, and returns it. If a line fails to parse, it logs and retries within the deadline.
- **Args:**
  - `timeout_ms: int` — milliseconds, default `10000`. Used **both** as the per-`readline` serial timeout (`timeout_ms/1000` s) **and** the overall loop deadline. Non-positive → effectively immediate timeout.
  - `enable_tear: bool` — default `True`. If True, subtract `self.tear_calibration` (grams).
- **Returns:** `float`, force in **grams**. Sign-flipped if `reverse_negative`; tare-subtracted if `enable_tear`.
- **Blocks?** Yes — up to ~`timeout_ms` (worst case longer; see deferred note about per-readline timeout).
- **Readback?** N/A — read-only operation, no commanded state.
- **Raises:** `bsl_type.DeviceTimeOutError` if no parseable `g` line arrives before the deadline. If `self.serial` is `None` (e.g. after `close()`), raises a raw `AttributeError` (not a typed bsl_type error).
- **Example:** `f = sensor.get_new_measurement(timeout_ms=2000)`

### `set_tear_calibration(average_count=10) -> float`
- **Does:** Takes `average_count` fresh measurements (each with `enable_tear=False`), stores their mean in `self.tear_calibration`, and returns it. This becomes the zero offset subtracted by later `get_new_measurement(enable_tear=True)` calls.
- **Args:** `average_count: int` — sample count, default `10`, **must be ≥ 1** (validated). Each sample uses the default 10000 ms timeout and can block accordingly.
- **Returns:** `float` — the new tare value in grams (also stored in `self.tear_calibration`).
- **Blocks?** Yes — up to `average_count × 10 s`.
- **Readback?** N/A (value is computed from reads).
- **Raises:** `bsl_type.DeviceOperationError` if `average_count < 1`; `bsl_type.DeviceTimeOutError` if any underlying read times out.
- **Example:** `tare = sensor.set_tear_calibration(average_count=20)`

### `reset_tear_calibration(average_count=10) -> bool`
- **Does:** Convenience wrapper that re-runs `set_tear_calibration` and converts the outcome to a boolean.
- **Args:** `average_count: int` — default `10`; same ≥ 1 constraint as `set_tear_calibration`.
- **Returns:** `bool` — `True` if calibration succeeded, `False` if any exception was caught and logged.
- **Blocks?** Yes — same as `set_tear_calibration`.
- **Readback?** N/A.
- **Raises:** Nothing — **swallows all exceptions** (including `DeviceTimeOutError` and the `average_count < 1` `DeviceOperationError`) and returns `False`. Caller must check the return value.
- **Example:** `if not sensor.reset_tear_calibration(): print("re-tare failed")`

### `reconnect(device_sn='', tear_on_startup=False) -> bool`
- **Does:** Closes the current connection, optionally overrides the target SN, re-opens with bounded retries, and optionally re-tares.
- **Args:**
  - `device_sn: str` — optional override; if `''`, keeps the existing `self._target_device_sn`. **Not alias-resolved** — passing `'CH1'` is used verbatim and will not match (see deferred note).
  - `tear_on_startup: bool` — default `False`; re-run tare after reconnect.
- **Returns:** `bool` — `True` on success, `False` if the connect step fails.
- **Blocks?** Yes — connect plus optional tare (up to ~100 s if `tear_on_startup=True`).
- **Readback?** Connection validated via `serial_port.is_open` inside the connect helper.
- **Raises:** `bsl_type.DeviceOperationError`/`DeviceTimeOutError` can propagate from the optional tare.
- **Example:** `sensor.reconnect(device_sn="1066657", tear_on_startup=True)`

### `close() -> None`
- **Does:** Best-effort closes the serial transport and sets `self.serial = None`. Guards the serial handle with `getattr`/None-check, so it is safe to call when already closed.
- **Args:** none.
- **Returns:** `None`.
- **Blocks?** No.
- **Readback?** N/A.
- **Raises:** Suppresses errors from the underlying close. (It always emits a `CLOSED` success log; if `self.logger` was never assigned during a very early construction failure, that log line can raise `AttributeError`.)
- **Example:** `sensor.close()`

## Full method index
| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `USB_520(...)` | constructor | connect (+ optional startup tare) | `device_sn:str`, `tear_on_startup:bool`, `reverse_negative:bool` | instance / raises |
| `get_new_measurement(...)` | method | read latest force | `timeout_ms:int (ms)`, `enable_tear:bool` | `float` (grams) |
| `set_tear_calibration(...)` | method | set zero offset from averaged reads | `average_count:int (≥1)` | `float` (grams tare) |
| `reset_tear_calibration(...)` | method | re-tare, exception→bool | `average_count:int (≥1)` | `bool` |
| `reconnect(...)` | method | close + reopen (+ optional tare) | `device_sn:str`, `tear_on_startup:bool` | `bool` |
| `close()` | method | release serial resources | — | `None` |
| `USB_520_SN` | nested enum (attr) | channel alias → numeric SN map | — | enum members (`.value` = SN string) |
| `CONNECT_RETRY_COUNT` | class attr | connect attempts | — | `int` (3) |
| `CONNECT_RETRY_DELAY_SEC` | class attr | delay between attempts | — | `float` (0.5 s) |
| `tear_calibration` | instance attr | current zero offset | — | `float` (grams) |
| `flip_result` | instance attr | whether sign is flipped (= `reverse_negative`) | — | `bool` |
| `_serial_connect()` | internal helper | bounded-retry serial open | — | `bool` |
| `__system_init(...)` | internal (name-mangled) | init tare state, optional startup tare | `tear_on_startup:bool` | `int` (0) |
| `__extract_float(msg)` | internal (name-mangled) | regex-parse grams from a line | `msg:str` | `float` or `None` |
| `__del__` / `__init__` | dunder | finalizer (calls `close()`) / constructor | — | `None` |

## Units, ranges & limits
- **Force unit: grams (g).** Not Newtons. Returned by `get_new_measurement` and `set_tear_calibration`.
- **Parse format:** a reading is only recognized if the line matches the regex `([+-]?\d+\.\d+)\s*g` — i.e. it **requires a decimal point** and a trailing `g`. Lines like `5 g` (no fractional part) are treated as "no reading" and trigger a retry.
- **Known channel serial numbers (`USB_520_SN`):** `CH1='1066656'`, `CH2='1066657'`, `CH3='1066658'`, `CH4='1066659'`. Auto-probe (`device_sn=''`) iterates only these four.
- **`timeout_ms`:** default `10000` ms; positive int expected. Drives both the per-`readline` serial timeout (`timeout_ms/1000` s) and the loop deadline.
- **`average_count`:** int, default `10`, must be `≥ 1` (enforced in `set_tear_calibration`).
- **Connect retry policy:** `CONNECT_RETRY_COUNT = 3` attempts, `CONNECT_RETRY_DELAY_SEC = 0.5` s between attempts.
- **Defaults:** `tear_on_startup=True`, `reverse_negative=True`, `enable_tear=True`.
- No explicit force min/max range, baud rate, or load-cell capacity is defined in this source (baud is governed by instrument metadata in `bsl_serial`, not visible here).

## Safety & gotchas
- **Recovery layer:** wrap calls as `sensor.safe.get_new_measurement(...)` (etc.) to get the framework's automatic retry behavior. `.safe` is **method-only** — see [runtime & construction](00-runtime-and-construction.md).
- **Blocking constructor:** with `tear_on_startup=True`, construction can block up to ~`average_count × timeout` ≈ 10 × 10 s = **~100 s** before a `DeviceTimeOutError` escapes `__init__`. Pass `tear_on_startup=False` if you need a fast, non-blocking connect, then tare explicitly when ready.
- **Sign convention:** with the default `reverse_negative=True`, **every** reading is multiplied by -1. If you expect raw-signed data, construct with `reverse_negative=False`. The constructor docstring describing this flag (and its "returns status int 0") is inaccurate — trust this reference, not the docstring.
- **Tare is implicit by default:** `get_new_measurement` subtracts `self.tear_calibration` unless you pass `enable_tear=False`. Right after construction with `tear_on_startup=False`, the tare is `0.0`.
- **Closed-instance reads throw the wrong type:** calling `get_new_measurement` after `close()` (or on a never-connected instance) raises a raw `AttributeError`, not a typed `bsl_type` exception. Don't rely on a typed error to detect "not connected" — check that you have a live connection first.
- **`reset_tear_calibration` hides failures:** it returns `False` instead of raising on any error (timeout, bad `average_count`). Always check its boolean return.
- **`CH` detection is a substring test:** `if "CH" in device_sn`. Any raw SN that happens to contain `"CH"` would be misrouted to the alias enum. Real Futek numeric SNs (e.g. `1066656`) don't, so this is only a hazard for unusual identifiers.
- **Auto-probe is lab-specific:** `device_sn=''` only tries the four hard-coded SNs CH1..CH4. Any other USB-520 unit must be addressed by its raw numeric SN.
- **Read-only device:** no write/command is ever sent for a measurement, so there is genuinely no write-readback to verify; connection success is only weakly confirmed via `serial_port.is_open`.

## Audit notes (2026-06-28)
- **Fixed:**
  - A genuine force reading of exactly `999.0 g` is no longer silently dropped. `__extract_float` now returns `None` on a parse miss (instead of the magic value `999`), and `get_new_measurement` checks `if force is None`, so a real ~999 g load is returned correctly rather than treated as "no reading."
  - `set_tear_calibration` (and therefore `reset_tear_calibration`) no longer crashes with `ZeroDivisionError` on `average_count <= 0`. It now validates the input up front and raises `bsl_type.DeviceOperationError("average_count must be >= 1")`.
- **Known / deferred:**
  - **Per-readline timeout is set to the full loop deadline**, so a single slow line started near the deadline can make `get_new_measurement` block up to **~2× `timeout_ms`**. Budget conservatively — set `timeout_ms` to about half your true tolerance, and do not assume the call returns within exactly `timeout_ms`.
  - **`reconnect()` does NOT perform the `CHx` alias resolution that `__init__` does.** Passing `reconnect(device_sn='CH2')` stores `'CH2'` verbatim and will fail to match the device. When reconnecting with an explicit target, pass the **raw numeric SN** (e.g. `'1066657'`), not a channel alias.
