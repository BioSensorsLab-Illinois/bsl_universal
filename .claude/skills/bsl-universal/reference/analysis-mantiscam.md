# MantisCam Analysis — read-only post-acquisition reader for MantisCam `.h5` (HDF5) recordings

> **Factory:** `from bsl_universal.analysis import open_mantis_file, open_mantis_folder, open_mantis_gs_file, open_mantis_gs_folder` then call one of:
> - `open_mantis_file(path, x3_conv=False, conv_param=0.8, origin=(0,0))`
> - `open_mantis_folder(path, sort_with_exp=False, x3_conv=False, x3_conv_param=0.8)`
> - `open_mantis_gs_file(path, imager_type="FSI", is_2x2=False, origin=(0,0), R_loc=(0,1), G_loc=(1,0), B_loc=(0,0), SP_loc=(1,1), dark_frames=None, enable_dark_sub=False, use_filename_exp=True, filename_exp_reg=None)`
> - `open_mantis_gs_folder(path, sort_with_exp=False, imager_type="FSI", is_2x2=False, origin=(1,0), R_loc=(0,1), G_loc=(1,0), B_loc=(0,0), SP_loc=(1,1), dark_path=None, enable_dark_sub=None, use_filename_exp=True, filename_exp_reg=None, force_dark_files=True)`
> **Transport:** none — this is a **file/HDF5 analysis layer**, NOT a hardware driver. No VISA/Serial/USB/ZMQ. No `device_sn`. (For the live camera driver see the `mantisCam` ZMQ instrument in [00-runtime-and-construction.md](00-runtime-and-construction.md).) · **Datasheet:** none on disk · **Source:** `bsl_universal/analysis/api.py`, `bsl_universal/analysis/_mantisCam/mantis_file.py`, `mantis_folder.py`, `mantis_file_GS.py`, `mantis_folder_GS.py`

## When to use this
Use this to read and post-process MantisCam recordings already saved to disk as `.h5` (HDF5) files — never to control the camera (no acquisition, no exposure setting, no triggering; everything here is read-only disk I/O plus NumPy). Pick the **standard** path (`open_mantis_file` / `open_mantis_folder`) for ordinary single-gain recordings stored as `[N, H, W, C]`. Pick the **GSense (GS)** path (`open_mantis_gs_file` / `open_mantis_gs_folder`) for GSense dual-gain sensors where each frame is one wide image (typ. `2048x4096`) whose left half is high-gain and right half is low-gain, when you need HDR reconstruction, 2x2 color-filter demosaicing, or per-exposure dark-frame subtraction. Use the `*_folder*` variants to batch a directory of `.h5` files indexed by filename.

## Construct & tear down
There is **no `close()` and no context manager** — every property opens the `.h5` file with `h5py.File(..., 'r')` and closes it within that call (a `with` block), so each file handle is short-lived. "Tear down" just means dropping the Python reference. The `path` argument selects the file (or, for folders, the directory); these objects do **not** select a hardware device.

```python
from bsl_universal.analysis import open_mantis_file

# Standard single-gain recording. path may be str or pathlib.Path.
f = open_mantis_file("/data/run01/scene_2.5ms.h5")
try:
    print(f.raw_data_shape)        # (N, H, W, C) — one short h5py read per dim
    frame0 = f[0]                  # np.ndarray [H, W, C], dtype uint16
    all_frames = f.frames          # np.ndarray [N, H, W, C], loads ENTIRE stack into RAM
finally:
    del f                          # no close(); just drop the reference

# GSense dual-gain recording with HDR
from bsl_universal.analysis import open_mantis_gs_file
g = open_mantis_gs_file("/data/run01/scene_2.5ms.h5", imager_type="FSI")
g.init_HDR(tone_mapping="None")    # call BEFORE reading any HDR property
hdr = g.frames_GS_HDR              # [N, 2048, 2048] uint16
```

`path` selects the file. For folders, `path` is the directory; only top-level `*.h5` files (non-recursive `iterdir()`) are loaded.

## Most-used operations

