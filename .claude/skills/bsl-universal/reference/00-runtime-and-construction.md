# Runtime & Construction Contract (shared by every instrument)

This is the part of `bsl_universal` that is identical across all instruments. Read this
before any per-instrument reference — it tells you how to *create*, *safely drive*, and
*tear down* any device.

> Source of truth: `bsl_universal/instruments/inst.py`, `factory.py`, `registry.py`,
> `bsl_universal/core/instrument_runtime.py`. If those files change, this doc is stale —
> see `MAINTENANCE.md` (the sync hook enforces regeneration).

---

## 1. Constructing an instrument

Always construct through the **public factory functions** in `bsl_universal.instruments`.
Never instantiate the `_Driver` classes under `_inst_lib/instruments/` directly — you would
bypass logging, the health monitor, retry-on-construction, and the `.safe` recovery layer.

```python
from bsl_universal.instruments import PM100D, CS260B, RS_7_1, mantisCam

pm   = PM100D()                 # device_sn="" → auto-pick the only connected unit
mono = CS260B()
led  = RS_7_1(power_on_test=True)
cam  = mantisCam()
```

### Factory signatures (canonical keys + exact args)

| Factory                | Signature                                                           | Transport      |
|------------------------|---------------------------------------------------------------------|----------------|
| `PM100D`               | `PM100D(device_sn="")`                                               | VISA/USB       |
| `PM400`                | `PM400(device_sn="")`                                                | VISA/USB       |
| `DC2200`               | `DC2200(device_sn="")`                                               | VISA/USB       |
| `M69920`               | `M69920(device_sn="")`                                               | Serial         |
| `CS260B`               | `CS260B(device_sn="")`                                               | Serial         |
| `SP_2150`              | `SP_2150(device_sn="")`                                              | Serial         |
| `RS_7_1`               | `RS_7_1(device_sn="", power_on_test=True)`                           | Serial         |
| `USB_520`              | `USB_520(device_sn="", tear_on_startup=True, reverse_negative=True)` | FTDI/USB-SDK   |
| `HR4000CG`             | `HR4000CG(device_sn="")`                                             | USB-SDK (seabreeze) |
| `BSC203_HDR50`         | `BSC203_HDR50()`  *(no device_sn arg)*                               | USB-SDK (APT)  |
| `mantisCam`            | `mantisCam(device_sn="")`                                            | ZMQ            |

**`device_sn`**: optional serial/identifier selector. Leave it `""` to auto-select when
exactly one matching unit is on the bus. Pass the serial when multiple identical units are
connected. The factory does NOT raise `KeyError` on a bad serial here — that surfaces from
the driver's discovery step as a `DeviceConnectionFailed`.

You can also build by string key:

```python
from bsl_universal.instruments import create_instrument, available_instruments
available_instruments()              # ('BSC203_HDR50','CS260B','DC2200','HR4000CG','M69920',
                                     #  'PM100D','PM400','RS_7_1','SP_2150','USB_520','mantisCam')
dev = create_instrument("PM100D")    # same object the PM100D() factory returns
```

Aliases accepted by `create_instrument`: `USB520 → USB_520`, `MantisCam → mantisCam`.

### What construction does for you (`_build_instrument`)
1. Initializes the shared Loguru logger (`init_logger(LOG_LEVEL="DEBUG")` if not already done).
2. Starts the optional device-monitor GUI window once per process (failures are non-fatal).
3. Publishes a `CONNECTING` status to the health hub.
4. Calls the driver constructor through `InstrumentFactory.create`, which **retries 2×**
   (0.5 s apart) and converts any `SystemExit` from a driver into a `RuntimeError`
   (so a driver calling `sys.exit()` cannot kill your process — but see the audit; drivers
   should raise typed exceptions, not exit).
5. On success, publishes `CONNECTED` and attaches the runtime recovery hooks below.
6. On failure, publishes an unrecoverable `FAILURE` status and re-raises.

---

## 2. The recovery layer: `.safe`, `.invoke`, `.reconnect_safe`, `.reset_safe`

After construction, additive helpers are attached to the returned driver object. They never
replace the normal driver methods (except `.close`, which is wrapped to publish monitor state).

