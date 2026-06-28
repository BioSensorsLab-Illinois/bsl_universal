# M69920 — Newport 69920 arc-lamp power supply (1000 W Xe UV-enhanced arc lamp, lamp housing model 6296)

> **Factory:** `from bsl_universal.instruments import M69920` then `M69920(device_sn="", *, mode=M69920.SUPPLY_MODE.POWER_MODE, lim_current=50, lim_power=1200, default_power=1000, force_reset=False)`
> **Transport:** Serial · **Datasheet:** `M69920.pdf` (in `_datasheet/`) · **Source:** `bsl_universal/instruments/_inst_lib/instruments/_M69920.py`

## When to use this
This driver controls a Newport 69920 arc-lamp power supply that has been preconfigured for a 1000 W Xe UV-enhanced arc lamp (lamp housing model 6296). Use it when an experiment needs a broadband UV/visible high-intensity light source and you must ignite, monitor, or extinguish the arc lamp. The instrument self-documents that **only read-only queries and lamp ON/OFF should be used in normal operation** — all setpoint/limit mutators are marked by the author as reserved for internal/experimental use (the constructor logs three warnings to this effect). Pick it for live readback of amps/volts/watts/lamp-hours and for safe ignition/shutdown of the arc lamp; do not pick it to reprogram power/current envelopes unless you explicitly intend experimental reconfiguration.

## Construct & tear down
Constructing connects, sends `RST`, sleeps 5 s, and — only if measured power < 100 W (or `force_reset=True`) — programs mode, current limit, power limit, and the default power setpoint. It does **not** ignite the lamp. `device_sn=""` auto-selects the first M69920 found on any serial port; pass a serial-number selector string to disambiguate multiple units.

```python
from bsl_universal.instruments import M69920

# Construct + auto-connect. Blocks >5 s (RST settle) plus up to 3 connect retries x 0.5 s.
lamp = M69920(device_sn="",
              mode=M69920.SUPPLY_MODE.POWER_MODE,
              lim_current=50,      # A
              lim_power=1200,      # W
              default_power=1000)  # W
try:
    lamp.lamp_ON()                          # ignite the 1000 W UV arc lamp (~6 s/attempt, up to ~18 s)
    print("Watts:", lamp.get_current_power())
    print("Volts:", lamp.get_current_voltage())
    print("Amps :", lamp.get_current_current())
    print("Hours:", lamp.get_lamp_hours())
    print("On?  :", lamp.is_lamp_ON())
finally:
    lamp.close()                            # lamp_OFF + unlock front panel + close serial port
```

`close()` (and Python GC via `__del__`) call `lamp_shut_down()`, which turns the lamp **OFF** and unlocks the front panel — closing the object extinguishes the lamp. See [runtime & construction](00-runtime-and-construction.md) for the shared connection/retry conventions.

## Most-used operations
Listed in the order a normal workflow uses them. For normal operation prefer these; treat every `set_*` method as experimental (author-reserved).

### `lamp_ON(retry: int = 3) -> int`
- **Does:** Ignites the lamp. Loops up to `retry` times: sends `START`, waits 6 s, re-checks `is_lamp_ON()`. On loop iterations after the second it also re-runs internal init (`__init_lamp()`).
- **Args:** `retry` (int, count of ignition attempts, default `3`, intended ≥ 1).
- **Returns:** `int` `0` on success.
- **Blocks?** Yes — ~6 s per attempt (up to ~18 s with default retry). Each status check also issues `STB?`+`ESR?` (adds ~1 s sleep each).
- **Readback?** Yes — verifies `is_lamp_ON()` after the attempts.
- **Raises:** `bsl_type.DeviceOperationError` if the lamp never reports ON (timed out); may also raise `DeviceOperationError` mid-call via the embedded ESR error check.
- **Example:** `lamp.lamp_ON()`

### `is_lamp_ON() -> bool`
- **Does:** Reads the status byte (`STB?`) and returns the decoded lamp-on bit (bit 7).
- **Args:** none.
- **Returns:** `bool` — `True` when the lamp is ignited.
- **Blocks?** Yes — issues `STB?` and `ESR?`; the ESR path includes a hard `time.sleep(1)`.
- **Readback?** n/a (it is itself a query).
- **Raises:** `bsl_type.DeviceOperationError` if the ESR check finds an error bit.
- **Example:** `if lamp.is_lamp_ON(): ...`