### `open_mantis_file(path, x3_conv=False, conv_param=0.8, origin=(0,0))` -> `mantis_file`
- **Does:** Wrap one standard `.h5` recording. No disk read at construction; reads happen lazily per property.
- **Args:** `path` (str or `Path`); `x3_conv` (bool — if True, apply the OpenCV "x3" deconvolution filter to every frame on read); `conv_param` (float, unitless filter coefficient, default 0.8); `origin` (tuple, accepted but **unused** in `mantis_file`).
- **Returns:** `mantis_file`.
- **Blocks?** No I/O at construction. **Readback?** N/A (no hardware). **Raises:** nothing at construct; later property reads raise `OSError`/`KeyError` if the file is missing or lacks the expected `camera/frames` dataset.
- **Example:** `f = open_mantis_file("scene.h5")`

### `f[i]` (`__getitem__`) -> `np.ndarray`
- **Does:** Read a single frame `i` from disk, apply x3 conv if enabled, then apply dark subtraction if enabled.
- **Args:** `i` (int or any h5py-valid index, e.g. slice).
- **Returns:** `np.ndarray` shape `[H, W, C]`, dtype `uint16` (frame values are camera ADU counts; no physical unit).
- **Blocks?** Yes — one disk read. **Raises:** `IndexError`/`OSError` on bad index/file.
- **Example:** `frame = f[0]`

### `f.frames` (property) -> `np.ndarray`
- **Does:** Load the **entire** frame stack into RAM, apply x3 conv if enabled, then dark subtraction if enabled.
- **Returns:** `np.ndarray` `[N, H, W, C]`, dtype `uint16` (ADU). If dark-sub is enabled the result is float-subtracted, clamped to `>=0`, and cast back to `uint16`.
- **Blocks?** Yes — reads all N frames; can be large. **Raises:** `MemoryError` for big files.
- **Example:** `arr = f.frames`

### `f.apply_dark_subtraction(dark_data)` -> `None`  *(standard `mantis_file` only)*
- **Does:** Enable in-memory dark subtraction; stores `dark_data` cast to `float32`. Subsequent `f[i]` / `f.frames` subtract it and clamp negatives to 0.
- **Args:** `dark_data` (`np.ndarray`). Accepted shapes per docstring: `[H,W]`, `[H,W,C]`, or `[N,H,W,C]`. `[H,W,C]` broadcasts over all frames; `[N,H,W,C]` matches frame-by-frame only when shapes are exactly equal.
- **Returns:** None (logs at INFO). **Raises:** `AttributeError` if `dark_data` is not an ndarray (it calls `.astype`).
- **Gotcha:** If shapes don't match a handled case, it logs a WARNING and still attempts a raw NumPy broadcast subtraction (may raise `ValueError`). See Audit notes for the unused `frame_idx`.
- **Example:** `f.apply_dark_subtraction(dark_2d)` then `f.disable_dark_subtraction()` to turn off.

### `open_mantis_gs_file(path, imager_type="FSI", is_2x2=False, ...)` -> `mantis_file_GS`
- **Does:** Wrap one GSense dual-gain `.h5`. Selects calibration constants from `imager_type` at construction.
- **Args:** `imager_type` (str, **must be `"FSI"` or `"BSI"`**, case-insensitive — any other value raises); `is_2x2` (bool — set True only when a physical 2x2 color filter array is present); `origin`, `R_loc`, `G_loc`, `B_loc`, `SP_loc` (each `(row,col)` 2x2 offset for sub-sampling); `dark_frames` (dict `{exposure_time(float): 2D dark[H,W]}` or None); `enable_dark_sub` (bool); `use_filename_exp` (bool — parse exposure from filename vs. file data); `filename_exp_reg` (regex str or None).
- **Returns:** `mantis_file_GS`.
- **Blocks?** No I/O at construct. **Raises:** `ValueError` if `imager_type` is not FSI/BSI.
- **Example:** `g = open_mantis_gs_file("scene_2.5ms.h5", imager_type="BSI")`

