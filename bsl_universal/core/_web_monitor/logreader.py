from __future__ import annotations

"""
Log analyzer backend for the web device monitor.

Reads the JSON-lines log files written by ``bsl_universal.core.logging`` (one
per process under ``~/.bsl_universal/logs``), normalizes records, and provides
filtering, faceting, time-bucketed volume statistics, and error clustering.

Performance: only the tail of each file is read (bounded byte window), parsed
records are cached per (path, size) so repeated polls are cheap, and the total
number of scanned lines is capped.
"""

import json
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

try:
    from ..logging import log_directory
except Exception:  # pragma: no cover
    def log_directory() -> Path:
        return Path.home() / ".bsl_universal" / "logs"

MAX_TAIL_BYTES = 3_000_000      # bytes read from the end of each file
MAX_SCAN_RECORDS = 40_000       # hard cap on records held in memory per query
MAX_SCAN_FILES = 80             # newest N files visited per query (bounds work/memory)
MAX_CACHE_FILES = 48            # LRU cap on the per-file parsed-record cache
LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
_LEVELNO = {"TRACE": 5, "DEBUG": 10, "INFO": 20, "SUCCESS": 25, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

_HEX = re.compile(r"0x[0-9a-fA-F]+")
_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")

_cache_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[int, list[dict]]]" = OrderedDict()  # path -> (size, records), LRU


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce to int, returning ``default`` on any bad/missing value (never raises)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_log_dir() -> Path:
    try:
        return log_directory()
    except Exception:
        return Path.home() / ".bsl_universal" / "logs"


def list_log_files() -> list[dict[str, Any]]:
    """List available log files, newest first."""
    directory = _safe_log_dir()
    out: list[dict[str, Any]] = []
    try:
        for path in directory.glob("*.log"):
            try:
                st = path.stat()
                out.append({"name": path.name, "size": st.st_size, "mtime": st.st_mtime})
            except OSError:
                continue
    except Exception:
        return []
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def _resolve_file(name: str) -> Optional[Path]:
    """Resolve a user-supplied file name safely inside the log dir (no traversal)."""
    directory = _safe_log_dir().resolve()
    target = (directory / name).resolve()
    if target.parent != directory or not target.is_file():
        return None
    return target


