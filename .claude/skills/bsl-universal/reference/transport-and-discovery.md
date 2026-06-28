# Transport & Discovery — the Serial/VISA I/O layer + instrument metadata registry that every bsl_universal driver is built on

> **Factory:** `from bsl_universal.instruments._inst_lib.interfaces._bsl_serial import _bsl_serial` / `from bsl_universal.instruments._inst_lib.interfaces._bsl_visa import _bsl_visa`, then `_bsl_serial(target_inst, device_sn="")` or `_bsl_visa(target_inst, device_sn="")`. Metadata records come from `from bsl_universal.instruments._inst_lib.headers._bsl_inst_info import _bsl_inst_info_list`.
> **Transport:** Serial (pyserial) + VISA (PyVISA/SCPI) · **Datasheet:** none on disk (this is the software transport layer, not an instrument) · **Source:** `bsl_universal/instruments/_inst_lib/interfaces/_bsl_serial.py`, `bsl_universal/instruments/_inst_lib/interfaces/_bsl_visa.py`, `bsl_universal/instruments/_inst_lib/headers/_bsl_inst_info.py`

## When to use this

This is **infrastructure, not an instrument.** `_bsl_serial` and `_bsl_visa` are the two retry/reconnect-wrapped transport helpers that every per-instrument driver in this package uses under the hood; `_bsl_inst_info_list` is the static metadata registry (USB PID/VID, baud, identity-probe commands, serial-number regex) those helpers consume to *find and validate* a physical device on the bus. An agent normally drives hardware through a high-level instrument factory (see [runtime](00-runtime-and-construction.md)) and never touches these classes directly. Reach for this doc when you need to understand **why a device was/wasn't discovered**, what a driver's `.write()`/`.query()` actually does on the wire, how auto-detection picks a port, or when writing/debugging a new driver that wraps one of these transports. Both classes are underscore-private (`_bsl_*`) — they are not part of the public `bsl_universal` surface.

## Construct & tear down

Discovery and connection happen **inside `__init__`** — constructing the object scans the bus, opens the port, and validates identity. Success is signalled by an attribute, **not** by an exception (with one exception; see Safety). Always check `serial_port is not None` / `com_port is not None` before using the handle, and always `close()` in a `finally`.

```python
from bsl_universal.instruments._inst_lib.interfaces._bsl_serial import _bsl_serial
from bsl_universal.instruments._inst_lib.interfaces._bsl_visa import _bsl_visa
from bsl_universal.instruments._inst_lib.headers._bsl_inst_info import _bsl_inst_info_list as inst

# --- VISA: Thorlabs PM100D power meter (SCPI over USB) ---
pm = _bsl_visa(inst.PM100D, device_sn="")   # "" = accept the first PM100D found
try:
    if pm.com_port is None:                 # the documented success signal
        raise RuntimeError("PM100D not found on VISA bus")
    pm.set_timeout_ms(5000)                 # MILLISECONDS for VISA
    print(pm.device_id)                     # matched serial, e.g. "P1234567"
    print(pm.query("MEAS:POW?"))            # SCPI round-trip
finally:
    pm.close()

# --- Serial: Newport M69920 arc-lamp power supply (line protocol) ---
com = _bsl_serial(inst.M69920, device_sn="")
try:
    if com.serial_port is None:
        raise RuntimeError("M69920 not found on any serial port")
    com.set_serial_timeout(2)               # SECONDS for serial
    print(com.query("IDN?"))                # writes "IDN?\r\n", reads one line
finally:
    com.close()
```

**What `device_sn` selects:** it is a *substring* serial-number filter. `""` (default) disables S/N filtering and accepts the first device that passes the identity probe (`QUERY_E_RESP` match). A non-empty value is matched against the serial number parsed from the device — for **serial** via `QUERY_SN_CMD` + `SN_REG`, for **VISA** by applying `SN_REG` to the `QUERY_CMD` (`*IDN?`) response (VISA never sends `QUERY_SN_CMD`); only a device whose parsed S/N *contains* that substring is accepted, otherwise discovery moves to the next candidate. Use it to disambiguate two identical units on the same bus.

## Most-used operations

These are the agent-facing primitives a driver calls. Construction (the discovery engine) is itself the first and heaviest "operation."

### `_bsl_serial(target_inst, device_sn="")` / `_bsl_visa(target_inst, device_sn="")`