### `g.init_HDR(tone_mapping="None", mid_tone=0.5, contrast=10, power=0.5)` -> `None`  *(GS only)*
- **Does:** Set HDR tone-mapping parameters used by all `frames_GS_HDR*` properties. **Call before** any HDR property, otherwise defaults are used and a WARNING is logged.
- **Args:** `tone_mapping` (str, one of `"None"`/`"compress"`/`"enhance"`, matched case-insensitively via `.lower()`); `mid_tone` (float, used only by `"enhance"`); `contrast` (float, sigmoid factor for `"enhance"`); `power` (float, gamma exponent for `"compress"`).
- **Returns:** None (logs INFO). **Raises:** none (unknown `tone_mapping` strings silently fall through to linear/"none").
- **Example:** `g.init_HDR("compress", power=0.5)`

### `g.frames_GS_high_gain` / `g.frames_GS_low_gain` (properties) -> `np.ndarray`  *(GS)*
- **Does:** Return the left half (high-gain) / right half (low-gain) of every frame after optional per-exposure dark subtraction.
- **Returns:** `np.ndarray` `[N, 2048, 2048]` (i.e. `[N, n_rows, n_cols//2]`), dtype `uint16` (ADU).
- **Blocks?** Yes (loads & caches the full `[N,H,W]` stack on first call). **Example:** `hg = g.frames_GS_high_gain`

### `g.frames_GS_HDR` (property) -> `np.ndarray`  *(GS)*
- **Does:** Reconstruct HDR by combining high/low-gain halves: where `HG <= Threshold` keep HG, else use `K_RATIO * LG - param_b`; normalize and (optionally) tone-map; rescale to 16-bit.
- **Returns:** `np.ndarray` `[N, 2048, 2048]`, dtype `uint16`.
- **Blocks?** Yes. **Readback?** N/A. **Raises:** none beyond I/O. Auto-calls `init_HDR` with defaults (and WARNs) if you forgot.
- **Example:** `hdr = g.frames_GS_HDR`

### `open_mantis_folder(path, sort_with_exp=False, x3_conv=False, x3_conv_param=0.8)` -> `mantis_folder`
- **Does:** Index all top-level `*.h5` files in `path` into `mantis_file` objects keyed by filename.
- **Args:** `sort_with_exp` (bool — if True, order the internal dict by the `x.xms` exposure parsed from each filename; **filenames MUST contain `<float>ms`** or `__extract_time_key` raises on the missing match); `x3_conv`/`x3_conv_param` forwarded to each file.
- **Returns:** `mantis_folder`. **Blocks?** Light — `iterdir()` only; frames load lazily. **Raises:** `AttributeError`/`ValueError` from the regex if `sort_with_exp=True` and a filename lacks `<float>ms`.
- **Example:** `fold = open_mantis_folder("/data/run01", sort_with_exp=True)`; access via `fold["scene_2.5ms.h5"]` or `fold.find_key("2.5ms")`.

### `open_mantis_gs_folder(path, ..., dark_path=None, enable_dark_sub=None, force_dark_files=True)` -> `mantis_folder_GS`
- **Does:** Index `*.h5` into `mantis_file_GS` objects; optionally load dark frames from `dark_path` (file or directory) into a `{exposure: mean_dark[H,W]}` dict shared across all files.
- **Args:** `sort_with_exp` (bool, default **False**; GS folder sort tolerates missing `ms` — unmatched filenames sort last via key `999999`); `imager_type`/`is_2x2`/`origin`/`R_loc`/`G_loc`/`B_loc`/`SP_loc` forwarded to each file (note GS folder default `origin=(1,0)`); `dark_path` (str/Path to a dark `.h5` or a folder); `enable_dark_sub` (bool or None — **if `dark_path` is given and this is None, it auto-enables**); `force_dark_files` (bool — if False, only files whose name matches `dark` (case-insensitive) are treated as darks; if True, every `.h5` in the dark dir is used).
- **Returns:** `mantis_folder_GS`.
- **Blocks?** Loads & averages dark frames at construct if dark-sub active. **Raises:** I/O errors if `dark_path` invalid.
- **Example:** `gf = open_mantis_gs_folder("/data/run01", dark_path="/data/darks", imager_type="FSI")` then `gf.init_HDR_for_all("None")`.

## Full method index

