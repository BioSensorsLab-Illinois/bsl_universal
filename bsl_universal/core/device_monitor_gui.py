from __future__ import annotations

"""
Device monitor launcher.

The monitor is now a **web app** (stdlib HTTP + Server-Sent Events) served by
:mod:`bsl_universal.core._web_monitor`. This module keeps the historical public
entry points (`start_device_monitor_window`, `run_device_monitor_app`) so callers
and docs keep working; they now launch / run the web server instead of a Tkinter
window. The server is shared machine-wide (single instance per host:port), so
every bsl_universal process that constructs an instrument points the operator to
the same live page.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Optional

from loguru import logger

_MONITOR_PROCESS: Optional[subprocess.Popen] = None


def _port() -> int:
    """Resolve the monitor port (env ``BSL_MONITOR_PORT``, default 8787)."""
    try:
        return int(str(os.environ.get("BSL_MONITOR_PORT", "")).strip() or 8787)
    except ValueError:
        return 8787


def _is_server_running(port: int, *, timeout: float = 0.25) -> bool:
    """Return True if something is already listening on ``127.0.0.1:port``."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def start_device_monitor_window() -> bool:
    """Ensure the web-based device monitor server is running; open a browser once.

    Idempotent and safe to call from every process: if a monitor server is
    already listening on the configured port (this or another process started
    it), it does nothing and returns True. Otherwise it spawns a detached server
    subprocess and opens the local page in the default browser (unless
    ``BSL_MONITOR_NO_BROWSER`` is set).

    Returns
    -------
    bool
        True when a monitor server is running (already up or freshly launched).
    """
    global _MONITOR_PROCESS
    port = _port()

    if _is_server_running(port):
        return True
    if _MONITOR_PROCESS is not None and _MONITOR_PROCESS.poll() is None:
        return True

    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "posix":
            kwargs["start_new_session"] = True  # detach so the monitor outlives this process
        elif os.name == "nt":  # pragma: no cover
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        _MONITOR_PROCESS = subprocess.Popen(
            [sys.executable, "-m", "bsl_universal.core._web_monitor"],
            **kwargs,
        )
    except Exception as exc:
        logger.warning("Unable to launch device monitor server: {}", exc)
        return False

    # Wait for bind + open the browser off the caller's thread, so the first
    # instrument constructor (inst.py calls this) is never blocked on bootstrap.
    threading.Thread(target=_post_spawn, args=(port,), name="bsl-monitor-launch", daemon=True).start()
    logger.info("Device monitor starting at http://127.0.0.1:{}/", port)
    return True


def _post_spawn(port: int) -> None:
    """Wait for the server to bind, open a browser once, and reap a lost-race child."""
    global _MONITOR_PROCESS
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if _is_server_running(port):
            break
        time.sleep(0.1)

    # If our spawned child lost the single-instance bind race it has already
    # exited; poll() reaps it so it does not linger as a zombie.
    proc = _MONITOR_PROCESS
    if proc is not None and proc.poll() is not None:
        _MONITOR_PROCESS = None

    if not os.environ.get("BSL_MONITOR_NO_BROWSER"):
        try:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        except Exception as exc:  # pragma: no cover
            logger.debug("Could not open monitor in a browser: {}", exc)


# Backwards/forwards-compatible aliases.
start_device_monitor_web = start_device_monitor_window


def run_device_monitor_app() -> None:
    """Run the monitor web server in the current process (blocking).

    Used by ``python -m bsl_universal.core.device_monitor_gui`` and retained for
    backwards compatibility. New code should run
    ``python -m bsl_universal.core._web_monitor`` directly.
    """
    from ._web_monitor.server import serve

    serve()


if __name__ == "__main__":
    run_device_monitor_app()