- **Does:** Enumerates the bus, finds a port/resource matching `target_inst`, opens it, validates identity, and stores the live handle. Serial matches by `SERIAL_SN`-in-portpath, `device_sn`-in-portpath, `SERIAL_NAME`-in-description, or `USB_PID`-in-hwid (hex **or** decimal form), then probes with `QUERY_CMD` and checks `QUERY_E_RESP`; VISA matches by **both** PID **and** VID embedded in the VISA resource string, then probes `*IDN?`.
- **Args:** `target_inst` (a `_bsl_inst_info_list` record, e.g. `inst.PM100D`; required) · `device_sn` (str, S/N filter substring, default `""`).
- **Returns:** the transport instance. Inspect `.serial_port` / `.com_port` (handle or `None`) and `.device_id` (str).
- **Blocks?** **Yes, heavily.** Up to `MAX_CONNECT_RETRY=3` discovery passes with `RETRY_DELAY_SEC` (0.2 s serial / 0.25 s VISA) between them. Serial probing sleeps **0.5 s after each query write** per candidate port, and if `BAUDRATE==0` it scans up to **6 baud rates** per port — worst case roughly `#ports × 6 × ~1 s`.
- **Readback?** Yes — identity is validated during discovery (`QUERY_E_RESP` substring; S/N via `SN_REG`). There is no liveness re-check after construction.
- **Raises:** Generally **does not raise on not-found** — logs an error, leaves the handle `None`. **Sole exception:** serial discovery raises `bsl_type.DeviceConnectionFailed` (as a bare class) when `device_sn` is set **and** `MODEL == "USB_520"` and the device is missing.
- **Example:** `pm = _bsl_visa(inst.PM100D); assert pm.com_port is not None`

### `query(cmd)` — both transports

- **Does (VISA):** `resource.query(cmd)`, returns stripped response. **Does (serial):** flushes the input buffer, writes `cmd + "\r\n"`, reads **one** line back.
- **Args:** `cmd` (str). VISA: raw SCPI query (e.g. `"MEAS:POW?"`). Serial: command **without** CRLF — `\r\n` is appended automatically.
- **Returns:** `str`, whitespace/CRLF stripped (UTF-8 decoded on serial).
- **Blocks?** Yes — one write+read round-trip, bounded by the transport timeout; wrapped in up to `MAX_IO_RETRY=3` retry/reconnect attempts.
- **Readback?** Returns the response but does **not** validate its content.
- **Raises:** `bsl_type.DeviceOperationError` after retries are exhausted.
- **Example:** `pm.query("*IDN?")`

### `write(cmd)` — both transports

- **Does:** Sends a command. VISA: `resource.write(cmd)`. Serial: encodes `cmd` UTF-8 and writes **raw, no terminator** (use `writeline` for CRLF).
- **Args:** `cmd` (str).
- **Returns:** serial `int` (bytes written); VISA `None`.
- **Blocks?** Yes until the write completes; retry/reconnect-wrapped.
- **Readback?** **No** — no verification the device accepted or applied the command.
- **Raises:** `bsl_type.DeviceOperationError` after retries exhausted. **Caution:** a failed write is retried up to 3× — see Safety re: non-idempotent commands.
- **Example:** `pm.write("SENS:POW:UNIT W")`

### `writeline(msg)` — serial only

- **Does:** Appends `"\r\n"` to `msg`, encodes UTF-8, writes it.
- **Args:** `msg` (str, no CRLF). **Returns:** `int` bytes written. **Blocks?** Yes; retry-wrapped. **Readback?** No.
- **Raises:** `bsl_type.DeviceOperationError`. **Example:** `com.writeline("GO")`

### `readline()` / `read(n_bytes)` / `read_all()` — serial only

- **Does:** `readline()` reads one line; `read(n_bytes)` reads a fixed byte count; `read_all()` returns all currently-buffered bytes.
- **Args:** `read` takes `n_bytes` (int, byte count, no range validation). Others: none.
- **Returns (mind the inconsistency):** `readline()` → `str`, `read()` → **`str`** (UTF-8 decoded, CRLF stripped — despite the name), `read_all()` → **`bytes`** (raw, only ASCII-whitespace stripped).
- **Blocks?** `readline`/`read` block up to the serial timeout (default **0.1 s** unless changed); `read_all` returns what is buffered. All retry-wrapped.
- **Readback?** n/a (read ops). **Raises:** `bsl_type.DeviceOperationError`.
- **Example:** `line = com.readline()`

### `set_timeout_ms(timeout)` (VISA) / `set_serial_timeout(timeout)` (serial)

