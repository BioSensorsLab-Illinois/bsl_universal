"""Web-based BSL instrument monitor (stdlib HTTP + SSE).

Run standalone with ``python -m bsl_universal.core._web_monitor``. The public
launcher lives in :mod:`bsl_universal.core.device_monitor_gui`
(``start_device_monitor_window``), which spawns this server in a subprocess.
"""

from .server import DEFAULT_HOST, DEFAULT_PORT, serve

__all__ = ["serve", "DEFAULT_HOST", "DEFAULT_PORT"]
