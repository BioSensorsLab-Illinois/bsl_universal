# bsl_universal — Code Audit (2026-06-28)

Automated multi-agent audit of the first-party `bsl_universal` source (~12k LOC, 18 modules), run as part of building this AI-native skill. Findings were adversarially re-verified before any code was changed.

## Summary

- **Candidate defects surfaced:** 216 (P0=6, P1=53, P2=94, P3=63).
- **Fixes applied & byte-compiled:** 28 (27 from the verify/apply pass + 1 OAuth-portability fix applied by hand).
- **Issues deferred** (real, but risky to auto-fix without hardware / need design): 13.
- **Claims refuted** (not real bugs, incl. stale Agent.md items): 3.
- After all changes: `import bsl_universal` succeeds and every changed file compiles.

> ⚠️ The library is installed editable; these edits are live on import. Changes are in the working tree (not committed) so you can review `git diff` before committing.

## Methodology

1. **Map** — one agent per module read its source in full and produced a structured API map + candidate defects (file:line evidence, proposed fix, confidence).
2. **Verify** — one adversarial auditor per file re-checked each candidate against the source (and cross-referenced callers), classifying CONFIRMED / REFUTED / RISKY. Conservative bias: when unsure, RISKY (no auto-fix).
3. **Apply** — only CONFIRMED-safe patches were applied (one agent per file, no cross-file conflicts), each followed by `python -m py_compile`.
4. **Author + review** — reference docs were written from the *fixed* source and then adversarially reviewed against the code.

## Fixes applied

| Severity | File | Fix |
|---|---|---|
| P0 | core/device_health.py | Hardcoded `/Users/zz4/…` OAuth client-secret path → portable resolver (`$BSL_OAUTH_CLIENT_SECRET` → `~/.bsl_universal/gmail_client_secret.json` → legacy fallback). |
| P0 | _DC2200.py | Misspelled SCPI mnemonic 'CCURENT:CURRENT' may not set LED1 current before output is enabled |
| P0 | _DC2200.py | Misspelled SCPI mnemonic 'CCURENT:CURRENT' for LED2 constant current |
| P0 | _Futek_USB_520.py | Magic sentinel 999 collides with a valid force reading |
| P0 | _HR4000CG.py | get_spectrum triggers two hardware acquisitions and discards the first |
| P1 | _BSC203.py | home() raises TypeError when __curr_step is None (un-homed state) |
| P1 | _CS260B.py | get_errors() raises DeviceOperationError unconditionally after the drain loop |
| P1 | _CS260B.py | set_wavelength return annotation is -> float but it returns an int status code (0/-1) |
| P1 | _DC2200.py | Current quantized to 2-decimal Amps ('.2f') loses fine resolution / drops sub-10mA setpoints |
| P1 | _DC2200.py | Stray trailing '.' appended to PWM frequency SCPI command (LED1) |
| P1 | _DC2200.py | Stray trailing '.' appended to PWM frequency SCPI command (LED2) |
| P1 | _Futek_USB_520.py | ZeroDivisionError when average_count <= 0 in set_tear_calibration |
| P1 | _M69920.py | set_lamp_power readback mismatch is silent — returns success on failed set |
| P1 | _M69920.py | set_lamp_power_limit readback mismatch is silent — returns success on failed limit set |
| P1 | _PM100D.py | get_measured_power_avg divides by zero / returns garbage for avg<=0 |
| P1 | _PM100D.py | get_measured_power_density_avg has the same avg<=0 division/no-validation bug |
| P1 | _PM100D.py | get_power_measuring_range return type annotation int but returns np.float64 |
| P1 | _PM400.py | get_measured_power_avg(avg=0) raises ZeroDivisionError; avg<0 silently returns 0 |
| P1 | _PM400.py | get_measured_power_density_avg(avg=0) ZeroDivisionError; avg<0 returns 0 |
| P1 | _PM400.py | get_measured_power_density logs wrong label/unit (mW) for a W/cm^2 value |
| P1 | _PM400.py | get_power_measuring_range annotated `-> int` but returns np.float64 |
| P1 | _RS_7_1.py | get_distinct_led_channel_id uses channel numbers as table indices (off-by-one + wrong indexing) |
| P1 | _SP_2150.py | Backwards/fragile substring check 'if resp in msg' consumes a line whenever resp is empty |
| P1 | mantis_file_GS.py | imager_type validation absent: any non-'FSI' string silently selects BSI calibration |
| P2 | _bsl_inst_info.py | RS_7_1 USB_PID and USB_VID are swapped |
| P3 | _RS_7_1.py | set_power_led_random returns None but is documented/typed to return list[float] |
| P3 | _bsl_inst_info.py | TEST_DEVICE_NO_BAUD and TEST_DEVICE_BAUD have swapped MODEL strings |
| P3 | mantis_folder.py | Inconsistent default for sort_with_exp between public constructor (False) and private helper (True) |

## Deferred (real issues NOT auto-fixed — handle deliberately)

These were confirmed real but left unchanged because a blind fix could break load-bearing behavior, change a public contract, need hardware-in-loop validation, or requires a design decision. Each is documented as a warning in the relevant instrument's reference **Audit notes**.