- **Does:** Sets the read/query timeout on the open handle.
- **Args / UNIT — easy to confuse:** VISA `set_timeout_ms(timeout: int)` is **milliseconds**; serial `set_serial_timeout(timeout: int)` is **seconds** (pyserial accepts fractional values despite the int annotation).
- **Returns:** `None`. **Blocks?** No real I/O; retry-wrapped. **Readback?** No.
- **Example:** `pm.set_timeout_ms(5000)` (5 s) vs `com.set_serial_timeout(2)` (2 s).

### `flush_read_buffer()` — serial only

- **Does:** `reset_input_buffer()` — discards buffered incoming data. **Args:** none. **Returns:** `None`. **Blocks?** No. **Example:** `com.flush_read_buffer()`

### `close()` — both transports

- **Does:** Closes the handle (errors swallowed) and sets it to `None`. Idempotent; also called from `__del__`.
- **Args:** none. **Returns:** `None`. **Blocks?** No. **Readback?** n/a.
- **Note (VISA):** closes the opened resource only — it does **not** close the PyVISA `ResourceManager` (leaked across reconnect cycles).
- **Example:** `pm.close()`

## Full method index

### `_bsl_serial`

| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `__init__` | method | discover + connect a matching serial device | `target_inst`, `device_sn: str=""` | instance (`.serial_port` = handle/None) |
| `readline` | method | read one line | — | `str` (CRLF stripped) |
| `read` | method | read fixed byte count | `n_bytes: int` (bytes) | `str` (decoded, CRLF stripped) |
| `read_all` | method | read all buffered bytes | — | **`bytes`** (raw) |
| `write` | method | write raw bytes, no terminator | `msg: str` | `int` (bytes written) |
| `writeline` | method | write line with `\r\n` appended | `msg: str` | `int` (bytes written) |
| `query` | method | flush, write `cmd+\r\n`, read one line | `cmd: str` | `str` (response line) |
| `flush_read_buffer` | method | clear input buffer | — | `None` |
| `set_serial_timeout` | method | set read timeout | `timeout: int` (**seconds**) | `None` |
| `is_port_free` | method | macOS-only `lsof` busy check (private/internal helper, surfaced) | `port_name: str` (e.g. `/dev/tty.usbserial`) | `bool` (True = free) |
| `close` | method | close port, null handle, idempotent | — | `None` |
| `serial_port` | attribute | live `serial.Serial` or `None` (success signal) | — | handle/None |
| `device_id` | attribute | matched S/N or `''`/`'UNKNOWN'` | — | `str` |
| `baudrate` | attribute | active baud (from descriptor or scan) | — | `int` |
| `MAX_CONNECT_RETRY` / `MAX_IO_RETRY` / `RETRY_DELAY_SEC` | class const | retry tuning (3, 3, 0.2) | — | `int`/`float` |

### `_bsl_visa`

| name | kind | purpose | key args (units) | returns |
|------|------|---------|------------------|---------|
| `__init__` | method | discover + connect a matching VISA/SCPI device | `target_inst`, `device_sn: str=""` | instance (`.com_port` = handle/None) |
| `query` | method | SCPI `resource.query(cmd)` | `cmd: str` (SCPI) | `str` (stripped) |
| `write` | method | SCPI `resource.write(cmd)` | `cmd: str` (SCPI) | `None` |
| `set_timeout_ms` | method | set VISA timeout | `timeout: int` (**milliseconds**) | `None` |
| `close` | method | close resource (NOT the RM), idempotent | — | `None` |
| `com_port` | attribute | live pyvisa resource or `None` (success signal) | — | handle/None |
| `device_id` | attribute | matched S/N, or `''` (not found), or the full `*IDN?` identity string on a VISA `SN_REG` miss | — | `str` |
| `visa_resource_manager` | attribute | the pyvisa `ResourceManager` (or `None`) | — | RM/None |
| `MAX_CONNECT_RETRY` / `MAX_IO_RETRY` / `RETRY_DELAY_SEC` | class const | retry tuning (3, 3, 0.25) | — | `int`/`float` |

### `_bsl_inst_info_list` (metadata registry — read these, do not mutate)

Each attribute is a pre-built `_bsl_inst_info_class` record. Pass one as `target_inst`. Fields per record: `MANUFACTURE, MODEL, TYPE, INTERFACE, BAUDRATE, SERIAL_NAME, SERIAL_SN, USB_PID, USB_VID, QUERY_CMD, QUERY_E_RESP, QUERY_SN_CMD, SN_REG`. `USB_PID`/`USB_VID` are **hex strings** like `"0x8078"` (caller must `int(x,16)`); `BAUDRATE==0` means "unspecified / scan."

