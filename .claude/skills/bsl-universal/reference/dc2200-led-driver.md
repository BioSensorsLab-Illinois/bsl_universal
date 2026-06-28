# DC2200 — Thorlabs DC2200 high-power LED driver/controller (2-channel: LED1, LED2)

> **Factory:** `from bsl_universal.instruments import DC2200` then `DC2200(device_sn: str = "")`
> **Transport:** VISA · **Datasheet:** none on disk · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_DC2200.py`

## When to use this
Pick this driver to drive a Thorlabs DC2200 LED controller — a high-power LED source with two independent channels (LED1, LED2). Use it when an experiment needs a programmable optical source: steady illumination at a set drive current (Constant Current), a set fraction of the LED's max (Constant Brightness), or pulsed/strobed output at a chosen frequency and duty cycle (PWM). Typical uses are sample excitation/illumination, photodiode or sensor calibration, and time-resolved/lock-in measurements where the LED is modulated. It also exposes the unit's on-board touchscreen brightness. This is **not** a measurement instrument — it sources light, it does not read power (use a power meter such as the PM100D/PM400 for that).

## Construct & tear down
```python
from bsl_universal.instruments import DC2200

# device_sn selects which DC2200 the VISA layer binds to (a serial-number string).
# "" lets the VISA layer auto-pick the single connected DC2200; pass an explicit
# serial when more than one unit is present to avoid ambiguity.
led = DC2200(device_sn="")          # raises bsl_type.DeviceConnectionFailed on failure

try:
    # One representative operation: LED1 at 100 mA constant current (this turns LED1 ON).
    led.set_LED1_constant_current(current_mA=100.0)
    # ... do work while LED1 is illuminated ...
finally:
    # close() does NOT disable the outputs — turn channels OFF yourself first.
    led.set_LED1_OFF()
    led.set_LED2_OFF()
    led.close()
