from __future__ import annotations

"""
Web-based BSL instrument monitor — stdlib HTTP + Server-Sent Events.

A standalone, dependency-free monitor server. It reads the shared device-health
state written by every bsl_universal process (via ``device_health_hub``) and
serves a live single-page web UI plus a small JSON API. Live updates are pushed
to browsers over SSE; a single background poller watches the on-disk snapshot
(the hub's ``subscribe`` is in-process only, so cross-process changes are only
visible through the shared state file).

Run standalone with ``python -m bsl_universal.core._web_monitor``.
"""

import io
import csv
import json
import math
import os
import socket
import threading
import time
import mimetypes
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from loguru import logger

from ..device_health import device_health_hub
from ..logging import log_directory
from . import logreader

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to ``default`` on any error."""
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except Exception:
        return default


DEFAULT_PORT = _env_int("BSL_MONITOR_PORT", 8787)
DEFAULT_HOST = (os.environ.get("BSL_MONITOR_HOST", "") or "0.0.0.0").strip() or "0.0.0.0"
STATIC_DIR = (Path(__file__).resolve().parent / "static")

POLL_INTERVAL_SEC = 0.7
SSE_HEARTBEAT_SEC = 15.0
HISTORY_MAXLEN = 250
MAX_SSE_CLIENTS = 64          # cap concurrent live streams (DoS guard)
HANDLER_TIMEOUT_SEC = 30.0    # per-connection socket timeout (slowloris guard)
ACTIVE_STATES = {"CONNECTING", "CONNECTED", "WARNING", "UNRECOVERABLE_FAILURE"}
ALL_STATES = ("CONNECTING", "CONNECTED", "WARNING", "UNRECOVERABLE_FAILURE", "STALE_SESSION", "DISCONNECTED")

_CLEAR_SCOPES = {
    "disconnected_stale": ("DISCONNECTED", "STALE_SESSION"),
    "warnings_failures": ("WARNING", "UNRECOVERABLE_FAILURE"),
    "all": None,
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lan_ip() -> str:
    """Best-effort primary LAN IPv4 address (no traffic actually sent)."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except Exception:
        return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _server_info(host: str, port: int) -> dict[str, Any]:
    ip = _lan_ip()
    return {
        "host": host,
        "port": port,
        "lan_url": f"http://{ip}:{port}/",
        "local_url": f"http://127.0.0.1:{port}/",
        "lan_ip": ip,
    }


def _qfloat(qs: dict, name: str, default: float) -> float:
    try:
        v = float(qs.get(name, [default])[0])
    except (TypeError, ValueError):
        return float(default)
    return v if math.isfinite(v) else float(default)  # reject inf/nan (would crash int())


def _counts(devices: list[dict]) -> dict[str, int]:
    counts = {state: 0 for state in ALL_STATES}
    for dev in devices:
        key = str(dev.get("status", "")).upper()
        if key in counts:
            counts[key] += 1
    counts["TOTAL"] = len(devices)
    counts["ACTIVE"] = sum(1 for d in devices if str(d.get("status", "")).upper() in ACTIVE_STATES)
    return counts


def _oauth_status(cfg) -> dict[str, Any]:
    """Mirror the legacy GUI's OAuth-token health check."""
    raw = (getattr(cfg, "oauth_token_file", "") or "").strip()
    if not raw:
        return {"authorized": False, "detail": "No OAuth token path configured."}
    path = Path(raw).expanduser()
    if not path.exists():
        return {"authorized": False, "detail": "Not authorized yet. Click 'Authorize Google'."}
    try:
        scopes = json.loads(path.read_text(encoding="utf-8")).get("scopes", [])
        scopes = {str(s).strip() for s in scopes if isinstance(s, str) and str(s).strip()}
    except Exception:
        scopes = set()
    if scopes and "https://mail.google.com/" not in scopes:
        return {"authorized": False, "detail": "Token scope is incompatible with SMTP mode. Re-authorize."}
    return {"authorized": True, "detail": f"Authorized (token at {path})."}


# --------------------------------------------------------------------------- #
# Live monitor state (poller + SSE fan-out)
# --------------------------------------------------------------------------- #