### `mantis_file` (standard) — `open_mantis_file`
| name | kind | purpose | key args (units) | returns |
|---|---|---|---|---|
| `apply_dark_subtraction` | method | enable in-memory dark sub | `dark_data: np.ndarray` ([H,W] / [H,W,C] / [N,H,W,C], ADU) | None |
| `disable_dark_subtraction` | method | turn dark sub off, clear stored frame | — | None |
| `__getitem__` (`f[i]`) | method | read one frame (+conv +dark) | `i: int`/slice | ndarray [H,W,C] uint16 |
| `frames` | property | full stack (+conv +dark) | — | ndarray [N,H,W,C] uint16 |
| `file_name` | property | the `.h5` filename | — | str |
| `system_infos` | property | HDF5 root attrs | — | dict |
| `exposure_times` | property | `camera/integration-time-expected` | — | ndarray |
| `timestamps` | property | `camera/timestamp` | — | ndarray |
| `frames_GS_high_gain` | property | left half of frames `[:, :, 0:n_cols//2, :]` | — | ndarray |
| `frames_GS_low_gain` | property | right half of frames `[:, :, n_cols//2:, :]` | — | ndarray |
| `n_frames` | property | N | — | int |
| `n_rows` | property | H | — | int |
| `n_cols` | property | W | — | int |
| `n_chans` | property | C | — | int |
| `is_monochrome` | property | `n_chans == 1` | — | bool |
| `raw_data_shape` | property | (N,H,W,C) | — | tuple |
| `frame_shape` | property | (H,W,C) | — | tuple |
| `_maybe_sub_dark` | private helper (surfaced) | applies stored dark sub + clamp | `frames`, `frame_idx=None` (frame_idx UNUSED) | ndarray uint16 |

### `mantis_folder` (standard) — `open_mantis_folder`
| name | kind | purpose | key args (units) | returns |
|---|---|---|---|---|
| `__getitem__` (`fold[name]`) | method | get the `mantis_file` for a filename key | `name: str` | mantis_file |
| `find_key` | method | first filename containing substring | `key: str` | str (raises ValueError if none) |
| `n_videos` | property | file count | — | int |
| `name_videos` | property | filenames sorted by mtime | — | list[str] |
| `arr_files` | property | all `mantis_file` objects | — | np.ndarray[mantis_file] |
| `arr_videos` | property | **all frames of all files** in RAM | — | ndarray [n_files,N,H,W,C] (WARNs RAM estimate) |

### `mantis_file_GS` (GSense) — `open_mantis_gs_file`
| name | kind | purpose | key args (units) | returns |
|---|---|---|---|---|
| `init_HDR` | method | set HDR/tone-map params | `tone_mapping` {None/compress/enhance}, `mid_tone`,`contrast`,`power` (float) | None |
| `frames` | property | full stack, dark-subbed, `[..., newaxis]` | — | ndarray [N,2048,4096,1] uint16 |
| `file_name` | property | filename | — | str |
| `system_infos` | property | HDF5 root attrs | — | dict |
| `exposure_times` | property | `integration-time-expected` | — | ndarray |
| `timestamps` | property | `timestamp` | — | ndarray |
| `frames_GS_high_gain` | property | left half [N,2048,2048] | — | ndarray |
| `frames_GS_low_gain` | property | right half [N,2048,2048] | — | ndarray |
| `frames_2x2_subsample` | property | 2x2 subsample (needs is_2x2) | — | ndarray [N,1024,2048] (WARNs if not 2x2) |
| `frames_GS_high_gain_2x2` | property | HG 2x2 subsample | — | ndarray [N,1024,1024] |
| `frames_GS_low_gain_2x2` | property | LG 2x2 subsample | — | ndarray [N,1024,1024] |
| `frames_GS_HDR` | property | HDR reconstruction | — | ndarray [N,2048,2048] uint16 |
| `frames_GS_high_gain_RGB` | property | demosaiced RGB from HG (needs is_2x2) | — | ndarray [N,2048,2048,3] (empty if not 2x2) |
| `frames_GS_low_gain_RGB` | property | demosaiced RGB from LG | — | ndarray [N,2048,2048,3] (empty if not 2x2) |
| `frames_GS_HDR_RGB` | property | demosaiced RGB from HDR | — | ndarray (empty if not 2x2) |
| `frames_GS_high_gain_SP` | property | special-plane from HG | — | ndarray [N,1024,1024] (empty if not 2x2) |
| `frames_GS_low_gain_SP` | property | special-plane from LG | — | ndarray (empty if not 2x2) |
| `frames_GS_HDR_SP` | property | special-plane from HDR | — | ndarray (empty if not 2x2) |
| `n_frames`/`n_rows`/`n_cols`/`n_chans` | property | shape dims | — | int |
| `is_monochrome` | property | `not is_2x2` | — | bool |
| `raw_data_shape` | property | (N,H,W,C) | — | tuple |
| `frame_shape` | property | (H,W,C) | — | tuple |
| `_get_dark_subbed_frames` | private (surfaced) | load+cache `[N,H,W]` channel-0, per-exposure dark sub | — | ndarray [N,H,W] uint16 |
| `_resolve_exposure` | private | exposure from filename or file data | `frame_idx=0` | float (us) |
| `_get_dark_frame` | private | nearest-key dark for an exposure | `exptime: float` | 2D ndarray or 0 |
| `_HDR_reconstruction` | private | blend HG/LG -> HDR | frames, tone params | ndarray uint16 |