def _parse_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line or line[0] != "{":
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None
    rec = obj.get("record")
    if not isinstance(rec, dict):
        return None
    lvl = rec.get("level") or {}
    tm = rec.get("time") or {}
    proc = rec.get("process") or {}
    fileinfo = rec.get("file") or {}
    exc = rec.get("exception")
    exc_str = None
    if exc:
        if isinstance(exc, dict):
            head = (str(exc.get("type") or "").strip() + ": " + str(exc.get("value") or "").strip()).strip(": ").strip()
            tb = exc.get("traceback")
            exc_str = head or "exception"
            if isinstance(tb, str) and tb.strip():
                exc_str = (exc_str + "\n" + tb).strip()
        else:
            exc_str = str(exc)
    try:
        ts = float(tm.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        ts = 0.0
    return {
        "ts": ts,
        "level": str(lvl.get("name") or "INFO").upper(),
        "levelno": _as_int(lvl.get("no"), _LEVELNO.get(str(lvl.get("name") or "").upper(), 0)),
        "module": str(rec.get("name") or rec.get("module") or ""),
        "function": str(rec.get("function") or ""),
        "line": _as_int(rec.get("line")),
        "message": str(rec.get("message") or ""),
        "file": str(fileinfo.get("name") or ""),
        "pid": _as_int(proc.get("id")),
        "exception": exc_str,
    }


def _read_file_records(path: Path) -> list[dict]:
    """Parse the tail of one log file, using a (path,size) cache."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    key = str(path)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] == size:
            _cache.move_to_end(key)  # mark recently used
            return cached[1]
    try:
        with path.open("rb") as fh:
            if size > MAX_TAIL_BYTES:
                fh.seek(size - MAX_TAIL_BYTES)
                fh.readline()  # drop partial line
            raw = fh.read()
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        # one malformed/non-loguru line must never abort the scan or poison the cache
        try:
            parsed = _parse_line(line)
        except Exception:
            continue
        if parsed is not None:
            records.append(parsed)
    with _cache_lock:
        _cache[key] = (size, records)
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHE_FILES:  # bounded LRU
            _cache.popitem(last=False)
    return records


def _gather(since_ts: float = 0.0, files: Optional[list[str]] = None) -> list[dict]:
    """Collect parsed records (newest files first), capped at MAX_SCAN_RECORDS."""
    if files:
        paths = [p for p in (_resolve_file(n) for n in files) if p is not None]
    else:
        directory = _safe_log_dir()
        try:
            paths = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_SCAN_FILES]
        except Exception:
            paths = []
    out: list[dict] = []
    for path in paths:
        for rec in _read_file_records(path):
            if since_ts and rec["ts"] < since_ts:
                continue
            out.append(rec)
            if len(out) >= MAX_SCAN_RECORDS:
                return out
    return out


def query(
    *,
    levels: Optional[list[str]] = None,
    q: str = "",
    module: str = "",
    since_ts: float = 0.0,
    limit: int = 500,
    files: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Return filtered log records (newest first) plus facets.

    Parameters mirror the ``/api/logs`` query string.
    """
    limit = max(1, min(int(limit or 500), 5000))
    records = _gather(since_ts=since_ts, files=files)

    # facets computed over the time-windowed set (independent of level/q/module)
    level_facet = {lv: 0 for lv in LEVELS}
    module_counts: dict[str, int] = {}
    for rec in records:
        level_facet[rec["level"]] = level_facet.get(rec["level"], 0) + 1
        module_counts[rec["module"]] = module_counts.get(rec["module"], 0) + 1

    level_set = {lv.upper() for lv in levels} if levels else None
    qlow = q.strip().lower()
    mlow = module.strip().lower()

    def keep(rec: dict) -> bool:
        if level_set and rec["level"] not in level_set:
            return False
        if mlow and mlow not in rec["module"].lower():
            return False
        if qlow:
            hay = (rec["message"] + " " + rec["module"] + " " + rec["function"] + " " + (rec["exception"] or "")).lower()
            if qlow not in hay:
                return False
        return True

    filtered = [r for r in records if keep(r)]
    filtered.sort(key=lambda r: r["ts"], reverse=True)
    total = len(filtered)
    page = filtered[:limit]

    top_modules = sorted(module_counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
    return {
        "records": page,
        "returned": len(page),
        "matched": total,
        "scanned": len(records),
        "facets": {
            "levels": level_facet,
            "modules": [{"module": m, "count": c} for m, c in top_modules],
        },
    }


def _normalize(message: str) -> str:
    m = _HEX.sub("0xX", message)
    m = _NUM.sub("N", m)
    m = _WS.sub(" ", m).strip()
    return m[:160]


def stats(*, hours: float = 6.0, buckets: int = 60) -> dict[str, Any]:
    """Time-bucketed volume per level, error clustering, and top modules."""
    hours = max(0.05, min(float(hours or 6.0), 24.0 * 14))
    buckets = max(6, min(int(buckets or 60), 240))
    now = time.time()
    since = now - hours * 3600.0
    records = _gather(since_ts=since)

    span = max(1.0, now - since)
    width = span / buckets
    grid = [{"t": since + i * width, "counts": {}} for i in range(buckets)]

    totals = {lv: 0 for lv in LEVELS}
    clusters: dict[str, dict[str, Any]] = {}
    module_counts: dict[str, int] = {}

    for rec in records:
        idx = int((rec["ts"] - since) / width)
        if idx < 0:
            idx = 0
        elif idx >= buckets:
            idx = buckets - 1
        b = grid[idx]["counts"]
        b[rec["level"]] = b.get(rec["level"], 0) + 1
        totals[rec["level"]] = totals.get(rec["level"], 0) + 1
        module_counts[rec["module"]] = module_counts.get(rec["module"], 0) + 1
        if rec["levelno"] >= 30:  # WARNING+
            key = rec["level"] + "|" + _normalize(rec["message"])
            c = clusters.get(key)
            if c is None:
                clusters[key] = {"message": rec["message"][:200], "level": rec["level"], "count": 1, "last_ts": rec["ts"]}
            else:
                c["count"] += 1
                if rec["ts"] > c["last_ts"]:
                    c["last_ts"] = rec["ts"]
                    c["message"] = rec["message"][:200]

    total = sum(totals.values())
    err = totals.get("ERROR", 0) + totals.get("CRITICAL", 0)
    top_errors = sorted(clusters.values(), key=lambda c: c["count"], reverse=True)[:10]
    top_modules = sorted(module_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "since": since,
        "now": now,
        "bucket_width": width,
        "buckets": grid,
        "totals": totals,
        "total": total,
        "error_count": err,
        "warning_count": totals.get("WARNING", 0),
        "error_rate": round(err / total, 4) if total else 0.0,
        "top_errors": top_errors,
        "top_modules": [{"module": m, "count": c} for m, c in top_modules],
        "levels": list(LEVELS),
    }