class MonitorState:
    """Polls the shared health snapshot and fans changes out to SSE clients."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._subscribers: set["queue_Queue"] = set()  # type: ignore[name-defined]
        self._latest: list[dict] = []
        self._digest: str = ""
        self._history: dict[str, deque] = {}
        self._last_status: dict[str, str] = {}
        self._connected_since: dict[str, float] = {}
        self._started = False
        self._poll_request = threading.Event()
        self._events: deque = deque(maxlen=2000)  # global status-transition feed

    # -- lifecycle ------------------------------------------------------ #

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        try:
            self._poll_once()
        except Exception as exc:  # pragma: no cover
            logger.debug("monitor initial poll failed: {}", exc)
        thread = threading.Thread(target=self._poll_loop, name="bsl-monitor-poller", daemon=True)
        thread.start()

    def _poll_loop(self) -> None:
        while True:
            try:
                self._poll_once()
            except Exception as exc:  # pragma: no cover
                logger.debug("monitor poll error: {}", exc)
            # Sleep until the next interval, or wake early when a mutating request
            # signals request_poll(). Only this thread ever runs _poll_once, so
            # polls never overlap (no racing file reads/writes, no duplicate work).
            self._poll_request.wait(POLL_INTERVAL_SEC)
            self._poll_request.clear()

    def request_poll(self) -> None:
        """Wake the poller thread to refresh soon (non-blocking, off the request thread)."""
        self._poll_request.set()

    # -- polling -------------------------------------------------------- #

    def _poll_once(self) -> None:
        try:
            device_health_hub.reconcile_stale_entries()
        except Exception:
            pass
        try:
            items = device_health_hub.get_snapshot_from_file()
        except Exception as exc:
            logger.debug("monitor snapshot read failed: {}", exc)
            return

        devices = [asdict(item) for item in items]
        devices.sort(key=lambda d: str(d.get("key", "")))
        digest = json.dumps(
            [(d.get("key"), d.get("status"), d.get("updated_at"), d.get("last_error"), d.get("process_id")) for d in devices],
            default=str,
        )
        now = time.time()
        changed = False

        with self._lock:
            present = set()
            for dev in devices:
                key = str(dev.get("key", ""))
                present.add(key)
                status = str(dev.get("status", "")).upper()
                prev = self._last_status.get(key)
                if prev != status:
                    self._history.setdefault(key, deque(maxlen=HISTORY_MAXLEN)).append(
                        {"ts": _now_iso(), "status": status}
                    )
                    self._last_status[key] = status
                    self._events.append({
                        "ts": now,
                        "iso": _now_iso(),
                        "key": key,
                        "model": dev.get("model", ""),
                        "device_type": dev.get("device_type", ""),
                        "from": prev,
                        "to": status,
                        "error": dev.get("last_error", ""),
                    })
                if status == "CONNECTED":
                    self._connected_since.setdefault(key, now)
                else:
                    self._connected_since.pop(key, None)
                hist = self._history.get(key)
                dev["active"] = status in ACTIVE_STATES
                since = self._connected_since.get(key)
                dev["connected_since"] = since  # epoch secs; client computes live uptime
                dev["uptime_seconds"] = round(now - since, 1) if since is not None else None
                dev["history"] = list(hist) if hist else []

            # prune vanished keys
            for key in list(self._last_status):
                if key not in present:
                    self._last_status.pop(key, None)
                    self._connected_since.pop(key, None)
                    self._history.pop(key, None)

            if digest != self._digest:
                self._digest = digest
                changed = True
            self._latest = devices

        if changed:
            self._broadcast()

    # -- snapshot / fan-out --------------------------------------------- #

    def snapshot_payload(self) -> dict[str, Any]:
        with self._lock:
            devices = [dict(d) for d in self._latest]
            events = list(self._events)[-60:][::-1]
        return {
            "devices": devices,
            "counts": _counts(devices),
            "events": events,
            "server": _server_info(self.host, self.port),
            "generated_at": _now_iso(),
        }

    def recent_events(self, limit: int = 500) -> list[dict]:
        with self._lock:
            return list(self._events)[-int(limit):][::-1]

    def analytics(self) -> dict[str, Any]:
        """Per-instrument reliability stats derived from the observed event feed."""
        with self._lock:
            devices = [dict(d) for d in self._latest]
            events = list(self._events)
            connected_since = dict(self._connected_since)
        now = time.time()
        per: dict[str, dict] = {}
        for ev in events:
            key = ev["key"]
            d = per.get(key)
            if d is None:
                d = per[key] = {
                    "key": key, "model": ev.get("model", ""), "device_type": ev.get("device_type", ""),
                    "transitions": 0, "connects": 0, "disconnects": 0, "failures": 0, "warnings": 0,
                    "first_ts": ev["ts"], "last_ts": ev["ts"],
                }
            d["transitions"] += 1
            d["last_ts"] = max(d["last_ts"], ev["ts"])
            d["first_ts"] = min(d["first_ts"], ev["ts"])
            to = ev.get("to")
            if to == "CONNECTED":
                d["connects"] += 1
            elif to == "DISCONNECTED":
                d["disconnects"] += 1
            elif to == "UNRECOVERABLE_FAILURE":
                d["failures"] += 1
            elif to == "WARNING":
                d["warnings"] += 1
        cur = {dv.get("key"): dv for dv in devices}
        out = []
        for key, d in per.items():
            dv = cur.get(key, {})
            d["status"] = str(dv.get("status", ""))
            d["last_error"] = str(dv.get("last_error", ""))
            d["uptime_seconds"] = round(now - connected_since[key], 1) if key in connected_since else None
            d["reconnects"] = max(0, d["connects"] - 1)
            out.append(d)
        out.sort(key=lambda x: (x["failures"] + x["warnings"], x["reconnects"], x["transitions"]), reverse=True)
        return {
            "instruments": out,
            "generated_at": _now_iso(),
            "totals": {
                "instruments": len(out),
                "events": len(events),
                "failures": sum(x["failures"] for x in out),
                "warnings": sum(x["warnings"] for x in out),
                "reconnects": sum(x["reconnects"] for x in out),
            },
        }

    def subscribe(self):
        import queue

        q = queue.Queue(maxsize=64)
        with self._lock:
            if len(self._subscribers) >= MAX_SSE_CLIENTS:
                return None  # too many live streams; caller sends 503
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def _broadcast(self) -> None:
        import queue

        data = json.dumps(self.snapshot_payload(), default=str)
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except Exception:
                    pass


STATE = MonitorState()


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #


class MonitorRequestHandler(BaseHTTPRequestHandler):
    server_version = "BSLMonitor/2.0"
    timeout = HANDLER_TIMEOUT_SEC  # per-connection socket timeout; frees threads on slow/dead peers

    # quiet by default; route to loguru at trace level
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        logger.trace("monitor http: " + fmt, *args)

    # -- response helpers ---------------------------------------------- #

    def _send_bytes(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, obj: Any, status: int = 200, extra: Optional[dict] = None) -> None:
        self._send_bytes(status, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 2_000_000:  # 2 MB sanity cap
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    # -- static --------------------------------------------------------- #

    def _serve_static(self, rel: str) -> None:
        if rel in ("", "/"):
            rel = "index.html"
        rel = rel.lstrip("/")
        base = STATIC_DIR.resolve()
        target = (STATIC_DIR / rel).resolve()
        if base != target and base not in target.parents:
            self._send_error_json(403, "forbidden")
            return
        if not target.is_file():
            self._send_error_json(404, "not found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send_bytes(200, target.read_bytes(), ctype)

    # -- SSE ------------------------------------------------------------ #

    def _serve_sse(self) -> None:
        import queue

        q = STATE.subscribe()
        if q is None:
            self._send_error_json(503, "too many live monitor connections")
            return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            STATE.unsubscribe(q)
            return

        try:
            self._sse_send(json.dumps(STATE.snapshot_payload(), default=str))
            while True:
                try:
                    data = q.get(timeout=SSE_HEARTBEAT_SEC)
                    self._sse_send(data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            STATE.unsubscribe(q)

    def _sse_send(self, data: str) -> None:
        self.wfile.write(b"event: snapshot\n")
        for line in data.split("\n"):
            self.wfile.write(b"data: " + line.encode("utf-8") + b"\n")
        self.wfile.write(b"\n")
        self.wfile.flush()

    # -- email config payload ------------------------------------------ #

    def _email_config_payload(self) -> dict[str, Any]:
        cfg = device_health_hub.get_email_config()
        payload = asdict(cfg)
        payload["supported_categories"] = list(device_health_hub.get_supported_alert_categories())
        payload["default_oauth_client_secret_file"] = device_health_hub.get_default_oauth_client_secret_file()
        payload["oauth"] = _oauth_status(cfg)
        instruments: list[str] = []
        seen: set[str] = set()
        with STATE._lock:
            latest = list(STATE._latest)
        for dev in latest:
            if str(dev.get("status", "")).upper() != "CONNECTED":
                continue
            token = str(dev.get("key", "")).split(":", 1)[0].strip()
            if token and token.lower() not in seen:
                instruments.append(token)
                seen.add(token.lower())
        payload["instruments"] = instruments
        return payload

    # -- routing -------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/stream":
                self._serve_sse()
                return
            if path == "/api/snapshot":
                self._send_json(STATE.snapshot_payload())
                return
            if path == "/api/snapshot.json":
                self._send_json(
                    STATE.snapshot_payload(),
                    extra={"Content-Disposition": 'attachment; filename="bsl_monitor_snapshot.json"'},
                )
                return
            if path == "/api/snapshot.csv":
                self._send_csv()
                return
            if path == "/api/categories":
                self._send_json({"categories": list(device_health_hub.get_supported_alert_categories())})
                return
            if path == "/api/events":
                self._send_json({"events": STATE.recent_events(800)})
                return
            if path == "/api/analytics":
                self._send_json(STATE.analytics())
                return
            if path == "/api/logs":
                self._send_json(self._logs_payload(parsed.query))
                return
            if path == "/api/logs/stats":
                qs = parse_qs(parsed.query)
                self._send_json(logreader.stats(hours=_qfloat(qs, "hours", 6.0), buckets=int(_qfloat(qs, "buckets", 60))))
                return
            if path == "/api/logs/files":
                self._send_json({"files": logreader.list_log_files(), "dir": str(log_directory())})
                return
            if path == "/api/logs.csv":
                self._send_logs_csv(parsed.query)
                return
            if path == "/api/email-config":
                self._send_json(self._email_config_payload())
                return
            if path == "/healthz":
                self._send_json({"ok": True, "service": "bsl-monitor"})
                return
            if path.startswith("/api/"):
                self._send_error_json(404, "unknown endpoint")
                return
            self._serve_static(path)
        except Exception as exc:  # pragma: no cover
            logger.debug("monitor GET error: {}", exc)
            self._send_error_json(500, "internal server error")

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if path == "/api/clear":
                body = self._read_json_body()
                scope = str(body.get("scope", "all")).strip().lower()
                if scope not in _CLEAR_SCOPES:
                    self._send_error_json(400, f"invalid scope: {scope}")
                    return
                removed = device_health_hub.clear_entries(statuses=_CLEAR_SCOPES[scope])
                STATE.request_poll()
                self._send_json({"ok": True, "removed": int(removed)})
                return
            if path == "/api/email-config":
                self._save_email_config(self._read_json_body())
                self._send_json(self._email_config_payload())
                return
            if path == "/api/authorize":
                body = self._read_json_body()
                # client_secrets_file is intentionally NOT taken from the network
                # (see _save_email_config) — use the locally configured/default path.
                ok, msg = device_health_hub.authorize_google_workspace(
                    client_secrets_file=None,
                    sender_email=(body.get("sender_email") or "students@bsl-uiuc.com"),
                    recipient_email=(body.get("recipient_email") or ""),
                )
                self._send_json({"ok": bool(ok), "message": str(msg)})
                return
            if path == "/api/test-email":
                ok, msg = device_health_hub.send_test_email()
                self._send_json({"ok": bool(ok), "message": str(msg)})
                return
            self._send_error_json(404, "unknown endpoint")
        except ValueError as exc:
            self._send_error_json(400, f"bad request: {exc}")
        except Exception as exc:  # pragma: no cover
            logger.debug("monitor POST error: {}", exc)
            self._send_error_json(500, "internal server error")

    def _save_email_config(self, body: dict) -> None:
        # SECURITY: oauth_client_secrets_file / oauth_token_file are deliberately
        # NOT accepted from the (unauthenticated, LAN-exposed) network — a remote
        # client could otherwise redirect where the host writes its Google refresh
        # token (an arbitrary host-side file write). Passing None preserves the
        # locally-configured paths. Configure those via env / the config file.
        device_health_hub.set_email_config(
            enabled=bool(body.get("enabled", False)),
            recipient_email=str(body.get("recipient_email", "") or "").strip(),
            sender_email=str(body.get("sender_email", "") or "").strip() or "students@bsl-uiuc.com",
            provider="gmail",
            oauth_client_secrets_file=None,
            oauth_token_file=None,
            default_categories=_clean_categories(body.get("default_categories")),
            instrument_category_matrix=_clean_matrix(body.get("instrument_category_matrix")),
        )

    def _log_query_args(self, raw_query: str) -> dict:
        qs = parse_qs(raw_query or "")
        levels = None
        lv = qs.get("level", [])
        if lv:
            levels = [x.strip() for item in lv for x in item.split(",") if x.strip()]
        hours = _qfloat(qs, "hours", 0.0)
        return {
            "levels": levels,
            "q": qs.get("q", [""])[0],
            "module": qs.get("module", [""])[0],
            "since_ts": (time.time() - hours * 3600.0) if hours and hours > 0 else 0.0,
        }

    def _logs_payload(self, raw_query: str) -> dict:
        args = self._log_query_args(raw_query)
        qs = parse_qs(raw_query or "")
        return logreader.query(limit=int(_qfloat(qs, "limit", 500)), **args)

    def _send_logs_csv(self, raw_query: str) -> None:
        from datetime import datetime as _dt

        data = logreader.query(limit=5000, **self._log_query_args(raw_query))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["time", "level", "module", "function", "line", "pid", "message", "exception"])
        for r in data["records"]:
            iso = _dt.fromtimestamp(r["ts"], tz=timezone.utc).isoformat() if r["ts"] else ""
            writer.writerow([
                _csv_safe(iso), _csv_safe(r["level"]), _csv_safe(r["module"]), _csv_safe(r["function"]),
                _csv_safe(r["line"]), _csv_safe(r["pid"]), _csv_safe(r["message"]), _csv_safe(r["exception"] or ""),
            ])
        self._send_bytes(
            200, buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
            extra={"Content-Disposition": 'attachment; filename="bsl_logs.csv"'},
        )

    def _send_csv(self) -> None:
        with STATE._lock:
            devices = [dict(d) for d in STATE._latest]
        cols = ("key", "model", "device_type", "serial_number", "status", "updated_at", "process_id", "session_id", "last_error")
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(list(cols))
        for dev in devices:
            writer.writerow([_csv_safe(dev.get(c, "")) for c in cols])
        self._send_bytes(
            200,
            buf.getvalue().encode("utf-8"),
            "text/csv; charset=utf-8",
            extra={"Content-Disposition": 'attachment; filename="bsl_monitor_snapshot.csv"'},
        )


def _csv_safe(value: Any) -> str:
    """Neutralize spreadsheet formula injection (leading =,+,-,@,tab,CR)."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _clean_categories(value: Any) -> list[str]:
    supported = set(device_health_hub.get_supported_alert_categories())
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        cat = str(item).strip().upper()
        if cat in supported and cat not in out:
            out.append(cat)
    return out