| Severity | File | Issue | Why deferred (recommendation) |
|---|---|---|---|
| P0 | _mantisCam.py | State-changing hardware writes (set_hardware_node) have no readback verification | Real concern: set_hardware_node (lines 959-1004) writes safety-relevant registers — TEC `coolingtemp-setpoint`, `adc-gain`/`high-gain`, and raw `spi`/`dac`/`dly |
| P0 | device_health.py | Hardcoded developer-specific absolute path as default OAuth client-secret file | The finding is factually real: line 40-42 defines `_DEFAULT_OAUTH_CLIENT_SECRET_FILE = Path("/Users/zz4/Downloads/client_secret_...apps.googleusercontent.com.js |
| P1 | _BSC203.py | set_angle(precision=False) raises TypeError / mis-moves when __curr_step is None | The crash is real: at line 313 `self.step(doable_step - self.__curr_step)` evaluates the subtraction BEFORE step() is entered, so when __curr_step is None it ra |
| P1 | _DC2200.py | close() does not disable LED outputs before releasing the handle | The safety concern is real: close() (lines 334-346) and __del__ -> close release the VISA resource without issuing OUTPut1/2:STATe OFF, so an energized high-pow |
| P1 | _Futek_USB_520.py | Per-readline timeout set to full loop deadline, doubling worst-case block time | Real issue: serial_port.timeout is set to the full timeout_ms/1000 budget (line 192) and the loop deadline is only re-checked between readline() calls (line 198 |
| P1 | _Futek_USB_520.py | reconnect() does not perform the 'CH' alias resolution that __init__ does | Genuine inconsistency: __init__ (lines 37-43) resolves a 'CHx' alias to its numeric SN before connecting, but reconnect (lines 134-135) assigns device_sn verbat |
| P1 | _PM400.py | set_power_range: unit mismatch (W command vs mW log) and shadows builtin `range` | This method WRITES to hardware: `self._com.write("SENS:POW:RANG:UPP {}".format(range))`. There is a genuine inconsistency -- the SCPI mnemonic SENS:POW:RANG:UPP |
| P1 | _SP_2150.py | set_wavelength has no range validation and no readback verification | The concern is real (set_wavelength formats the argument straight into '{wavelength} GOTO' with no bounds check and never reads back via ?NM), but a safe auto-f |
| P1 | _bsl_serial.py | Unguarded SERIAL_SN/SERIAL_NAME match defaults to 'N/A' and can false-match ports | The defect is real: SERIAL_SN and SERIAL_NAME default to 'N/A' (confirmed in _bsl_inst_info_class.py line 2: SERIAL_NAME:str="N/A", SERIAL_SN:str="N/A"), and _f |
| P1 | device_health.py | Wrong argument forwarded to _build_key for legacy payloads (model passed as instrument_key) | The semantic mismatch is real. `_build_key(self, instrument_key, serial_number)` (line 821) builds `f"{instrument_key}:{serial}"`, and `instrument_key` is the l |
| P1 | factory.py | Constructor retries re-run full driver __init__ — non-idempotent hardware init on motion/light/lamp instruments | The factual core of the claim is verified: factory.create has retries=2 (line 60, 3 total attempts), and its loop re-executes the entire constructor `return cls |
| P1 | instrument_runtime.py | close() sets _closed=True before attempting close, so a failed close cannot be retried and the handle can leak | The observation is factually correct: at lines 385-387, `if self._closed: return` then `self._closed = True` executes BEFORE `device.close()` is called (lines 3 |
| P1 | mantis_file.py | frame_idx accepted by _maybe_sub_dark but never used to index a per-frame [N,H,W,C] dark volume | This is a real defect: __getitem__ passes frame_idx=i but _maybe_sub_dark never consumes it. For a single frame returned by __getitem__ (shape [H,W,C], ndim 3)  |

## Refuted (not real defects)

| File | Claim | Why refuted |
|---|---|---|
| _mantisCam.py | Reported get_frame_mean_gs_hg / get_frame_mean_gs_lg argument-forwarding bug — REFUTED for this file | Confirmed by grep: `get_frame_mean_gs_hg`/`get_frame_mean_gs_lg` exist ONLY in Agent.md:152, nowhere in _mantisCam.py (or any .py in the repo). The sole frame-mean method |
| _bsl_serial.py | read_all() returns bytes while read()/readline() return str (inconsistent contract) | The bytes return is intentional and load-bearing, not a defect. The only in-repo caller, _M69920.py serial_query() line 181, does `float(resp.decode('utf-8'))` -- it expl |
| mantis_file.py | Dark-subtraction result force-cast to uint16, contradicting float docstring and corrupting magnitudes | The premise is false on three counts. (1) There is no 'float docstring': _maybe_sub_dark's docstring promises nothing about dtype; apply_dark_subtraction says only 'Negat |

### Note on `Agent.md` staleness
The repo's `Agent.md` lists P0 'known bugs' that the audit found **no longer exist** in the current code: `MantisCamCtrl.get_frame_mean_gs_hg/_lg` (these methods are not in `_mantisCam.py` at all), and `sys.exit()` inside drivers (none found — `factory.py` already converts a stray `SystemExit` into `RuntimeError`). Treat `Agent.md`'s risk list as historical; this `AUDIT.md` reflects the current code.

<a name='regeneration'></a>
## Regeneration
This audit + skill was produced by a map → verify/apply → author → review pipeline. To re-run after large changes, see [`MAINTENANCE.md`](MAINTENANCE.md). The audit lens (what to hunt for) is the bullet list under step 1 of MAINTENANCE.