### `mantis_folder_GS` (GSense) — `open_mantis_gs_folder`
| name | kind | purpose | key args (units) | returns |
|---|---|---|---|---|
| `init_HDR_for_all` | method | call `init_HDR` on every file | `tone_mapping`,`mid_tone`,`contrast`,`power` | None |
| `__getitem__` (`gf[name]`) | method | get `mantis_file_GS` by filename | `name: str` | mantis_file_GS |
| `find_key` | method | first filename containing substring | `key: str` | str (raises ValueError) |
| `n_videos` | property | file count | — | int |
| `name_videos` | property | filenames sorted by mtime | — | list[str] |
| `arr_files` | property | all `mantis_file_GS` objects | — | np.ndarray |
| `arr_videos` | property | all frames of all files in RAM | — | ndarray (WARNs RAM) |
| `_load_dark_frames` | private | build `{exp: mean dark[H,W]}` from file/dir | dark_path, regex, force | dict |
| `_load_dark_file` | private | mean of `frames[1:]` (or all if <=1) | dark_file | `{exp: 2D}` |
| `_parse_exposure_from_filename` | private | regex/heuristic exposure parse | filename, regex | float |

## Units, ranges & limits
- **Frame values:** raw camera ADU counts (no physical unit). Standard stack dtype `uint16`, shape `[N, H, W, C]`. GS frames are cast/clamped to `uint16`; GS `frames` shape is `[N, 2048, 4096, 1]`, with halves `[N, 2048, 2048]`.
- **Exposure:** `_resolve_exposure` returns exposure in **microseconds (us)** per its docstring; folder filename sort parses `<float>ms` from the filename (milliseconds). The HDF5 dataset is `camera/integration-time-expected`.
- **GS calibration constants (class attributes, ADU-scale, from `mantis_file_GS`):**
  - BSI: `K_HG_BSI = 1.813*16`, `K_LG_BSI = 0.274*16`, `Threshold_BSI = 3300*16`, `Dark_Level_LG_BSI = 200`, `Dark_Level_HG_BSI = 500`.
  - FSI: `K_HG_FSI = 2.931*16`, `K_LG_FSI = 0.119*16`, `Threshold_FSI = 3500*16`, `Dark_Level_LG_FSI = 1000`, `Dark_Level_HG_FSI = 1300`.
  - Derived: `K_RATIO = K_HG / K_LG`. `param_b = K_RATIO*Dark_Level_LG - Dark_Level_HG` normally, but **`param_b = 0` whenever `enable_dark_sub=True`** (dark frames assumed to handle the offset).