### `get_current_power() -> int`
- **Does:** Reads live output power via `WATTS?`. Also used internally at construction to decide whether to reinitialize (resets if < 100 W).
- **Args:** none.
- **Returns:** annotated `int` but actually returns a `float` — power in **W**.
- **Blocks?** Yes — one serial query (~0.1 s).
- **Readback?** n/a.
- **Raises:** `ValueError` if the device returns an empty/non-numeric reply (`serial_query` does a bare `float()`); `AttributeError` if called after `close()`.
- **Example:** `watts = lamp.get_current_power()`

### `get_current_voltage() -> float`
- **Does:** Reads live output voltage via `VOLTS?`.
- **Args:** none.
- **Returns:** `float` — volts (**V**).
- **Blocks?** Yes — one serial query.
- **Readback?** n/a.
- **Raises:** `ValueError` on empty/non-numeric reply; `AttributeError` after `close()`.
- **Example:** `volts = lamp.get_current_voltage()`

### `get_current_current() -> float`
- **Does:** Reads live output current via `AMPS?`.
- **Args:** none.
- **Returns:** `float` — amps (**A**).
- **Blocks?** Yes — one serial query.
- **Readback?** n/a.
- **Raises:** `ValueError` on empty/non-numeric reply; `AttributeError` after `close()`.
- **Example:** `amps = lamp.get_current_current()`

### `get_lamp_hours() -> int`
- **Does:** Reads accumulated lamp runtime via `LAMP HRS?` (note the space in the command).
- **Args:** none.
- **Returns:** annotated `int`, actually a `float` — hours (**h**). Lamp life is ~1000 h.
- **Blocks?** Yes — one serial query.
- **Readback?** n/a.
- **Raises:** `ValueError` on empty/non-numeric reply; `AttributeError` after `close()`.
- **Example:** `hrs = lamp.get_lamp_hours()`

### `get_lamp_mode() -> int`
- **Does:** Reads the status byte and returns the decoded regulation mode (STB bit 5).
- **Args:** none.
- **Returns:** **a `SUPPLY_MODE` enum object** (despite the `-> int` annotation and a docstring that says 0/1). Compare against `M69920.SUPPLY_MODE.POWER_MODE` / `.CURRENT_MODE`, **not** against `0`/`1`.
- **Blocks?** Yes — issues `STB?`+`ESR?` (~1 s+).
- **Readback?** n/a.
- **Raises:** `bsl_type.DeviceOperationError` via the embedded ESR check.
- **Example:** `if lamp.get_lamp_mode() == M69920.SUPPLY_MODE.POWER_MODE: ...`

### `lamp_OFF(timeout_sec: int = 45) -> int`
- **Does:** Extinguishes the lamp. Loops sending `STOP` + 5 s wait until `is_lamp_ON()` is false or the timeout elapses.
- **Args:** `timeout_sec` (int, **s**, default `45`).
- **Returns:** `int` `0` on success.
- **Blocks?** Yes — up to `timeout_sec` (polls every ~5 s; each poll issues `STB?`+`ESR?`).
- **Readback?** Yes — verifies `not is_lamp_ON()`.
- **Raises:** `bsl_type.DeviceOperationError` if the lamp does not turn off before timeout.
- **Example:** `lamp.lamp_OFF()`

### `lamp_shut_down() -> int`
- **Does:** Safe shutdown sequence: `lamp_OFF()` then `unlock_front_panel()`.
- **Args:** none.
- **Returns:** `int` `0`.
- **Blocks?** Yes — `lamp_OFF()` can take up to 45 s.
- **Readback?** Inherits `lamp_OFF` / `unlock_front_panel` readbacks.
- **Raises:** Propagates `DeviceOperationError` / `DeviceInconsistentError` from the sub-calls.
- **Example:** `lamp.lamp_shut_down()`

### `close() -> None`
- **Does:** Releases resources: if a serial object exists, calls `lamp_shut_down()` (exceptions swallowed), closes the serial port (swallowed), sets `self.serial = None`, logs `CLOSED`.
- **Args:** none.
- **Returns:** `None`.
- **Blocks?** Yes — runs `lamp_shut_down()` (up to ~45 s).
- **Readback?** n/a.
- **Raises:** Does not raise (sub-call exceptions are swallowed).
- **Example:** `lamp.close()`