def _clean_matrix(value: Any) -> dict[str, list[str]]:
    supported = set(device_health_hub.get_supported_alert_categories())
    out: dict[str, list[str]] = {}
    if not isinstance(value, dict):
        return out
    for raw_key, raw_cats in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        cats: list[str] = []
        if isinstance(raw_cats, (list, tuple)):
            for item in raw_cats:
                cat = str(item).strip().upper()
                if cat in supported and cat not in cats:
                    cats.append(cat)
        out[key] = cats
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Start the monitor server (blocking). Exits quietly if the port is taken.

    Parameters
    ----------
    host : str, optional
        Bind address, by default ``BSL_MONITOR_HOST`` or ``"0.0.0.0"``.
    port : int, optional
        Bind port, by default ``BSL_MONITOR_PORT`` or ``8787``.
    """
    host = host or DEFAULT_HOST
    port = int(port or DEFAULT_PORT)
    STATE.host, STATE.port = host, port
    STATE.start()

    try:
        httpd = ThreadingHTTPServer((host, port), MonitorRequestHandler)
    except OSError as exc:
        logger.info(
            "BSL monitor: {}:{} unavailable ({}); assuming another monitor is already running.",
            host,
            port,
            exc,
        )
        return

    httpd.daemon_threads = True
    info = _server_info(host, port)
    logger.success("BSL instrument monitor running — local {} · LAN {}", info["local_url"], info["lan_url"])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