- **`imager_type`:** must be `"FSI"` or `"BSI"` (case-insensitive); any other value raises `ValueError`.
- **HDR `tone_mapping`:** `"None"` (linear), `"compress"` (gamma `**power`), `"enhance"` (sigmoid with `mid_tone`,`contrast`). Unknown strings behave as `"None"`.
- **HDR scaling:** normalized by `denom = K_RATIO*65535 - param_b`, then rescaled to 16-bit and clipped to `[0, 65535]`.
- **2x2 sub-sampling:** offsets are `(row, col)` taken `origin[0]::2, origin[1]::2`. GS-file default `origin=(0,0)`; GS-folder default `origin=(1,0)`. `R_loc=(0,1)`, `G_loc=(1,0)`, `B_loc=(0,0)`, `SP_loc=(1,1)` by default.
- **Channels:** standard `is_monochrome` <=> `n_chans == 1`. GS `is_monochrome` <=> `not is_2x2` (it does NOT inspect the data).
- **Folder scanning:** non-recursive `iterdir()`, suffix `== '.h5'` only.
- **No hardware timeouts, no `device_sn`, no power/current/wavelength limits** — this module touches no instrument.

## Safety & gotchas
- **No `.safe` recovery layer here.** These analysis objects are NOT `ManagedInstrument`s and have no `.safe` / `.invoke` / `.reconnect` (see [00-runtime-and-construction.md](00-runtime-and-construction.md) for the hardware recovery layer — it does not apply to file analysis). There is also **no `close()`**; files are opened read-only per call and closed immediately. To release, drop the reference.
- **`.frames`, `.arr_videos`, and `_get_dark_subbed_frames` load entire datasets into RAM.** `arr_videos` loads *every frame of every file in a folder at once* and logs a RAM-estimate WARNING — it can crash the kernel. Prefer per-frame `f[i]` or per-file access for large data.
- **`init_HDR` must precede HDR properties.** If you read `frames_GS_HDR*` without it, defaults are silently applied with only a WARNING; results may not match your intent.
- **Dark-sub shape mismatch (standard `mantis_file`) is non-fatal but risky.** Unhandled shape combos fall through to a raw `frames_f32 -= self._dark_frame`, which either broadcasts unexpectedly or raises `ValueError`. Verify your dark array shape matches `frame_shape`/`raw_data_shape`.
- **GS dark frames are matched by NEAREST exposure key**, not exact. If no exact match it logs a WARNING and uses the closest available dark — confirm your `dark_frames` keys cover your exposures.
- **`_get_dark_subbed_frames` caches** on first call; changing dark settings afterward will not invalidate the cache on an existing object.
- **GS reads only channel 0** of `camera/frames` (`[:,:,:,0]`); multi-channel GS data beyond channel 0 is ignored by the GS path.
- **Folder sort fragility (standard):** `open_mantis_folder(..., sort_with_exp=True)` requires every filename to contain `<float>ms`; a missing match raises (the GS folder tolerates it, sorting unmatched files last).
- **`name_videos` is mtime-sorted; the internal `__videos` dict order may differ** (insertion or exposure-sorted). Don't assume `arr_files`/`arr_videos` order equals `name_videos` order.
- **No destructive operations** — read-only disk I/O only. The "x3 conv" filter mutates returned frames (flip/`cv2.filter2D`/roll), not the file.

## Audit notes (2026-06-28)
- **Fixed:**
  - **`sort_with_exp` default is now consistent.** The public folder constructors and their internal init helper agree: folder sorting is **off unless you pass `sort_with_exp=True`** (previously the private helper defaulted to `True`, which could sort even when the public default said `False`).
  - **`imager_type` is now validated.** Passing anything other than `"FSI"`/`"BSI"` raises `ValueError`. Previously any non-`"FSI"` string silently selected the BSI calibration constants; choose the imager explicitly and expect an exception on typos.
- **Known / deferred:**
  - **`_maybe_sub_dark` accepts a `frame_idx` argument but never uses it** to index a per-frame `[N,H,W,C]` dark volume (standard `mantis_file`). Do NOT rely on per-frame dark indexing through `f[i]`: a 4D dark volume is only subtracted correctly when its shape exactly equals the full stack shape in `frames`; for single-frame `f[i]` reads the index is ignored and subtraction falls back to broadcast/shape-equality logic. Supply a `[H,W]`/`[H,W,C]` broadcastable dark for predictable per-frame behavior.