| Helper                       | What it does |
|------------------------------|--------------|
| `dev.safe.<method>(*args)`   | Runs `<method>` through bounded retry + reset/reconnect recovery. **Method calls only.** |
| `dev.invoke("<method>", …)`  | Same recovery flow, method addressed by name. (Attached as `invoke_safe` if the driver already defines its own `invoke`.) |
| `dev.reconnect_safe()`       | Guarded reconnect; refreshes monitor state. Returns `bool`. |
| `dev.reset_safe()`           | Guarded reset (tries `reset_controller/reset_meter/reset_system/…`). Returns `bool`. |
| `dev.close()`                | Monitored: releases hardware **and** marks the device disconnected in the monitor. Idempotent. |

```python
# Plain call — raises immediately on a transport hiccup:
pm.set_preset_wavelength(532)

# Recovery-managed call — retries up to 2×, attempting reset then reconnect between tries:
pm.safe.set_preset_wavelength(532)
pm.invoke("set_preset_wavelength", 532)     # equivalent
```

**`RecoveryPolicy` defaults** (`bsl_universal.core.RecoveryPolicy`):
`operation_retries=2`, `reset_on_error=True`, `reconnect_on_error=True`,
`recovery_delay_sec=0.2`. Recovery order is **reset first, then reconnect**.

### `.safe` gotchas — read these
- **`.safe` is for METHODS, not properties.** `dev.safe.<name>` always returns a *callable*
  (it proxies through `invoke`). `dev.safe.some_property` gives you a function, not the value.
  Read properties directly: `dev.some_property`.
- **Name collision:** if a driver already defines an attribute named `safe`, the proxy is
  attached as **`dev.bsl_safe`** instead. Check `hasattr(dev, "bsl_safe")` if `dev.safe`
  looks wrong.
- `dev.invoke(...)` raises `AttributeError` if the method name doesn't exist on the driver.
- Recovery only helps with *transient transport* faults. A logic error (bad argument, out of
  range) will retry and still fail — fix the call, don't lean on `.safe`.

---

## 3. `ManagedInstrument` — opt-in context-manager wrapper

The factory functions return the **raw driver** (with helpers bolted on). They do **not**
return a `ManagedInstrument`. If you want `with`-block lifetime management, wrap explicitly:

```python
from bsl_universal.instruments import ManagedInstrument, PM100D

dev = PM100D()
mi = ManagedInstrument(
    instrument_name="PM100D", device=dev,
    model="PM100D", device_type="PowerMeter", serial_number=dev.device_id,
)
with mi:                       # __exit__ calls mi.close()
    mi.safe.set_preset_wavelength(532)
    p = mi.get_measured_power()         # unknown attrs proxy to the wrapped device
mi.raw                         # the underlying driver object
```

`ManagedInstrument` exposes `.safe`, `.invoke(name,*a)`, `.reconnect()`, `.reset()`,
`.close()`, `.raw`, and proxies every other attribute to the wrapped device via `__getattr__`.

> Most lab scripts do **not** need `ManagedInstrument`. The plain factory object already has
> `.safe`/`.invoke`/monitored-`.close`. Use `ManagedInstrument` only when you specifically
> want `with`-statement scoping.

---

## 4. Teardown

```python
dev.close()        # idempotent; safe to call twice; also publishes 'disconnected' to monitor
```

If you forget, the object auto-releases on garbage collection (a class-level `__del__` hook,
with a `weakref.finalize` fallback) and still marks the monitor disconnected. **Prefer an
explicit `close()`** in a `try/finally` — GC timing is not guaranteed, and a still-open
serial/VISA handle blocks the next process from connecting.

```python
dev = CS260B()
try:
    dev.set_wavelength(550)
    ...
finally:
    dev.close()
```

---

## 5. Exceptions to catch

Typed exceptions live in `bsl_universal.core.exceptions` (aliases of the legacy
`_bsl_type` hierarchy). Catch these rather than bare `Exception`:

```python
from bsl_universal.core.exceptions import (
    CustomError,                 # base of all bsl device errors
    DeviceConnectionFailed,      # discovery/handshake/transport-open failure
    DeviceOperationError,        # a command failed or returned an inconsistent result
    DeviceTimeOutError,          # transport read/handshake timeout
    DeviceInconsistentError,     # readback did not match the commanded value
)
```

Construction failures raise `DeviceConnectionFailed` (or `RuntimeError` if a driver tried to
`SystemExit`). State-changing commands that fail their readback verification raise
`DeviceInconsistentError`.

---

## 6. Logging

`init_logger(LOG_LEVEL="DEBUG")` configures the shared Loguru sink; the first factory call
does this automatically. To quiet things down, call it **before** constructing any instrument:

```python
from bsl_universal.instruments import init_logger
init_logger("WARNING")
```