## Full method index
| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `M69920(...)` | constructor | Connect, `RST`, 5 s settle, conditionally program mode/limits/setpoint | `device_sn:str=""`, kw-only `mode:SUPPLY_MODE`, `lim_current:int=50` (A), `lim_power:int=1200` (W), `default_power:int=1000` (W), `force_reset:bool=False` | `M69920` instance |
| `SUPPLY_MODE` | nested enum | Regulation-mode enum | — | `POWER_MODE=0`, `CURRENT_MODE=1` |
| `lamp_ON` | method | Ignite lamp (`START` loop) | `retry:int=3` | `int` 0 |
| `lamp_OFF` | method | Extinguish lamp (`STOP` loop) | `timeout_sec:int=45` (s) | `int` 0 |
| `is_lamp_ON` | method | Query lamp-on bit (STB b7) | — | `bool` |
| `is_front_panel_locked` | method | Query panel-lock bit (STB b2) | — | `bool` |
| `get_lamp_mode` | method | Query regulation mode (STB b5) | — | `SUPPLY_MODE` enum (annotated `int`) |
| `lock_front_panel` | method | Lock panel (`COMM=1`), verify | — | `int` 0 |
| `unlock_front_panel` | method | Unlock panel (`COMM=0`), verify | — | `int` 0 |
| `set_lamp_current` | method *(author: experimental)* | Set current setpoint (`A-PRESET=`); needs CURRENT_MODE & current < limit | `current:float=43.5` (A) | `int` 0 |
| `set_lamp_power` | method *(author: experimental)* | Set power setpoint (`P-PRESET=`); needs POWER_MODE & power < limit | `power:int` (W, no default) | `int` 0 |
| `set_lamp_current_limit` | method *(author: experimental)* | Set current limit (`A-LIM=`); needs lim > preset current | `lim_I=50` (A) | `int` 0 |
| `set_lamp_power_limit` | method *(author: experimental)* | Set power limit (`P-LIM=`); needs lim > preset power | `lim_P=1200` (W) | `int` 0 |
| `get_current_current` | method | Live output current (`AMPS?`) | — | `float` (A) |
| `get_current_voltage` | method | Live output voltage (`VOLTS?`) | — | `float` (V) |
| `get_current_power` | method | Live output power (`WATTS?`) | — | `float` (W; annotated `int`) |
| `get_lamp_hours` | method | Accumulated runtime (`LAMP HRS?`) | — | `float` (h; annotated `int`) |
| `get_preset_current` | method | Configured current setpoint (`A-PRESET?`) | — | `float` (A) |
| `get_preset_power` | method | Configured power setpoint (`P-PRESET?`) | — | `float` (W; annotated `int`) |
| `get_current_limit` | method | Configured current limit (`A-LIM?`) | — | `float` (A) |
| `get_power_limit` | method | Configured power limit (`P-LIM?`) | — | `float` (W; annotated `int`) |
| `reconnect` | method | `close()` then reconnect + re-init | kw-only `force_reset:bool=False` | `bool` |
| `reset_supply` | method | Re-run init (`RST` + reprogram) | `force_reset:bool=True` | `bool` (swallows exceptions → `False`) |
| `serial_command` | method *(low-level escape hatch)* | Send raw command, return raw bytes | `msg:str` | `bytes` |
| `serial_query` | method *(low-level escape hatch)* | Send query, parse `float` | `msg:str` | `float` |
| `lamp_shut_down` | method | `lamp_OFF()` + `unlock_front_panel()` | — | `int` 0 |
| `close` | method | Shut down lamp + close serial | — | `None` |

Private/internal (name-mangled or underscore-prefixed; do **not** call directly): `__init_lamp` (re-trigger via `reset_supply`/`reconnect`), `__set_lamp_mode` (mode change is intentionally private), `__STB_query`, `__error_checking`, `_serial_connect`, `_get_lamp_id` (a no-op `pass`), `__del__`.

## Units, ranges & limits
- **Regulation mode enum (inverted values):** `SUPPLY_MODE.POWER_MODE.value == 0`, `SUPPLY_MODE.CURRENT_MODE.value == 1`. Default startup mode is `POWER_MODE`.
- **Constructor defaults:** `lim_current=50` A, `lim_power=1200` W, `default_power=1000` W.
- **Init reset trigger:** at construction, limits/mode/setpoint are programmed only if `get_current_power() < 100` W **or** `force_reset=True`; otherwise the driver trusts existing hardware state and programs nothing.
- **`set_lamp_current`:** requires `CURRENT_MODE`; requires `current < get_current_limit()` (strict — exact-equal is rejected). Default `43.5` A (the value the comments state this Xe lamp requires). Sent as `A-PRESET={current:.1f}` (one decimal).
- **`set_lamp_power`:** requires `POWER_MODE`; requires `power < get_power_limit()` (strict — exact-equal rejected). No default. Sent as `P-PRESET={power:04d}` (4-digit integer).
- **`set_lamp_current_limit`:** requires `lim_I > get_preset_current()` (strict — exact-equal rejected). Default `50` A. Sent as `A-LIM={lim_I:.1f}`.
- **`set_lamp_power_limit`:** requires `lim_P > get_preset_power()` (strict — exact-equal rejected). Default `1200` W. Sent as `P-LIM={lim_P:04d}`.
- **Lamp nameplate (from source comments — NOT enforced anywhere in code):** power range 800–1100 W; typical current 43.5 A DC; typical voltage 23 V DC; lamp life ~1000 h. Only the configured `P-LIM`/`A-LIM` (defaults 1200 W / 50 A) gate setpoints — there is no 800–1100 W / 23 V envelope check.
- **Timing:** `CONNECT_RETRY_COUNT = 3`, `CONNECT_RETRY_DELAY_SEC = 0.5` s. Construction/reset block >5 s (RST settle). `lamp_ON` retry default `3` (6 s/attempt). `lamp_OFF` `timeout_sec` default `45` s (5 s poll). Each status read includes a `time.sleep(1)` in the ESR check.
- **Status byte (`STB?`) bit decode:** b7 = lamp ON, b5 = power mode (else current mode), b3 = error (triggers error check), b2 = front-panel lock, b1 = limit reached (logs error), b0 = interlock (0 = interlock fault).
- **Error status register (`ESR?`) bits 7..1** map to power-on / user-request / command / execution / device-dependent / query / request-control errors; any set bit raises `bsl_type.DeviceOperationError`.

