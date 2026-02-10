from __future__ import annotations

import atexit
import enum
import pickle
import socket
import time
from multiprocessing import shared_memory
from typing import Any, Callable, Dict, Optional, Tuple, Union

import numpy as np
from loguru import logger

from ..headers._bsl_type import _bsl_type as bsl_type

try:
    import dill
except Exception:  # pragma: no cover
    dill = pickle

try:
    import zmq
except Exception:  # pragma: no cover
    zmq = None

try:
    from MantisCam import Messenger as _ExternalMessenger
except Exception:  # pragma: no cover
    try:
        from mantiscam_gui import Messenger as _ExternalMessenger
    except Exception:  # pragma: no cover
        _ExternalMessenger = None


class _FallbackMessenger:
    """Minimal MantisCam messenger used when project messenger import is unavailable."""

    def __init__(
        self,
        ctx: "zmq.Context",
        pub: Optional[str],
        sub: Optional[str],
        category: str,
        topic: str,
    ) -> None:
        """
        Initialize fallback publish/subscribe sockets.

        Parameters
        ----------
        ctx : zmq.Context
            ZMQ context object.
        pub : str | None
            Publisher endpoint to connect, or None to disable publish socket.
        sub : str | None
            Subscriber endpoint to connect, or None to disable subscribe socket.
        category : str
            Message category prefix (for example ``"cmd"``).
        topic : str
            Default topic suffix.
        """
        if zmq is None:
            raise RuntimeError("pyzmq is required for MantisCam control")

        self.ctx = ctx
        self.category = category or "__default"
        self.default_topic = topic
        self.skt_pub = ctx.socket(zmq.PUB) if pub else None
        self.skt_sub = ctx.socket(zmq.SUB) if sub else None

        if self.skt_pub is not None:
            self.skt_pub.connect(pub)

        if self.skt_sub is not None:
            self.skt_sub.connect(sub)
            self.skt_sub.subscribe(f"{self.category}-{self.default_topic}".encode("utf-8"))

    def _encode(self, topic: str, name: Optional[str] = None) -> bytes:
        if name is None:
            return f"{self.category}-{topic}".encode("utf-8")
        return f"{self.category}-{topic}-{name}".encode("utf-8")

    @staticmethod
    def _decode(tag: bytes) -> Tuple[str, str]:
        parts = tag.decode("utf-8").split("-", 2)
        topic = parts[1] if len(parts) > 1 else ""
        name = parts[2] if len(parts) > 2 else ""
        return topic, name

    def send(self, name: str, obj: Any, *, topic: Optional[str] = None, subscribe: bool = True) -> None:
        """
        Send one message.

        Parameters
        ----------
        name : str
            Message name.
        obj : Any
            Message payload.
        topic : str | None, optional
            Topic override, by default None.
        subscribe : bool, optional
            Ignored; retained for compatibility.
        """
        del subscribe
        if self.skt_pub is None:
            raise AttributeError("Messenger has no publish socket")
        topic = self.default_topic if topic is None else topic
        tag = self._encode(topic, name)
        self.skt_pub.send_multipart([tag, dill.dumps(obj, protocol=dill.DEFAULT_PROTOCOL)])

    def recv(self) -> Tuple[str, str, Any]:
        """
        Receive one command payload.

        Returns
        -------
        tuple[str, str, Any]
            Topic, name, payload tuple.
        """
        if self.skt_sub is None:
            raise AttributeError("Messenger has no subscribe socket")
        tag, payload = self.skt_sub.recv_multipart()
        topic, name = self._decode(tag)
        return topic, name, dill.loads(payload)

    def recv_auto(self) -> Tuple[str, str, Any, Optional[bytes], bool]:
        """
        Receive one payload with optional frame dump.

        Returns
        -------
        tuple[str, str, Any, bytes | None, bool]
            Topic, name, message payload, frame dump bytes, and shared-memory flag.
        """
        if self.skt_sub is None:
            raise AttributeError("Messenger has no subscribe socket")
        parts = self.skt_sub.recv_multipart()
        topic, name = self._decode(parts[0])
        try:
            msg = dill.loads(parts[1])
        except Exception:
            msg = pickle.loads(parts[1])
        if len(parts) == 3:
            return topic, name, msg, parts[2], False
        return topic, name, msg, None, True

    def close(self) -> None:
        """
        Close fallback sockets.
        """
        if self.skt_sub is not None:
            self.skt_sub.close(linger=0)
            self.skt_sub = None
        if self.skt_pub is not None:
            self.skt_pub.close(linger=0)
            self.skt_pub = None