```
On construction the driver connects (bounded retry: 3 attempts, 0.5 s apart) and immediately issues `*RST`, resetting the controller to default state. Connection failure raises `bsl_type.DeviceConnectionFailed`. See [runtime & construction](00-runtime-and-construction.md) for the factory/`.safe` conventions shared by all instruments.

## Most-used operations
Workflow order: (optionally set screen brightness) → put a channel in a mode (these helpers turn the channel ON for you) → turn channels OFF → `close()`.

### `set_LED1_constant_current(current_mA: float) -> None`  /  `set_LED2_constant_current(current_mA: float) -> None`
- **Does:** Sequence per channel: turn channel OFF → set mode to Constant Current (`SOURceN:MODe CC`) → write current setpoint (`SOURCEN:CCURRENT:CURRENT <amps>`) → turn channel ON. Energizes the LED.
- **Args:** `current_mA: float`, UNIT mA. **No range validation in code** — bounds are the caller's responsibility (must stay within the DC2200/LED safe operating limits). Internally converted to amps (`current_mA/1000`) and formatted `.4f` (0.1 mA resolution).
- **Returns:** `None`.
- **Blocks?** Yes — several sequential VISA writes; returns once issued (no settle wait).
- **Readback?** No — fire-and-forget writes; hardware echo is not verified.
- **Raises:** `AttributeError` if `_com` is None (e.g. after `close()` or a failed `reconnect()`); otherwise propagates transport errors from the VISA write.
- **Example:** `led.set_LED1_constant_current(current_mA=250.0)`

### `set_LED1_constant_brightness(percent: float) -> None`  /  `set_LED2_constant_brightness(percent: float) -> None`
- **Does:** Per channel: OFF → set mode Constant Brightness (`SOURceN:MODe CB`) → write `SOURCEN:CBRightness:BRIGhtness <percent>` → ON. Drives the LED at `percent` of its configured maximum limit.
- **Args:** `percent: float`, UNIT % of the LED's maximum limit. Docstring intends 0–100; **no bounds check in code**. Sent **unscaled** (verbatim, formatted `.2f`) — unlike screen brightness, do **not** pass a 0.0–1.0 fraction here.
- **Returns:** `None`.
- **Blocks?** Yes (sequential VISA writes).
- **Readback?** No.
- **Raises:** `AttributeError` if `_com` is None; otherwise transport errors propagate.
- **Example:** `led.set_LED2_constant_brightness(percent=25.0)`

### `set_LED1_PWM(current_mA: float, frequency: float, duty_cycle: float, count: int = 0) -> None`  /  `set_LED2_PWM(...) -> None`
- **Does:** Per channel: OFF → set mode PWM (`SOURceN:MODe PWM`) → set pulse current (`SOURCEN:PWM:CURRent <amps>`) → set frequency (`SOURCEN:PWM:FREQ <freq>`) → set duty cycle (`SOURCEN:PWM:DCYCle <dc>`) → set pulse count (`SOURCEN:PWM:COUNt <n>`) → ON.
- **Args:**
  - `current_mA: float`, UNIT mA — pulse current; converted to amps and formatted `.4f`. No range check.
  - `frequency: float`, UNIT Hz — PWM switching frequency. No range check.
  - `duty_cycle: float`, UNIT % — PWM duty cycle. No range check.
  - `count: int`, UNIT count (unitless), default `0` = continuous operation. No range check.
- **Returns:** `None`.
- **Blocks?** Yes (sequence of VISA writes).
- **Readback?** No.
- **Raises:** `AttributeError` if `_com` is None; otherwise transport errors propagate.
- **Example:** `led.set_LED1_PWM(current_mA=100.0, frequency=1000.0, duty_cycle=50.0, count=0)`

### `set_LED1_ON()` / `set_LED1_OFF()` / `set_LED2_ON()` / `set_LED2_OFF()` -> None
- **Does:** Write `OUTPutN:STATe ON|OFF`. The `_ON` variants energize the channel at whatever mode/current was last configured; the `_OFF` variants disable the channel. (NOTE: the docstrings are copy-paste-wrong — e.g. `set_LED1_ON` says "Turn off" — trust the SCPI write, not the docstring.)
- **Args:** none.
- **Returns:** `None`.
- **Blocks?** Yes (single VISA write).
- **Readback?** No.
- **Raises:** `AttributeError` if `_com` is None; otherwise transport errors propagate.
- **Example:** `led.set_LED1_OFF()`

### `set_screen_brightness(brightness: int) -> int`
- **Does:** Sets the on-board touchscreen brightness, then re-queries and returns it. Sends `DISPlay:BRIGhtness <fraction>` where `<fraction> = brightness/100`.
- **Args:** `brightness: int`, UNIT % (percent), valid range **0–100 inclusive** (enforced by a bare `assert`).
- **Returns:** `int` — read-back brightness in % (computed as `int(float(query)*100)`, so it truncates: a 0.999 fraction reads back 99).
- **Blocks?** Yes (write + query round-trip).
- **Readback?** Yes — re-queries `DISPlay:BRIGhtness?`, but does **not** raise on mismatch (it just returns whatever the device reports).
- **Raises:** `AssertionError` if `brightness` is outside 0–100 (and that check is stripped if Python runs with `-O`).
- **Example:** `actual = led.set_screen_brightness(50)`

### `get_screen_brightness() -> int`
- **Does:** Reads the on-board touchscreen brightness (`DISPlay:BRIGhtness?`).
- **Args:** none.
- **Returns:** `int` — brightness in % (0–100), truncated from the device's 0.0–1.0 fraction.
- **Blocks?** Yes (single query round-trip).
- **Readback?** N/A (pure read).
- **Raises:** transport errors propagate; `AttributeError` if `_com` is None.
- **Example:** `b = led.get_screen_brightness()`

### `reset_controller() -> bool`
- **Does:** Issues `*RST`, resetting the controller to default state (turns outputs off, clears mode/parameter state).
- **Args:** none.
- **Returns:** `bool` — `True` on success, `False` if the write raised (does not re-raise).
- **Blocks?** Yes (single VISA write).
- **Readback?** No.
- **Raises:** Does not raise — catches all exceptions and returns `False`.
- **Example:** `ok = led.reset_controller()`

## Full method index
| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `DC2200(device_sn="")` | factory/constructor | Connect (3× retry), `*RST`, return ready driver | `device_sn: str` (VISA serial; `""`=auto) | driver instance |
| `reconnect(device_sn="", reset_controller=False)` | method | Close then reconnect; optionally `*RST` after | `device_sn: str`; `reset_controller: bool` | `bool` (True=success) |
| `reset_controller()` | method | Reset controller via `*RST` | — | `bool` |
| `get_screen_brightness()` | method | Read touchscreen brightness | — | `int` (%) |
| `set_screen_brightness(brightness)` | method | Set touchscreen brightness, return readback | `brightness: int` (%, 0–100) | `int` (%) |
| `set_LED1_ON()` / `set_LED2_ON()` | method | Enable channel output (`OUTPutN:STATe ON`) | — | `None` |
| `set_LED1_OFF()` / `set_LED2_OFF()` | method | Disable channel output (`OUTPutN:STATe OFF`) | — | `None` |
| `set_LED1_constant_current(current_mA)` / `set_LED2_constant_current(...)` | method | CC mode at given current, then ON | `current_mA: float` (mA) | `None` |
| `set_LED1_constant_brightness(percent)` / `set_LED2_constant_brightness(...)` | method | CB mode at % of max limit, then ON | `percent: float` (%, unscaled) | `None` |
| `set_LED1_PWM(current_mA, frequency, duty_cycle, count=0)` / `set_LED2_PWM(...)` | method | PWM mode (current/freq/duty/count), then ON | `current_mA`(mA), `frequency`(Hz), `duty_cycle`(%), `count`(int, 0=continuous) | `None` |
| `close()` | method | Close VISA handle; null `_com` (does NOT disable outputs) | — | `None` |
| `_com_connect(device_sn)` | private helper | Bounded-retry VISA connect (3 attempts, 0.5 s apart) | `device_sn: str` | `bool` |
| `_reset_controller()` | private helper | Raw `*RST` write (no error handling) | — | `None` |
| `__del__` | dunder | Best-effort `close()` on GC (swallows exceptions) | — | `None` |

## Units, ranges & limits
- **Channels:** 2 — LED1 (`SOURce1`/`OUTPut1`) and LED2 (`SOURce2`/`OUTPut2`). Channel is fixed by method name; there is no channel argument.
- **Operating modes:** Constant Current (`CC`), Constant Brightness (`CB`), PWM — one per channel, selected by `SOURceN:MODe`.
- **Screen brightness:** integer **0–100 %** inclusive (the only validated parameter; asserted). Internally sent as a 0.0–1.0 fraction (`brightness/100`).
- **`current_mA`:** float mA. **No min/max enforced in code** — must be kept within DC2200/LED limits by the caller. Sent to hardware as amps with `.4f` formatting → effective resolution ≈ 0.1 mA.
- **`percent` (Constant Brightness):** float % of the LED's max limit, intended 0–100, **not validated**, sent unscaled.
- **`frequency` (PWM):** float Hz, **not validated**.
- **`duty_cycle` (PWM):** float %, **not validated**.
- **`count` (PWM):** int, default `0` = continuous; **not validated**.
- **Connection retry:** `CONNECT_RETRY_COUNT = 3` attempts, `CONNECT_RETRY_DELAY_SEC = 0.5` s between attempts (≈1.5 s worst case before failure).
- **No power/wavelength readout:** this driver exposes no optical-power, wavelength, or temperature query. (A commented-out `get_LED_id` stub exists but is disabled — do not call it.)

## Safety & gotchas
- **High-power LED — outputs energize without readback.** Every `set_LEDx_*` mode helper ends by turning the channel ON, and `set_LEDx_ON()` energizes at whatever current/mode is currently configured. None of these verify a hardware echo. Confirm mode and current are correct before relying on output.
- **`close()` does NOT disable the LEDs.** It only releases the VISA handle and nulls `_com`. A channel left ON stays energized after `close()`/garbage collection, with no software path left to turn it off. **Always call `set_LED1_OFF()` and `set_LED2_OFF()` before `close()`.** (See Known/deferred below.)
- **No range validation** on `current_mA`, `percent`, `frequency`, `duty_cycle`, or `count`. Negative, zero, or over-limit values are forwarded straight to the hardware and the output is then switched ON. Validate against your LED's safe operating range before calling.
- **Constant Brightness `percent` is unscaled** (sent verbatim, 0–100), whereas **screen brightness is scaled** (`/100`). Do not mix the conventions: pass `25.0` to `set_LEDx_constant_brightness`, not `0.25`.
- **No `_com` None-guard.** After `close()` or a failed `reconnect()` (which returns `False` and leaves `_com = None`), any command method raises a bare `AttributeError`, not a typed `bsl_type` error. Check `reconnect()`'s return value before issuing commands.
- **`set_screen_brightness` bound is a bare `assert`** — stripped under `python -O`; an out-of-range value would then reach the device as a >1.0 fraction.
- **Construction resets the controller** (`*RST`), so any pre-existing output is turned off on connect; `reset_controller()`/`*RST` likewise turn all outputs off.
- **Do not trust the docstrings.** Many are copy-paste-wrong (e.g. `set_LED1_ON` reads "Turn off"; several LED2 docstrings say "LED1"). Behavior is defined by the SCPI writes, documented here.
- **Recovery layer:** for transient transport failures, retry via `dev.safe.<method>()` (e.g. `led.safe.set_LED1_OFF()`). `.safe` is **method-only** — it wraps callable methods, not attribute/property access. See [runtime & construction](00-runtime-and-construction.md).

## Audit notes (2026-06-28)
- **Fixed:**
  - Constant-current setpoints for both channels now use the correct SCPI node `CCURRENT:CURRENT` (previously a misspelled mnemonic that the device could reject) — so `set_LEDx_constant_current` now actually applies the requested current before the output is turned ON.
  - Drive-current values are now sent with `.4f` precision (≈0.1 mA resolution) instead of `.2f` — fine and sub-10 mA setpoints are no longer quantized away or silently zeroed, for both CC and PWM current.
  - The PWM frequency command for both channels no longer has a stray trailing `.` appended — `SOURCEN:PWM:FREQ <freq>` is now well-formed SCPI and is parsed correctly by the instrument.
- **Known / deferred:**
  - **`close()` (and `__del__`→`close()`) does not turn the LED outputs off before releasing the handle.** A high-power LED can remain energized after the driver is closed or garbage-collected, with no software handle left to recover it. Do **not** rely on `close()`/object destruction to make the hardware safe — explicitly call `set_LED1_OFF()` and `set_LED2_OFF()` first.