## Safety & gotchas
- **High-power UV arc lamp.** `lamp_ON()` energizes a 1000 W xenon UV-enhanced arc lamp. Confirm the interlock and any shutter/enclosure are safe before igniting. Treat ignition as a destructive/high-energy operation.
- **Closing extinguishes the lamp.** `close()` and Python GC (`__del__`) both call `lamp_shut_down()` → `lamp_OFF()` + `unlock_front_panel()`. Do not let the object go out of scope while you intend the lamp to keep running.
- **`RST` resets the live supply.** The constructor, `reset_supply()`, and `reconnect()` send `RST` and block >5 s. Do not construct/reset while the lamp is critically running unless intended.
- **Use read-only + ON/OFF only.** The constructor explicitly warns (three log lines) that all setpoint/limit mutators are reserved for internal/experimental use. For normal work call the `get_*`, `is_*`, `lamp_ON`, `lamp_OFF`, `lamp_shut_down` methods.
- **No nameplate envelope enforcement.** Nothing prevents setting power/current within the configured limits but outside the 800–1100 W / 23 V nameplate window. The only guard is the configured `P-LIM`/`A-LIM` (defaults 1200 W / 50 A).
- **Init may program nothing.** If `get_current_power() >= 100` W and `force_reset=False`, the constructor programs no mode/limits/setpoint — it trusts existing hardware state. Pass `force_reset=True` if you require a known configuration.
- **`get_lamp_mode()` returns an enum, not an int.** Despite the `-> int` annotation/docstring, compare against `M69920.SUPPLY_MODE.*`, never `0`/`1`.
- **Return-type drift on getters.** `get_current_power`, `get_preset_power`, `get_power_limit`, `get_lamp_hours` are annotated `-> int` but return `float` (`serial_query` always returns `float`).
- **Status reads have side effects and can raise.** Every `is_lamp_ON` / `is_front_panel_locked` / `get_lamp_mode` issues `STB?` **and** `ESR?` and runs `__error_checking`, which can raise `DeviceOperationError` mid-read and includes a hard `time.sleep(1)`.
- **Low-level escape hatches are unguarded.** `serial_command` / `serial_query` bypass all validation and have no `None`-check on `self.serial`; calling them after `close()` raises `AttributeError`. `serial_query` does a bare `float(...)` with no empty/prefix guard, so a malformed reply raises `ValueError`. Prefer the typed methods.
- **Strict boundary checks.** Setpoint/limit guards use strict `>=`/`<=`, so a value exactly equal to the limit/preset is rejected. Readback equality uses exact float `!=`, which can spuriously fail on serial-formatted round-trips.
- **Recovery layer:** wrap any call in the retry recovery layer via `dev.safe.<method>()` (e.g. `lamp.safe.get_current_power()`). `.safe` is **method-only** — it wraps method calls, not attribute/property access. See [runtime & construction](00-runtime-and-construction.md).

## Audit notes (2026-06-28)
- **Fixed:**
  - `set_lamp_power(power)` now **raises `bsl_type.DeviceInconsistentError` when the power setpoint readback does not match the requested value**, instead of silently logging an error and returning `0`. A failed/clamped power set no longer reports success.
  - `set_lamp_power_limit(lim_P)` now **raises `bsl_type.DeviceInconsistentError` when the power-limit readback does not match the requested limit**, instead of silently logging and returning `0`. A safety-relevant over-power limit that fails to apply now surfaces as an error.
- **Known / deferred:** No outstanding issues recorded for this module.