| record | mfr / type | interface | PID / VID · baud | identity probe (`QUERY_CMD` → `QUERY_E_RESP`) |
|--------|-----------|-----------|------------------|-----------------------------------------------|
| `PM100D` | Thorlabs Power Meter | VISA | 0x8078 / 0x1313 | `*IDN?` → `PM100D` |
| `PM400` | Thorlabs Power Meter | VISA | 0x8075 / 0x1313 | `*IDN?` → `PM400` |
| `DC2200` | Thorlabs LED Controller | VISA | 0x80C8 / 0x1313 | `*IDN?` → `DC2200` |
| `CS260B` | Newport Monochromator | VISA | 0x0014 / 0x1FDE | `*IDN?` → `CS260B` |
| `BSC203_HDR50` | Thorlabs Rotational Stage | FTDI | 0x6001 / 0x0403 | `*IDN?` → `HDR50` |
| `M69920` | Newport Power Supply (arc lamp) | Serial | — · 9600 | `IDN?\r` → `69920` |
| `USB_520` | Futek USB ADC (load cell) | Serial | — · 9600 | (no `QUERY_CMD`) → resp contains `g` |
| `RS_7_1` | Gamma Scientific Tunable LED | Serial | 0x6001 / 0x0403 · 460800 | `USN\r\n` → `HX0650` |
| `SP_2150` | Princeton Monochromator | Serial | 0x6001 / 0x0403 · 9600 | `model\r` → `SP-2-150i` |
| `HR4000CG` | Ocean Optics Spectrometer | USB-SDK | `???` / `???` | (none; SDK-discovered) |
| `mantisCam` | BioSensors Lab Camera | ZMQ | — | (none) |
| `TEST_DEVICE_NO_BAUD` | BSL test fixture | Serial | 0x8078 / 0x1313 · scan | `*IDN?` → `PM100D` |
| `TEST_DEVICE_BAUD` | BSL test fixture | Serial | 0x8078 / 0x1313 · 115200 | `*IDN?` → `PM100D` |

## Units, ranges & limits

- **Retry / timing:** `MAX_CONNECT_RETRY = 3`, `MAX_IO_RETRY = 3` (both transports). `RETRY_DELAY_SEC = 0.2` (serial) / `0.25` (VISA).
- **Serial open timeout:** hardcoded **0.1 s** at every `serial.Serial(...)` open and reconnect. Change the live read timeout with `set_serial_timeout(seconds)`.
- **Baud scan list (when `BAUDRATE==0`):** `[4800, 9600, 19200, 28800, 38400, 115200]` bits/s, probed in that order. A non-zero `BAUDRATE` pins to that single value.
- **Per-probe delay:** serial discovery sleeps **0.5 s** after writing `QUERY_CMD` and again after `QUERY_SN_CMD`, then reads up to **100 bytes**.
- **`device_sn`:** arbitrary substring; `""` = no S/N filtering (accept first identity match).
- **Timeout units differ:** VISA `set_timeout_ms` = **milliseconds**; serial `set_serial_timeout` = **seconds**.
- **USB PID/VID:** hex strings in the registry (`"0x8078"` etc.); serial discovery also tries the **decimal** form of the PID as a substring; VISA requires **both** PID and VID to appear in the resource string.
- **Registry baud values in use:** `{0, 9600, 115200, 460800}`. **Interfaces in use:** `VISA, Serial, FTDI, USB-SDK, ZMQ` (free-text string, not an enum).
- **`_bsl_inst_info_class` defaults (keyword-only constructor):** `INTERFACE="Serial"`, `BAUDRATE=0`, `SERIAL_NAME="N/A"`, `SERIAL_SN="N/A"`, `USB_PID="0x9999"`, `USB_VID="0x9999"`, `QUERY_CMD="N/A"`, `QUERY_E_RESP="N/A"`, `SN_REG=".*"`, `QUERY_SN_CMD=""`.
- **Exception hierarchy (`_bsl_type`):** `CustomError` (base) → `DeviceConnectionFailed`, `DeviceOperationError`, `DeviceTimeOutError`, `DeviceInconsistentError`. Catch `_bsl_type.CustomError` for any library error; `DeviceInconsistentError` is the canonical readback-mismatch exception.

## Safety & gotchas