class MantisCamCtrl:
    """Stable MantisCam control client over ZMQ.

    Public API focuses on explicit camera operations without legacy wrappers.
    """

    TIMEOUT_SEC = 60.0
    _POLL_STEP_MS = 25
    _SEND_RETRIES = 3
    _MONITOR_CONNECTED_THROTTLE_SEC = 2.0
    _MONITOR_WARNING_THROTTLE_SEC = 3.0

    class FileNamingMode(enum.Enum):
        """Naming mode for recording file and folder naming."""

        CUSTOM = "Custom"
        TIMESTAMP = "Timestamp"

    def __init__(
        self,
        device_sn: str = "",
        port_cmd_pub: int = 60000,
        port_cmd_sub: int = 60001,
        port_vid_sub: int = 60011,
        *,
        log_level: str = "TRACE",
    ) -> None:
        """Initialize MantisCam client transport.

        Parameters
        ----------
        device_sn : str, optional
            Logical device label used for user-side tracking, by default ``""``.
        port_cmd_pub : int, optional
            Command publisher port, by default ``60000``.
        port_cmd_sub : int, optional
            Command subscriber port, by default ``60001``.
        port_vid_sub : int, optional
            Video subscriber port, by default ``60011``.
        log_level : str, optional
            Logging hint retained for constructor compatibility, by default ``"TRACE"``.

        Raises
        ------
        bsl_type.DeviceConnectionFailed
            Raised when ZMQ transport cannot be initialized.
        """
        del log_level
        if zmq is None:
            raise bsl_type.DeviceConnectionFailed("pyzmq is not installed")

        self.device_sn = device_sn
        self.device_id = device_sn or "Unknown"
        self._backend_host = "127.0.0.1"
        self._backend_cmd_ports = (int(port_cmd_pub), int(port_cmd_sub))

        url_prefix = "tcp://127.0.0.1:"
        self.url_cmd_pub = url_prefix + str(port_cmd_pub)
        self.url_cmd_sub = url_prefix + str(port_cmd_sub)
        self.url_vid_sub = url_prefix + str(port_vid_sub)

        self._ctx = None
        self.cmd = None
        self.vid = None
        self.poller = None
        self._closed = False
        self._atexit_registered = False

        self.is_recording = False
        self._target_exposure_ms = 50.0
        self.current_exposure_ms = 0.0

        self._last_received_exp_ms: Optional[float] = None
        self._last_raw_meta: Dict[str, Any] = {}
        self._last_isp_meta: Dict[str, Any] = {}
        self._observed_isp_frame_names: set[str] = set()
        self._camera_info: Dict[str, Any] = {}
        self._camera_type_info: Dict[str, Any] = {}
        self._camera_capabilities: Dict[str, Any] = {}
        self._hardware_nodes: Dict[str, Any] = {}
        self._monitor_on_connected: Optional[Callable[[str, str, str, str], None]] = None
        self._monitor_on_warning: Optional[Callable[[str, str, str, str], None]] = None
        self._monitor_on_disconnected: Optional[Callable[[str, str, str, str], None]] = None
        self._monitor_last_state = ""
        self._monitor_last_identity: Tuple[str, str, str] = ("mantisCam", "MantisCam", self.device_id)
        self._monitor_last_message = ""
        self._monitor_last_ts = 0.0

        logger.info("Initiating bsl_instrument - MantisCam({})...", device_sn)
        self._connect_or_raise()

        try:
            self.set_recording_file_name(time_stamp_only=True)
            self.set_exposure_time(50.0, strict=False)
        except Exception as exc:  # pragma: no cover
            logger.warning("Initial MantisCam sync command failed: {}", exc)

    def __enter__(self) -> "MantisCamCtrl":
        """Enter context manager.

        Returns
        -------
        MantisCamCtrl
            Active client object.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context manager and close sockets.

        Returns
        -------
        bool
            Always ``False`` to preserve exception propagation.
        """
        self.close()
        return False

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def close(self) -> None:
        """Close all sockets and terminate ZMQ context.

        Returns
        -------
        None
        """
        if self._closed:
            return
        self._closed = True

        try:
            if self.cmd is not None:
                self.cmd.close()
        except Exception:
            pass

        try:
            if self.vid is not None:
                self.vid.close()
        except Exception:
            pass

        try:
            if self._ctx is not None:
                self._ctx.term()
        except Exception:
            pass

        self.cmd = None
        self.vid = None
        self.poller = None
        self._ctx = None

    def set_monitor_callbacks(
        self,
        *,
        on_connected: Optional[Callable[[str, str, str, str], None]] = None,
        on_warning: Optional[Callable[[str, str, str, str], None]] = None,
        on_disconnected: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> None:
        """
        Register monitor callbacks used by the parent instrument runtime.

        Parameters
        ----------
        on_connected : Callable[[str, str, str, str], None] | None, optional
            Callback for connected/healthy state updates.
        on_warning : Callable[[str, str, str, str], None] | None, optional
            Callback for recoverable warning state updates.
        on_disconnected : Callable[[str, str, str, str], None] | None, optional
            Callback for disconnected/unreachable state updates.

        Returns
        -------
        None
        """
        self._monitor_on_connected = on_connected
        self._monitor_on_warning = on_warning
        self._monitor_on_disconnected = on_disconnected

    def _monitor_identity(self) -> Tuple[str, str, str]:
        """
        Build monitor-facing identity tuple for current camera state.

        Returns
        -------
        tuple[str, str, str]
            ``(model, device_type, serial_number)`` tuple.
        """
        info = self.get_camera_identity(refresh=False)
        model = str(
            info.get("nickname")
            or info.get("display_name")
            or info.get("model")
            or info.get("model-name")
            or self._monitor_last_identity[0]
            or "mantisCam"
        ).strip()
        serial = str(
            info.get("serial")
            or info.get("serial-number")
            or self.device_id
            or self.device_sn
            or self._monitor_last_identity[2]
            or "Unknown"
        ).strip()
        camera_type = str(
            info.get("camera_type")
            or self._camera_type_info.get("camera_type_str")
            or self._camera_type_info.get("camera_type")
            or ""
        ).strip()
        device_type = f"MantisCam/{camera_type}" if camera_type else "MantisCam"
        if serial:
            self.device_id = serial
        return (model or "mantisCam", device_type, serial or "Unknown")

    @staticmethod
    def _same_text(a: str, b: str) -> bool:
        return str(a or "").strip() == str(b or "").strip()

    def _publish_monitor_state(
        self,
        *,
        state: str,
        detail: str = "",
        force: bool = False,
    ) -> None:
        """
        Publish monitor state through registered callbacks with throttling.

        Parameters
        ----------
        state : str
            One of ``"CONNECTED"``, ``"WARNING"``, ``"DISCONNECTED"``.
        detail : str, optional
            Optional detail text.
        force : bool, optional
            Bypass dedupe throttling when True.

        Returns
        -------
        None
        """
        model, device_type, serial = self._monitor_identity()
        identity = (model, device_type, serial)
        now = time.monotonic()

        throttle_sec = self._MONITOR_CONNECTED_THROTTLE_SEC if state == "CONNECTED" else self._MONITOR_WARNING_THROTTLE_SEC
        if (
            not force
            and state == self._monitor_last_state
            and identity == self._monitor_last_identity
            and self._same_text(detail, self._monitor_last_message)
            and (now - self._monitor_last_ts) < throttle_sec
        ):
            return

        callback = None
        if state == "CONNECTED":
            callback = self._monitor_on_connected
        elif state == "WARNING":
            callback = self._monitor_on_warning
        elif state == "DISCONNECTED":
            callback = self._monitor_on_disconnected

        if callback is not None:
            try:
                callback(model, device_type, serial, detail)
            except Exception:
                pass

        self._monitor_last_state = state
        self._monitor_last_identity = identity
        self._monitor_last_message = str(detail or "")
        self._monitor_last_ts = now

    def _monitor_connected(self, detail: str = "", *, force: bool = False) -> None:
        self._publish_monitor_state(state="CONNECTED", detail=detail, force=force)

    def _monitor_warning(self, detail: str) -> None:
        self._publish_monitor_state(state="WARNING", detail=detail, force=False)

    def _monitor_disconnected(self, detail: str, *, force: bool = False) -> None:
        self._publish_monitor_state(state="DISCONNECTED", detail=detail, force=force)

    def _is_backend_reachable(self, *, timeout_sec: float = 0.2) -> bool:
        """
        Check whether MantisCamUnified command ports are reachable.

        Parameters
        ----------
        timeout_sec : float, optional
            TCP connect timeout, by default ``0.2``.

        Returns
        -------
        bool
            True when all command ports are reachable.
        """
        for port in self._backend_cmd_ports:
            try:
                with socket.create_connection((self._backend_host, int(port)), timeout=timeout_sec):
                    pass
            except Exception:
                return False
        return True

    def _handle_link_issue(self, detail: str, *, allow_recover: bool = True) -> None:
        """
        Handle camera-link degradation with warning/disconnect/recovery actions.

        Parameters
        ----------
        detail : str
            Human-readable issue description.
        allow_recover : bool, optional
            Attempt transport recovery when True, by default True.

        Returns
        -------
        None
        """
        clean = str(detail or "MantisCam link issue").strip()
        self._monitor_warning(clean)

        if not self._is_backend_reachable():
            self._monitor_disconnected(f"{clean}. MantisCamUnified backend unreachable.")
            return

        if not allow_recover:
            return

        try:
            self._recover_transport()
            self._monitor_connected(f"{clean}. Transport recovered.", force=True)
        except Exception as exc:
            self._monitor_disconnected(f"{clean}. Transport recovery failed: {exc}", force=True)

    # ---------------------------------------------------------------------
    # Transport and protocol internals
    # ---------------------------------------------------------------------

    def _connect_or_raise(self) -> None:
        """Initialize command/video sockets and poller.

        Raises
        ------
        bsl_type.DeviceConnectionFailed
            Raised when socket initialization fails.
        """
        messenger_cls = _ExternalMessenger or _FallbackMessenger
        try:
            self._ctx = zmq.Context()
            self.cmd = messenger_cls(self._ctx, self.url_cmd_pub, self.url_cmd_sub, "cmd", "")
            self.vid = messenger_cls(self._ctx, None, self.url_vid_sub, "vid", "")
            self.poller = zmq.Poller()
            self.poller.register(self.cmd.skt_sub, zmq.POLLIN)
            self.poller.register(self.vid.skt_sub, zmq.POLLIN)
            if not self._atexit_registered:
                atexit.register(self.close)
                self._atexit_registered = True
            time.sleep(0.1)
            logger.success(
                "MantisCam transport connected (cmd pub={}, cmd sub={}, vid sub={}).",
                self.url_cmd_pub,
                self.url_cmd_sub,
                self.url_vid_sub,
            )
        except Exception as exc:
            self.close()
            raise bsl_type.DeviceConnectionFailed(f"Unable to initialize MantisCam transport: {exc}")

    def _recover_transport(self) -> None:
        logger.warning("Recovering MantisCam transport sockets...")
        self.close()
        self._closed = False
        self._connect_or_raise()

    def _reset_video_socket(self) -> None:
        """Reset video subscriber socket only.

        Returns
        -------
        None
        """
        if self._closed:
            return

        messenger_cls = _ExternalMessenger or _FallbackMessenger
        try:
            if self.vid is not None:
                self.poller.unregister(self.vid.skt_sub)
                self.vid.close()
        except Exception:
            pass

        self.vid = messenger_cls(self._ctx, None, self.url_vid_sub, "vid", "")
        self.poller.register(self.vid.skt_sub, zmq.POLLIN)

    def _safe_send(self, topic: str, name: str, payload: Dict[str, Any]) -> None:
        """Send a command with retry and transport recovery.

        Parameters
        ----------
        topic : str
            Command topic.
        name : str
            Command name.
        payload : dict
            Command payload.

        Raises
        ------
        bsl_type.DeviceOperationError
            Raised when all send retries fail.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self._SEND_RETRIES):
            try:
                self.cmd.send(name, payload, topic=topic)
                return
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                logger.warning(
                    "Send failure {}:{} attempt {}/{}: {}",
                    topic,
                    name,
                    attempt + 1,
                    self._SEND_RETRIES,
                    exc,
                )
                self._monitor_warning(f"Command send failure {topic}:{name}: {exc}")
                try:
                    self._recover_transport()
                    self._monitor_connected(f"Recovered after send failure {topic}:{name}.", force=True)
                except Exception as recover_exc:
                    last_exc = recover_exc
                    self._monitor_disconnected(
                        f"Command send failure {topic}:{name}. Transport recovery failed: {recover_exc}",
                        force=True,
                    )
                time.sleep(0.05)

        self._handle_link_issue(f"Command send failed for {topic}:{name}", allow_recover=False)
        raise bsl_type.DeviceOperationError(f"Failed to send {topic}:{name}: {last_exc}")

    def _poll(self, timeout_ms: int) -> Dict[Any, Any]:
        if self.poller is None:
            return {}
        try:
            return dict(self.poller.poll(timeout=timeout_ms))
        except Exception:  # pragma: no cover
            self._handle_link_issue("Poll failure", allow_recover=True)
            return {}

    def _update_exposure_from_meta(self, msg: Dict[str, Any]) -> None:
        frame_meta = msg.get("frame_meta")
        if not isinstance(frame_meta, dict):
            return
        value = frame_meta.get("int-set")
        try:
            if value is not None:
                self._last_received_exp_ms = float(value)
        except Exception:
            pass

    def _consume_cmd(self, sockets: Dict[Any, Any]) -> None:
        if self.cmd is None or self.cmd.skt_sub not in sockets:
            return
        try:
            topic, name, msg = self.cmd.recv()
        except Exception:  # pragma: no cover
            self._handle_link_issue("Command receive failure", allow_recover=True)
            return

        if topic == "file" and name == "recording_status":
            self.is_recording = bool(msg.get("recording", False))
            self._monitor_connected()
            return

        if topic == "widget" and name == "camera_info" and isinstance(msg, dict):
            self._camera_info = dict(msg)
            serial = str(msg.get("serial", "")).strip()
            if serial:
                self.device_id = serial
            self._monitor_connected(force=True)
            return

        if topic == "widget" and name == "camera_capabilities" and isinstance(msg, dict):
            self._camera_capabilities = dict(msg)
            self._monitor_connected()
            return

        if topic == "widget" and name == "hardware_nodes" and isinstance(msg, dict):
            self._hardware_nodes = dict(msg)
            camera_payload = msg.get("camera", {})
            if isinstance(camera_payload, dict):
                self._camera_info.update(camera_payload)
            self._monitor_connected(force=True)
            return

        if topic == "isp" and name == "camera_type" and isinstance(msg, dict):
            self._camera_type_info = dict(msg)
            if msg.get("camera_type_str"):
                self._camera_info["camera_type"] = str(msg.get("camera_type_str"))
            self._monitor_connected(force=True)
            return

    def _consume_vid(self, sockets: Dict[Any, Any]) -> None:
        if self.vid is None or self.vid.skt_sub not in sockets:
            return
        try:
            topic, _name, msg, _frame_dump, _is_ref = self.vid.recv_auto()
        except Exception:  # pragma: no cover
            self._handle_link_issue("Video receive failure", allow_recover=True)
            return

        if not isinstance(msg, dict):
            return

        self._update_exposure_from_meta(msg)
        frame_name = str(msg.get("frame_name", ""))
        if topic == "raw" or frame_name == "Raw":
            self._last_raw_meta = dict(msg)
        else:
            self._last_isp_meta = dict(msg)
            if frame_name:
                self._observed_isp_frame_names.add(frame_name)
        self._monitor_connected()

    def _drain_nonblocking(self, max_iter: int = 64) -> None:
        for _ in range(max_iter):
            sockets = self._poll(0)
            if not sockets:
                break
            self._consume_cmd(sockets)
            self._consume_vid(sockets)

    @staticmethod
    def _decode_frame(msg: Dict[str, Any], frame_dump: Optional[bytes], is_ref: bool) -> Optional[np.ndarray]:
        if is_ref and "_shm_ref" in msg:
            ref = msg["_shm_ref"]
            try:
                shm = shared_memory.SharedMemory(name=ref["name"])
            except FileNotFoundError:
                return None
            try:
                arr = np.ndarray(tuple(ref["shape"]), dtype=np.dtype(ref["dtype"]), buffer=shm.buf)
                return np.array(arr, copy=True)
            finally:
                shm.close()

        if frame_dump is None:
            return None
        try:
            return dill.loads(frame_dump)
        except Exception:
            try:
                return pickle.loads(frame_dump)
            except Exception:
                return None

    def _wait_for_frame(
        self,
        *,
        require_raw: Optional[bool],
        frame_name: Optional[str],
        timeout_ms: int,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        deadline = time.monotonic() + timeout_ms / 1000.0
        frame_name = None if frame_name is None else str(frame_name)

        while time.monotonic() < deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)

            if self.vid is None or self.vid.skt_sub not in sockets:
                continue

            try:
                topic, _name, msg, frame_dump, is_ref = self.vid.recv_auto()
            except Exception:  # pragma: no cover
                self._handle_link_issue("Frame receive failure", allow_recover=True)
                continue

            if not isinstance(msg, dict):
                continue

            self._update_exposure_from_meta(msg)
            current_name = str(msg.get("frame_name", ""))
            is_raw = topic == "raw" or current_name == "Raw"

            if require_raw is True and not is_raw:
                continue
            if require_raw is False and is_raw:
                continue
            if frame_name is not None and current_name != frame_name:
                continue

            frame = self._decode_frame(msg, frame_dump, is_ref)
            if frame is None:
                continue

            if is_raw:
                self._last_raw_meta = dict(msg)
            else:
                self._last_isp_meta = dict(msg)
                if current_name:
                    self._observed_isp_frame_names.add(current_name)
            self._monitor_connected()
            return frame, dict(msg)

        self._handle_link_issue("Frame acquisition timeout", allow_recover=True)
        raise bsl_type.DeviceTimeOutError

    @staticmethod
    def _exposure_matches(requested_ms: float, measured_ms: float) -> bool:
        tol = max(abs(requested_ms) * 0.01, 0.1)
        return abs(requested_ms - measured_ms) <= tol

    @staticmethod
    def _as_numeric(value: Any) -> Union[float, np.ndarray]:
        if isinstance(value, (list, tuple, np.ndarray)):
            return np.asarray(value)
        return float(value)

    def _camera_type_token(self) -> str:
        """
        Build a normalized token string used for camera-type inference.

        Returns
        -------
        str
            Lower-case token string containing camera type and identity hints.
        """
        parts = []
        for source in (self._camera_type_info, self._camera_info):
            if not isinstance(source, dict):
                continue
            for key in ("camera_type", "camera_type_str", "sensor", "model", "display_name"):
                value = source.get(key)
                if value:
                    parts.append(str(value))
        return " ".join(parts).strip().lower()

    def _is_gsense_camera(self) -> bool:
        """
        Determine whether the connected camera is a GSense family device.

        Returns
        -------
        bool
            True when camera metadata indicates GSense.
        """
        token = self._camera_type_token()
        return any(keyword in token for keyword in ("gsense", "g-sense", "gsense2020"))

    # ---------------------------------------------------------------------
    # Camera information and node catalog
    # ---------------------------------------------------------------------

    def get_camera_identity(self, *, refresh: bool = True) -> Dict[str, Any]:
        """Get camera identity details (model, serial, vendor).

        Parameters
        ----------
        refresh : bool, optional
            If True, request fresh hardware node payload first, by default True.

        Returns
        -------
        dict
            Identity dictionary.
        """
        if refresh:
            self.refresh_hardware_nodes(timeout_ms=1500)
            self._drain_nonblocking()

        if self._camera_info:
            info = dict(self._camera_info)
            if self._camera_type_info.get("camera_type_str"):
                info.setdefault("camera_type", self._camera_type_info["camera_type_str"])
            return info

        dev_attr = self._last_raw_meta.get("dev_attr")
        if isinstance(dev_attr, dict):
            serial = dev_attr.get("serial-number", dev_attr.get("sn-camera", "Unknown"))
            return {
                "model": dev_attr.get("model-name", "Unknown"),
                "serial": serial,
                "vendor": dev_attr.get("vendor", dev_attr.get("vendor-name", "Unknown")),
                "firmware": dev_attr.get("fw-version", dev_attr.get("firmware-version", "Unknown")),
                "sensor": dev_attr.get("sensor-desc", dev_attr.get("sensor-description", "Unknown")),
                "nickname": dev_attr.get("nickname", ""),
                "camera_type": self._camera_type_info.get("camera_type_str", ""),
                "display_name": dev_attr.get("nickname", "") or dev_attr.get("model-name", "Unknown"),
            }

        return {}

    def get_camera_name_serial(self, *, refresh: bool = True) -> Tuple[str, str]:
        """Get camera model name and serial number.

        Parameters
        ----------
        refresh : bool, optional
            Refresh identity data first when True, by default True.

        Returns
        -------
        tuple[str, str]
            ``(model_name, serial_number)``.
        """
        info = self.get_camera_identity(refresh=refresh)
        model = str(
            info.get("nickname")
            or info.get("display_name")
            or info.get("model")
            or info.get("model-name")
            or "Unknown"
        )
        serial = str(info.get("serial", info.get("serial-number", "Unknown")))
        if serial and serial != "Unknown":
            self.device_id = serial
        return (model, serial)

    def get_camera_type(self, *, refresh: bool = True) -> str:
        """Get camera type string reported by the camera process.

        Parameters
        ----------
        refresh : bool, optional
            Refresh identity data first when True, by default True.

        Returns
        -------
        str
            Camera type string such as ``"GSense2020-BSI"`` or ``"F13-Full"``.
            Returns ``"Unknown"`` when unavailable.
        """
        info = self.get_camera_identity(refresh=refresh)
        camera_type = (
            info.get("camera_type")
            or self._camera_type_info.get("camera_type_str")
            or self._camera_type_info.get("camera_type")
            or ""
        )
        camera_type = str(camera_type).strip()
        return camera_type if camera_type else "Unknown"

    def refresh_hardware_nodes(self, *, timeout_ms: int = 1500) -> Dict[str, Any]:
        """Request hardware node catalog from camera process.

        Parameters
        ----------
        timeout_ms : int, optional
            Wait timeout in milliseconds, by default ``1500``.

        Returns
        -------
        dict
            Node catalog payload.
        """
        self._safe_send("cam", "query-hardware-nodes", {"request": True})
        deadline = time.monotonic() + timeout_ms / 1000.0

        while time.monotonic() < deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)
            self._consume_vid(sockets)
            if self._hardware_nodes:
                self._monitor_connected()
                return dict(self._hardware_nodes)

        self._handle_link_issue("Hardware node query timeout", allow_recover=True)
        if not self._hardware_nodes:
            self._hardware_nodes = self._fallback_hardware_nodes()
        return dict(self._hardware_nodes)

    def get_hardware_nodes(self, *, refresh: bool = False) -> Dict[str, Any]:
        """Get hardware node catalog.

        Parameters
        ----------
        refresh : bool, optional
            Request a fresh catalog from camera process, by default False.

        Returns
        -------
        dict
            Node catalog.
        """
        if refresh or not self._hardware_nodes:
            return self.refresh_hardware_nodes()
        return dict(self._hardware_nodes)

    def set_hardware_node(self, node_name: str, value: Any = None) -> None:
        """Set a hardware node value by catalog name.

        Parameters
        ----------
        node_name : str
            Node name from node catalog.
        value : Any, optional
            Target value. For action nodes this may be omitted.

        Raises
        ------
        bsl_type.DeviceOperationError
            Raised when the node is not writable or not found.
        """
        catalog = self.get_hardware_nodes(refresh=False)
        nodes = catalog.get("nodes", []) if isinstance(catalog, dict) else []

        target: Optional[Dict[str, Any]] = None
        for node in nodes:
            if str(node.get("name")) == str(node_name):
                target = node
                break

        if target is None:
            raise bsl_type.DeviceOperationError(f"Unknown node: {node_name}")

        command = target.get("command")
        payload_key = target.get("payload_key")
        if not command or not payload_key:
            raise bsl_type.DeviceOperationError(f"Node is not writable: {node_name}")

        if str(target.get("value_type", "")).lower() == "action":
            self._safe_send("cam", command, {str(payload_key): True if value is None else value})
            return

        if command in {"spi", "dac", "dly"}:
            grouped: Dict[str, Any] = {}
            for node in nodes:
                if node.get("command") == command and node.get("payload_key"):
                    grouped[str(node["payload_key"])] = node.get("value")
            grouped[str(payload_key)] = value
            self._safe_send("cam", command, grouped)
            return

        self._safe_send("cam", command, {str(payload_key): value})

    def _fallback_hardware_nodes(self) -> Dict[str, Any]:
        info = self.get_camera_identity(refresh=False)
        caps = dict(self._camera_capabilities)

        nodes = [
            {
                "name": "exp-00",
                "display_name": "Exposure Time",
                "command": "exp-00",
                "payload_key": "exp-00",
                "value": self.current_exposure_ms or self._target_exposure_ms,
                "value_type": "float",
                "unit": "ms",
                "readable": True,
                "writable": True,
            },
            {
                "name": "acq-fps",
                "display_name": "Acquisition FPS",
                "command": "acq-fps",
                "payload_key": "acq-fps",
                "value_type": "int",
                "readable": True,
                "writable": True,
            },
        ]

        if caps.get("has_high_gain", False):
            nodes.append(
                {
                    "name": "high-gain",
                    "display_name": "High Gain",
                    "command": "high-gain",
                    "payload_key": "high-gain",
                    "value_type": "bool",
                    "readable": True,
                    "writable": True,
                }
            )

        if caps.get("has_adc_gain", False):
            nodes.append(
                {
                    "name": "adc-gain",
                    "display_name": "ADC Gain",
                    "command": "adc-gain",
                    "payload_key": "adc-gain",
                    "value_type": "int",
                    "readable": True,
                    "writable": True,
                }
            )

        if caps.get("has_tec", False):
            nodes.extend(
                [
                    {
                        "name": "coolingtemp-setpoint",
                        "display_name": "Cooling Setpoint",
                        "command": "coolingtemp-setpoint",
                        "payload_key": "coolingtemp-setpoint",
                        "value_type": "float",
                        "unit": "C",
                        "readable": True,
                        "writable": True,
                    },
                    {
                        "name": "tempcontrol-mode",
                        "display_name": "Cooling Control Mode",
                        "command": "tempcontrol-mode",
                        "payload_key": "tempcontrol-mode",
                        "value_type": "str",
                        "readable": True,
                        "writable": True,
                    },
                ]
            )

        return {
            "schema": "mantiscam.hardware.nodes.v2",
            "camera": info,
            "nodes": nodes,
        }

    # ---------------------------------------------------------------------
    # Recording and file controls
    # ---------------------------------------------------------------------

    def set_save_directory(self, save_dir: str) -> None:
        """Set root save directory for recording outputs.

        Parameters
        ----------
        save_dir : str
            Absolute path to recording root directory.
        """
        self._safe_send("file", "save_dir", {"save_dir": str(save_dir)})

    def set_recording_file_name(self, file_name: str = "video", *, time_stamp_only: bool = False) -> None:
        """Set recording filename mode and value.

        Parameters
        ----------
        file_name : str, optional
            Custom file-name template used in custom mode, by default ``"video"``.
        time_stamp_only : bool, optional
            Use timestamp-only naming mode when True, by default False.
        """
        if time_stamp_only:
            self._safe_send("file", "file_name", {"mode": self.FileNamingMode.TIMESTAMP.value})
            return

        self._safe_send(
            "file",
            "file_name",
            {"mode": self.FileNamingMode.CUSTOM.value, "name": str(file_name)},
        )

    def set_recording_folder(
        self,
        folder_name: str = "video",
        *,
        create_new_folder: bool = True,
        time_stamp_only: bool = False,
    ) -> None:
        """Set recording folder mode and value.

        Parameters
        ----------
        folder_name : str, optional
            Custom folder template used in custom mode, by default ``"video"``.
        create_new_folder : bool, optional
            Create per-recording folder when True, by default True.
        time_stamp_only : bool, optional
            Use timestamp-only folder naming mode, by default False.
        """
        if not create_new_folder:
            self._safe_send("file", "folder_name", {"mode": "Do Not Create New Folder"})
            return

        if time_stamp_only:
            self._safe_send("file", "folder_name", {"mode": "Timestamp"})
            return

        self._safe_send("file", "folder_name", {"mode": "Custom", "name": str(folder_name)})

    def start_recording(
        self,
        *,
        mode: str = "n_frames",
        n_frames: int = 10,
        wait_until_done: bool = True,
        frames_per_file: Optional[int] = None,
        strict: bool = True,
    ) -> bool:
        """Start camera recording.

        Parameters
        ----------
        mode : str, optional
            Recording mode: ``"n_frames"`` or ``"until_stop"``, by default ``"n_frames"``.
        n_frames : int, optional
            Target frame count for ``"n_frames"`` mode, by default ``10``.
        wait_until_done : bool, optional
            Block until complete for ``"n_frames"`` mode when True, by default True.
        frames_per_file : int, optional
            Frames per file for ``"until_stop"`` mode. If None, defaults to ``1000``.
        strict : bool, optional
            Raise timeout exception on failures when True, by default True.

        Returns
        -------
        bool
            True when start sequence succeeded.

        Raises
        ------
        ValueError
            Raised when an unsupported mode is provided.
        bsl_type.DeviceTimeOutError
            Raised when strict mode is enabled and timeouts occur.
        """
        mode = str(mode).strip().lower()
        if mode not in {"n_frames", "until_stop"}:
            raise ValueError(f"Unsupported recording mode: {mode}")

        if mode == "n_frames":
            frame_budget = max(1, int(n_frames))
            stop_condition = "File Full"
        else:
            frame_budget = max(1, int(frames_per_file or 1000))
            stop_condition = "Click Stop Recording"

        self._safe_send("file", "frames_per_file", {"frames_per_file": frame_budget})
        self._safe_send("file", "stop_condition", {"stop_condition": stop_condition})
        self._safe_send("file", "record", {"record": True})

        start_deadline = time.monotonic() + 5.0
        while time.monotonic() < start_deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)
            if self.is_recording:
                self._monitor_connected()
                break
        else:
            self._handle_link_issue("Start recording timeout", allow_recover=True)
            if strict:
                raise bsl_type.DeviceTimeOutError
            return False

        if not wait_until_done or mode != "n_frames":
            return True

        timeout_sec = max(20.0, (self._target_exposure_ms * frame_budget) / 500.0 + 20.0)
        done_deadline = time.monotonic() + timeout_sec
        while time.monotonic() < done_deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)
            if not self.is_recording:
                self._monitor_connected()
                return True

        self._handle_link_issue("Recording completion timeout", allow_recover=True)
        if strict:
            raise bsl_type.DeviceTimeOutError
        return False

    def stop_recording(self, *, timeout_sec: float = 15.0, strict: bool = True) -> bool:
        """Stop camera recording.

        Parameters
        ----------
        timeout_sec : float, optional
            Timeout for recording stop acknowledgment, by default ``15.0``.
        strict : bool, optional
            Raise timeout on failure when True, by default True.

        Returns
        -------
        bool
            True when recording stop is acknowledged.

        Raises
        ------
        bsl_type.DeviceTimeOutError
            Raised when strict mode is enabled and stop acknowledgement times out.
        """
        self._safe_send("file", "record", {"record": False})

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)
            if not self.is_recording:
                self._monitor_connected()
                return True

        self._handle_link_issue("Stop recording timeout", allow_recover=True)
        if strict:
            raise bsl_type.DeviceTimeOutError
        return False

    # ---------------------------------------------------------------------
    # Exposure and frame operations
    # ---------------------------------------------------------------------

    def set_exposure_time(self, exposure_ms: float, *, strict: bool = True, timeout_ms: int = 8000) -> bool:
        """Set camera exposure time in milliseconds.

        Exposure validation behavior:

        - GSense cameras use safeguard timing (metadata not trusted).
        - Other cameras verify readback from frame metadata.
        - Readback is accepted when error is within max(``1%``, ``0.1 ms``).

        Parameters
        ----------
        exposure_ms : float
            Requested exposure in milliseconds.
        strict : bool, optional
            Raise timeout on verification failure when True, by default True.
        timeout_ms : int, optional
            Verification timeout in milliseconds, by default ``8000``.

        Returns
        -------
        bool
            True when exposure set/verification succeeded.

        Raises
        ------
        bsl_type.DeviceTimeOutError
            Raised when strict mode is enabled and verification fails.
        """
        target = float(exposure_ms)
        self._target_exposure_ms = target
        self._drain_nonblocking()
        gsense_mode = self._is_gsense_camera()
        if not gsense_mode:
            try:
                self.refresh_hardware_nodes(timeout_ms=500)
                self._drain_nonblocking()
            except Exception:
                pass
            gsense_mode = self._is_gsense_camera()

        for _ in range(2):
            self._safe_send("cam", "exp-00", {"exp-00": target})
            self._safe_send("widget", "exp-00", {"exp-00": target})

            if gsense_mode:
                guard_delay = min(max(target / 1000.0, 0.02) * 2.0 + 0.25, 3.0)
                time.sleep(guard_delay)
                self.current_exposure_ms = target
                self._monitor_connected()
                return True

            deadline = time.monotonic() + timeout_ms / 1000.0
            while time.monotonic() < deadline:
                sockets = self._poll(self._POLL_STEP_MS)
                self._consume_cmd(sockets)
                self._consume_vid(sockets)

                if self._last_received_exp_ms is None:
                    continue

                if self._exposure_matches(target, self._last_received_exp_ms):
                    self.current_exposure_ms = target
                    self._monitor_connected()
                    return True

        self.current_exposure_ms = target
        self._handle_link_issue("Exposure verification timeout", allow_recover=True)
        if strict:
            raise bsl_type.DeviceTimeOutError
        return False

    def get_raw_frame(
        self,
        *,
        timeout_ms: int = 5000,
        fresh: bool = True,
        with_metadata: bool = False,
    ) -> Union[np.ndarray, Tuple[np.ndarray, Dict[str, Any]]]:
        """Get one raw frame snapshot.

        Parameters
        ----------
        timeout_ms : int, optional
            Timeout in milliseconds, by default ``5000``.
        fresh : bool, optional
            Reset local video socket to avoid stale buffered frame, by default True.
        with_metadata : bool, optional
            Return tuple ``(frame, metadata)`` when True, by default False.

        Returns
        -------
        numpy.ndarray or tuple
            Raw frame copy, with optional metadata.

        Raises
        ------
        bsl_type.DeviceTimeOutError
            Raised when no frame is received before timeout.
        """
        if fresh:
            self._reset_video_socket()
        frame, meta = self._wait_for_frame(require_raw=True, frame_name=None, timeout_ms=timeout_ms)
        return (frame, meta) if with_metadata else frame

    def get_isp_frame(
        self,
        frame_name: Optional[str] = None,
        *,
        timeout_ms: int = 5000,
        fresh: bool = True,
        with_metadata: bool = False,
    ) -> Union[np.ndarray, Tuple[np.ndarray, Dict[str, Any]]]:
        """Get one ISP frame snapshot.

        Parameters
        ----------
        frame_name : str, optional
            Specific ISP frame name (e.g. ``"High Gain"``, ``"RGB"``). If None,
            first available ISP frame is returned.
        timeout_ms : int, optional
            Timeout in milliseconds, by default ``5000``.
        fresh : bool, optional
            Reset local video socket to avoid stale buffered frame, by default True.
        with_metadata : bool, optional
            Return tuple ``(frame, metadata)`` when True, by default False.

        Returns
        -------
        numpy.ndarray or tuple
            ISP frame copy, with optional metadata.

        Raises
        ------
        bsl_type.DeviceTimeOutError
            Raised when no frame is received before timeout.
        """
        if fresh:
            self._reset_video_socket()
        frame, meta = self._wait_for_frame(require_raw=False, frame_name=frame_name, timeout_ms=timeout_ms)
        return (frame, meta) if with_metadata else frame

    def get_isp_frame_names(
        self,
        *,
        timeout_ms: int = 1500,
        fresh: bool = False,
        settle_ms: int = 200,
    ) -> list[str]:
        """Get currently available ISP frame names from the live video stream.

        Parameters
        ----------
        timeout_ms : int, optional
            Maximum observation window in milliseconds, by default ``1500``.
        fresh : bool, optional
            Reset local video socket before sampling when True, by default False.
            Keep this ``False`` for minimal transport disturbance.
        settle_ms : int, optional
            Early-stop window in milliseconds after the most recent new frame-name
            observation, by default ``200``.

        Returns
        -------
        list[str]
            Sorted unique ISP frame names observed from the active pipeline.
            The list may be empty if no ISP frame arrived within ``timeout_ms``.
        """
        if fresh:
            self._reset_video_socket()

        # Start with names observed earlier in this runtime.
        names = set(self._observed_isp_frame_names)
        last_meta_name = str(self._last_isp_meta.get("frame_name", "")).strip()
        if last_meta_name and last_meta_name != "Raw":
            names.add(last_meta_name)

        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        settle_sec = max(0, int(settle_ms)) / 1000.0
        last_new_name_at = time.monotonic()

        while time.monotonic() < deadline:
            sockets = self._poll(self._POLL_STEP_MS)
            self._consume_cmd(sockets)

            if self.vid is None or self.vid.skt_sub not in sockets:
                if names and (time.monotonic() - last_new_name_at) >= settle_sec:
                    break
                continue

            try:
                topic, _name, msg, _frame_dump, _is_ref = self.vid.recv_auto()
            except Exception:  # pragma: no cover
                self._handle_link_issue("ISP frame-name receive failure", allow_recover=True)
                continue

            if not isinstance(msg, dict):
                continue

            self._update_exposure_from_meta(msg)
            current_name = str(msg.get("frame_name", "")).strip()
            is_raw = topic == "raw" or current_name == "Raw"

            if is_raw:
                self._last_raw_meta = dict(msg)
            else:
                self._last_isp_meta = dict(msg)
                if current_name:
                    prev_len = len(names)
                    names.add(current_name)
                    self._observed_isp_frame_names.add(current_name)
                    if len(names) != prev_len:
                        last_new_name_at = time.monotonic()

            if names and (time.monotonic() - last_new_name_at) >= settle_sec:
                break

        if names:
            self._monitor_connected()
        else:
            self._handle_link_issue("No ISP frame names observed", allow_recover=False)
        return sorted(names)

    def get_frame_mean(
        self,
        frame_name: str,
        *,
        sub_frame_type: str = "",
        timeout_ms: int = 5000,
    ) -> Union[float, np.ndarray]:
        """Get frame mean value from ISP statistics.

        Parameters
        ----------
        frame_name : str
            Target ISP frame name.
        sub_frame_type : str, optional
            Optional sub-channel suffix (e.g. ``"red"``), by default ``""``.
        timeout_ms : int, optional
            Timeout in milliseconds, by default ``5000``.

        Returns
        -------
        float or numpy.ndarray
            Mean value from metadata statistics or computed from frame pixels.

        Raises
        ------
        bsl_type.DeviceTimeOutError
            Raised when frame retrieval times out.
        """
        frame, meta = self.get_isp_frame(
            frame_name=frame_name,
            timeout_ms=timeout_ms,
            fresh=True,
            with_metadata=True,
        )

        stats = meta.get("statistics", {}) if isinstance(meta, dict) else {}
        if isinstance(stats, dict):
            if sub_frame_type:
                key = f"frame-mean-{sub_frame_type}"
                if key in stats:
                    return self._as_numeric(stats[key])
            if "frame-mean" in stats:
                return self._as_numeric(stats["frame-mean"])

        if frame.ndim == 3 and frame.shape[-1] > 1:
            return np.mean(frame.reshape(-1, frame.shape[-1]), axis=0)
        return float(np.mean(frame))

    def run_auto_exposure(
        self,
        *,
        frame_name: str,
        target_mean: float = 30000,
        min_exp_ms: float = 1.0,
        max_exp_ms: float = 2500.0,
        max_iter: int = 10,
        hysteresis: float = 2000,
        sub_frame_type: str = "",
        use_max_rgb_channel: bool = False,
    ) -> float:
        """Run iterative auto exposure using ISP frame statistics.

        Parameters
        ----------
        frame_name : str
            Target ISP frame name used as feedback.
        target_mean : float, optional
            Mean target, by default ``30000``.
        min_exp_ms : float, optional
            Lower exposure bound in milliseconds, by default ``1.0``.
        max_exp_ms : float, optional
            Upper exposure bound in milliseconds, by default ``2500.0``.
        max_iter : int, optional
            Maximum number of iterations, by default ``10``.
        hysteresis : float, optional
            Absolute mean tolerance for convergence, by default ``2000``.
        sub_frame_type : str, optional
            Optional sub-channel name for metric extraction, by default ``""``.
        use_max_rgb_channel : bool, optional
            Use max RGB channel instead of mean when True, by default False.

        Returns
        -------
        float
            Final exposure value in milliseconds.
        """
        for idx in range(max_iter):
            metric = self.get_frame_mean(
                frame_name,
                sub_frame_type=sub_frame_type,
                timeout_ms=5000,
            )
            if isinstance(metric, np.ndarray):
                cur_mean = float(np.max(metric) if use_max_rgb_channel else np.mean(metric))
            else:
                cur_mean = float(metric)

            if self._is_gsense_camera():
                cur_offset = cur_mean - 1100.0
                target_offset = target_mean - 1100.0
            else:
                cur_offset = cur_mean
                target_offset = target_mean

            if abs(cur_mean - target_mean) <= hysteresis:
                return self.current_exposure_ms

            if cur_offset <= 0:
                next_exp = max_exp_ms
            else:
                ratio = target_offset / cur_offset
                if cur_mean > 63000:
                    ratio = 0.2
                next_exp = round(self._target_exposure_ms * ratio, 2)

            next_exp = max(min_exp_ms, min(max_exp_ms, next_exp))
            logger.info(
                "Auto exposure iter {}/{}: mean={}, next_exp={} ms",
                idx + 1,
                max_iter,
                cur_mean,
                next_exp,
            )

            self.set_exposure_time(next_exp, strict=False)

            if next_exp in {min_exp_ms, max_exp_ms}:
                return self.current_exposure_ms

        return self.current_exposure_ms