- **Recovery layer:** every I/O method is internally wrapped by `_run_with_reconnect`, which reconnects and retries up to `MAX_IO_RETRY=3` times before raising `DeviceOperationError`. At the driver level this is exposed as `dev.safe.<method>()` for an explicit retry wrapper — note `.safe` is **method-only**; see [runtime](00-runtime-and-construction.md).
- **Construction does not raise on not-found** (except serial `USB_520` with a `device_sn` set, which raises a bare `DeviceConnectionFailed`). For everything else you **must** check `serial_port`/`com_port` is not `None`; a silently-`None` handle will surface as a confusing `DeviceOperationError` on first I/O.
- **No write readback.** Neither `write`/`writeline` (serial) nor `write` (VISA) verifies the device applied the command. If you need confirmation, follow with a `query` and compare yourself (raise `DeviceInconsistentError` on mismatch).
- **Retries can double-apply non-idempotent writes.** A transient error *after* the hardware already actioned a command causes the same command to be re-sent on retry. For relative moves, triggers, increments, or output toggles this can apply the change twice with no detection. Prefer absolute/idempotent commands, or do not rely on auto-retry for state changes.
- **Serial discovery probes other ports.** `USB_PID` matching ignores `USB_VID` (unlike VISA, which requires both), so a same-PID device from another vendor can be selected and sent `QUERY_CMD`. The **brute-force fallback** (when nothing matches) writes `QUERY_CMD` to **every** serial port on the machine and waits 0.5 s/baud — this can disturb unrelated instruments and lock a busy port for seconds. Be aware when other lab gear shares the bus.
- **Busy-port detection is macOS-only.** `is_port_free` runs `lsof` only on Darwin and **fails open** (returns `True`) on Windows/Linux and on any `lsof` error — so on non-macOS the only busy-port guard is the subsequent `open()` failure.
- **Mixed serial return types:** `read()`/`readline()`/`query()` return `str`; `read_all()` returns `bytes`. Don't assume a uniform type.
- **Strict UTF-8 decode on serial reads.** A single non-UTF-8 byte raises `UnicodeDecodeError`, which is treated as a transport error and triggers reconnect + re-read — this can drop or duplicate data, or (for `query`) re-issue the write.
- **`device_id` may not be a clean serial number:** `''` (not found), `'UNKNOWN'` (serial `SN_REG` miss), or — on a VISA `SN_REG` miss — the **full `*IDN?` identity string** (the `'UNABLE_TO_OBTAIN'` literal appears only in the discovery log, and is never stored on the instance). Do not key persistent logic on it blindly.
- **VISA `close()` leaks the `ResourceManager`** (only the opened resource is closed). Long-lived processes that repeatedly reconnect accumulate VISA sessions.
- **Destructive-hardware note:** several registry records drive high-power or motion hardware — `M69920` (arc-lamp power supply), `DC2200` (high-power LED controller), `RS_7_1` (tunable LED source), `BSC203_HDR50` (rotational stage homing/motion). Because `write` has no readback and is retried, treat any command that raises output power or commands motion as potentially double-applied; verify with a follow-up `query` and bound power/position in driver logic.
- **Registry records are shared mutable singletons.** `_bsl_inst_info_class` has no immutability and no `__eq__`/`__repr__`; never mutate a `_bsl_inst_info_list.<MODEL>` field — you would corrupt it process-wide.

## Audit notes (2026-06-28)

- **Fixed:**
  - The `TEST_DEVICE_NO_BAUD` and `TEST_DEVICE_BAUD` registry records now carry the correct `MODEL` strings — each record's `MODEL`, its attribute name, and its baud configuration agree (`TEST_DEVICE_NO_BAUD` has no `BAUDRATE` → scans; `TEST_DEVICE_BAUD` is `BAUDRATE=115200`). Logs and any `MODEL`-keyed logic now identify these test fixtures correctly.
  - `RS_7_1` USB identifiers are now correct: `USB_PID="0x6001"` / `USB_VID="0x0403"` (the real FTDI VID 0x0403 / FT232R PID 0x6001, matching the sibling `BSC203_HDR50`). USB enumeration filtering by (VID, PID) will now match the Gamma Scientific tunable LED source.

- **Known / deferred:**
  - **Unguarded `SERIAL_SN`/`SERIAL_NAME` matching can false-match a port.** In `_bsl_serial._find_device`, the checks `self.inst.SERIAL_SN in port[0]` and `self.inst.SERIAL_NAME in port[1]` run unconditionally, and both fields **default to the literal `"N/A"`**. For any record that does not set them, discovery effectively tests whether the substring `"N/A"` appears in the port path / free-form port description — `port[1]` (the human-readable descriptor) can legitimately contain `"N/A"`, causing a wrong port to be selected and probed. **Do not assume discovery only matches by PID/VID or your explicit `device_sn`.** When wiring a new device or debugging a mis-match, set a real `SERIAL_NAME`/`SERIAL_SN` (or a `device_sn` filter) and verify `device_id`/the chosen port after construction rather than trusting the first match.
