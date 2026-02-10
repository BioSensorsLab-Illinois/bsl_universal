from __future__ import annotations

"""
Runtime device health tracking and alert delivery.

This module is defensive by design: monitoring errors are logged but never
raised back into hardware-control paths.
"""

import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import os
from pathlib import Path
import socket
import smtplib
import ssl
import threading
import uuid
from typing import Callable

from loguru import logger

try:  # pragma: no cover - optional runtime dependency
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except Exception:  # pragma: no cover
    Request = None
    Credentials = None
    InstalledAppFlow = None


_STATE_DIR = Path.home() / ".bsl_universal"
_STATE_FILE = _STATE_DIR / "device_monitor_state.json"
_EMAIL_FILE = _STATE_DIR / "device_monitor_email.json"
_DEFAULT_OAUTH_TOKEN_FILE = _STATE_DIR / "gmail_oauth_token.json"
_DEFAULT_OAUTH_CLIENT_SECRET_FILE = Path(
    "/Users/zz4/Downloads/client_secret_282428684630-9luunv8pkoc6odqri3cnn1vni5dbff1q.apps.googleusercontent.com.json"
)
# SMTP XOAUTH2 for Gmail requires full mail scope.
_GMAIL_SCOPES = ("https://mail.google.com/",)
_LEGACY_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
_STALE_UNKNOWN_PID_SEC = 12 * 3600
_MANTISCAM_HOST = "127.0.0.1"
_MANTISCAM_CMD_PORTS = (60000, 60001)
_MANTISCAM_ACTIVE_KEY = "mantisCam:ACTIVE"
_ALERT_CATEGORIES = (
    "CONNECTING",
    "CONNECTED",
    "DISCONNECTED",
    "WARNING",
    "UNRECOVERABLE_FAILURE",
    "STALE_SESSION",
)
_DEFAULT_ALERT_CATEGORIES = ("UNRECOVERABLE_FAILURE",)


def _utc_now_iso() -> str:
    """
    Return the current UTC timestamp in ISO-8601 format.

    Returns
    -------
    str
        UTC timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_iso(value: str) -> datetime | None:
    """
    Parse an ISO-8601 timestamp into a timezone-aware UTC datetime.

    Parameters
    ----------
    value : str
        Timestamp text.

    Returns
    -------
    datetime | None
        Parsed UTC datetime or None when parse fails.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_state_dir() -> None:
    """
    Ensure the monitor state directory exists.

    Returns
    -------
    None
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    """
    Write JSON atomically to avoid partial reads.

    Parameters
    ----------
    path : Path
        Output file path.
    payload : dict
        JSON payload.

    Returns
    -------
    None
    """
    _ensure_state_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default_payload: dict) -> dict:
    """
    Read JSON safely with fallback.

    Parameters
    ----------
    path : Path
        JSON file path.
    default_payload : dict
        Fallback payload if read fails.

    Returns
    -------
    dict
        Parsed JSON payload or fallback.
    """
    try:
        if not path.exists():
            return default_payload
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_payload


def _read_token_scopes(token_file: Path) -> set[str]:
    """
    Read OAuth scopes from persisted token JSON.

    Parameters
    ----------
    token_file : Path
        OAuth token JSON path.

    Returns
    -------
    set[str]
        Scope set, empty when unavailable.
    """
    payload = _read_json(token_file, {})
    raw = payload.get("scopes", [])
    if not isinstance(raw, list):
        return set()
    scopes: set[str] = set()
    for scope in raw:
        if isinstance(scope, str) and scope.strip():
            scopes.add(scope.strip())
    return scopes


@dataclass
class DeviceStatus:
    """
    Snapshot of a single device's runtime state.

    Parameters
    ----------
    key : str
        Unique key for the device in the registry.
    model : str
        Device model or logical instrument name.
    device_type : str
        Human-readable instrument type.
    serial_number : str
        Device serial number or identifier.
    status : str
        Current status (for example ``"CONNECTED"``).
    updated_at : str
        UTC timestamp in ISO-8601 format.
    last_error : str, optional
        Last known error message.
    process_id : int, optional
        Process id that last published this status.
    session_id : str, optional
        Runtime session identifier for stale-process detection.
    """

    key: str
    model: str
    device_type: str
    serial_number: str
    status: str
    updated_at: str
    last_error: str = ""
    process_id: int = 0
    session_id: str = ""


@dataclass
class EmailAlertConfig:
    """
    Email settings used for device status alert delivery.

    Parameters
    ----------
    enabled : bool
        Enable or disable email alerts.
    provider : str
        Provider label for UI display.
    sender_email : str
        Sender account used for SMTP auth and delivery.
    recipient_email : str
        Alert recipient.
    smtp_server : str
        SMTP host.
    smtp_port : int
        SMTP port.
    oauth_client_secrets_file : str
        Path to Google Workspace OAuth client secrets JSON.
    oauth_token_file : str
        Path to OAuth token JSON file containing refresh token.
    default_categories : list[str]
        Default alert categories that trigger email for all instruments.
    instrument_category_matrix : dict[str, list[str]]
        Per-instrument category override map.
    """

    enabled: bool = False
    provider: str = "gmail"
    sender_email: str = "students@bsl-uiuc.com"
    recipient_email: str = ""
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    oauth_client_secrets_file: str = str(_DEFAULT_OAUTH_CLIENT_SECRET_FILE)
    oauth_token_file: str = str(_DEFAULT_OAUTH_TOKEN_FILE)
    default_categories: list[str] = field(default_factory=lambda: list(_DEFAULT_ALERT_CATEGORIES))
    instrument_category_matrix: dict[str, list[str]] = field(default_factory=dict)


class DeviceHealthHub:
    """
    Thread-safe runtime registry for connected devices and failures.
    """

    def __init__(self) -> None:
        """
        Initialize monitor state, subscriptions, and persisted settings.

        Returns
        -------
        None
        """
        self._lock = threading.RLock()
        self._devices: dict[str, DeviceStatus] = {}
        self._subscribers: list[Callable[[list[DeviceStatus]], None]] = []
        self._email = EmailAlertConfig()
        self._session_id = f"{os.getpid()}-{uuid.uuid4().hex[:10]}"
        self._load_email_config_from_file()
        self._load_state_from_file()
        self.reconcile_stale_entries()

    def subscribe(self, callback: Callable[[list[DeviceStatus]], None]) -> None:
        """
        Subscribe to in-process snapshot updates.

        Parameters
        ----------
        callback : Callable[[list[DeviceStatus]], None]
            Callback receiving full snapshot on changes.

        Returns
        -------
        None
        """
        with self._lock:
            self._subscribers.append(callback)

    def set_email_config(
        self,
        *,
        enabled: bool,
        recipient_email: str,
        sender_email: str = "students@bsl-uiuc.com",
        provider: str = "gmail",
        oauth_client_secrets_file: str | None = None,
        oauth_token_file: str | None = None,
        default_categories: list[str] | tuple[str, ...] | None = None,
        instrument_category_matrix: dict[str, list[str] | tuple[str, ...]] | None = None,
    ) -> None:
        """
        Update and persist email alert configuration.

        Parameters
        ----------
        enabled : bool
            Whether alerts should be sent.
        recipient_email : str
            Destination email address.
        sender_email : str, optional
            Sender account, by default ``students@bsl-uiuc.com``.
        provider : str, optional
            Provider label for UI display.
        oauth_client_secrets_file : str | None, optional
            Optional OAuth client secret path.
        oauth_token_file : str | None, optional
            Optional OAuth token file path.
        default_categories : list[str] | tuple[str, ...] | None, optional
            Default status categories that trigger alert emails.
        instrument_category_matrix : dict[str, list[str] | tuple[str, ...]] | None, optional
            Optional per-instrument category overrides.

        Returns
        -------
        None
        """
        with self._lock:
            self._email.enabled = bool(enabled)
            self._email.provider = provider.strip() or "gmail"
            self._email.sender_email = sender_email.strip() or "students@bsl-uiuc.com"
            self._email.recipient_email = recipient_email.strip()
            if oauth_client_secrets_file is not None:
                cleaned = oauth_client_secrets_file.strip()
                self._email.oauth_client_secrets_file = cleaned or str(_DEFAULT_OAUTH_CLIENT_SECRET_FILE)
            if oauth_token_file is not None and oauth_token_file.strip():
                self._email.oauth_token_file = oauth_token_file.strip()
            if default_categories is not None:
                self._email.default_categories = self._sanitize_alert_categories(
                    default_categories,
                    fallback=list(_DEFAULT_ALERT_CATEGORIES),
                )
            if instrument_category_matrix is not None:
                self._email.instrument_category_matrix = self._sanitize_instrument_category_matrix(
                    instrument_category_matrix
                )
            self._persist_email_config_locked()

        logger.info(
            "Device health email config updated: enabled={}, provider={}, sender={}, recipient={}",
            self._email.enabled,
            self._email.provider,
            self._email.sender_email,
            self._email.recipient_email,
        )

    def authorize_google_workspace(
        self,
        *,
        client_secrets_file: str | None = None,
        sender_email: str = "students@bsl-uiuc.com",
        recipient_email: str = "",
    ) -> tuple[bool, str]:
        """
        Run first-time Google Workspace OAuth authorization flow.

        Parameters
        ----------
        client_secrets_file : str | None, optional
            Path to OAuth client secret JSON downloaded from Google Cloud.
            If omitted, the configured path is used.
        sender_email : str, optional
            Sender workspace account, by default ``students@bsl-uiuc.com``.
        recipient_email : str, optional
            Optional recipient to store together with OAuth config.

        Returns
        -------
        tuple[bool, str]
            ``(success, message)`` result tuple.
        """
        if InstalledAppFlow is None:
            return (
                False,
                "google-auth libraries are not installed. Install google-auth and google-auth-oauthlib.",
            )

        configured_secret = (
            str(client_secrets_file or "").strip()
            or self.get_email_config().oauth_client_secrets_file
            or str(_DEFAULT_OAUTH_CLIENT_SECRET_FILE)
        )
        secret_path = Path(configured_secret).expanduser()
        if not secret_path.exists():
            return False, f"OAuth client secret file not found: {secret_path}"

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secret_path),
                scopes=list(_GMAIL_SCOPES),
            )
            oauth_kwargs = {
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "false",
            }
            try:
                creds = flow.run_local_server(
                    host="127.0.0.1",
                    port=0,
                    authorization_prompt_message="Open this URL in your browser to authorize Gmail alerts:",
                    success_message="Authorization complete. You can close this browser tab.",
                    open_browser=True,
                    **oauth_kwargs,
                )
            except Exception:
                # Fallback for environments where opening the browser fails.
                if hasattr(flow, "run_console"):
                    creds = flow.run_console(**oauth_kwargs)  # pragma: no cover - version dependent
                else:
                    creds = flow.run_local_server(
                        host="127.0.0.1",
                        port=0,
                        authorization_prompt_message=(
                            "Open this URL in your browser to authorize Gmail alerts:"
                        ),
                        success_message="Authorization complete. You can close this browser tab.",
                        open_browser=False,
                        **oauth_kwargs,
                    )
            token_file = Path(self._email.oauth_token_file or str(_DEFAULT_OAUTH_TOKEN_FILE)).expanduser()
            _ensure_state_dir()
            token_file.write_text(creds.to_json(), encoding="utf-8")

            with self._lock:
                self._email.enabled = True
                self._email.provider = "gmail"
                self._email.sender_email = sender_email.strip() or "students@bsl-uiuc.com"
                if recipient_email.strip():
                    self._email.recipient_email = recipient_email.strip()
                self._email.oauth_client_secrets_file = str(secret_path)
                self._email.oauth_token_file = str(token_file)
                self._persist_email_config_locked()

            return True, "Google Workspace OAuth authorization completed."
        except Exception as exc:
            logger.error("Google Workspace authorization failed: {}", exc)
            return False, f"Google authorization failed: {exc}"

    def get_default_oauth_client_secret_file(self) -> str:
        """
        Get default OAuth client secret file path used by this library.

        Returns
        -------
        str
            Absolute path to the built-in default OAuth client secret JSON.
        """
        return str(_DEFAULT_OAUTH_CLIENT_SECRET_FILE)

    def get_supported_alert_categories(self) -> tuple[str, ...]:
        """
        Get supported alert categories for email notification policy.

        Returns
        -------
        tuple[str, ...]
            Supported category names.
        """
        return tuple(_ALERT_CATEGORIES)

    def send_test_email(self) -> tuple[bool, str]:
        """
        Send a test alert email using current configuration.

        Returns
        -------
        tuple[bool, str]
            ``(success, message)`` result tuple.
        """
        cfg = self.get_email_config()
        try:
            if not cfg.recipient_email:
                return False, "Recipient email is required."
            self._deliver_email(
                cfg,
                subject="[BSL Alert] Test notification",
                body=(
                    "This is a test message from bsl_universal device monitor.\n\n"
                    f"Sender: {cfg.sender_email}\n"
                    f"Recipient: {cfg.recipient_email}\n"
                    "Auth mode: oauth (Google Workspace)\n"
                    f"Time (UTC): {_utc_now_iso()}\n"
                ),
            )
            return True, "Test email sent successfully."
        except Exception as exc:
            logger.error("Test email delivery failed: {}", exc)
            return False, str(exc)

    def get_email_config(self) -> EmailAlertConfig:
        """
        Get latest email config (reloaded from persisted state).

        Returns
        -------
        EmailAlertConfig
            Current email config.
        """
        self._load_email_config_from_file()
        with self._lock:
            return EmailAlertConfig(**asdict(self._email))

    def get_snapshot(self) -> list[DeviceStatus]:
        """
        Return current in-memory device snapshot.

        Returns
        -------
        list[DeviceStatus]
            Snapshot sorted by key.
        """
        with self._lock:
            return [self._devices[key] for key in sorted(self._devices)]

    def get_snapshot_from_file(self) -> list[DeviceStatus]:
        """
        Load snapshot from persisted state file.

        Returns
        -------
        list[DeviceStatus]
            Device list from disk.
        """
        payload = _read_json(_STATE_FILE, {"devices": []})
        statuses = []
        for item in payload.get("devices", []):
            normalized = self._normalize_device_payload(item)
            if normalized is None:
                continue
            statuses.append(normalized)

        changed = self._reconcile_status_list(statuses)
        if changed:
            _atomic_write_json(_STATE_FILE, {"devices": [asdict(item) for item in sorted(statuses, key=lambda x: x.key)]})
        return statuses

    def register_connection(
        self,
        *,
        instrument_key: str,
        model: str,
        device_type: str,
        serial_number: str,
    ) -> None:
        """
        Register a successful device connection event.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        model : str
            Device model string.
        device_type : str
            Device type string.
        serial_number : str
            Device serial/identifier.

        Returns
        -------
        None
        """
        key = self._build_key(instrument_key, serial_number)
        status = DeviceStatus(
            key=key,
            model=model or instrument_key,
            device_type=device_type or "Unknown",
            serial_number=serial_number or "Unknown",
            status="CONNECTED",
            updated_at=_utc_now_iso(),
            last_error="",
            process_id=os.getpid(),
            session_id=self._session_id,
        )
        with self._lock:
            self._cleanup_owner_entries_for_instrument_locked(
                instrument_key=instrument_key,
                keep_key=key,
                remove_connecting_only=not self._is_mantiscam_instrument_key(instrument_key),
            )
            self._devices[key] = status
            self._persist_state_locked()
        self._notify_subscribers()
        self._send_status_email_async(status)

    def register_connecting(
        self,
        *,
        instrument_key: str,
        model: str,
        device_type: str,
        serial_number: str,
        note: str = "",
    ) -> None:
        """
        Register an in-progress device connection event.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        model : str
            Device model string.
        device_type : str
            Device type string.
        serial_number : str
            Device serial/identifier.
        note : str, optional
            Optional connection progress note.

        Returns
        -------
        None
        """
        key = self._build_key(instrument_key, serial_number)
        with self._lock:
            previous = self._devices.get(key)
            self._cleanup_owner_entries_for_instrument_locked(
                instrument_key=instrument_key,
                keep_key=key,
                remove_connecting_only=not self._is_mantiscam_instrument_key(instrument_key),
            )
            status = DeviceStatus(
                key=key,
                model=model or (previous.model if previous is not None else instrument_key),
                device_type=device_type or (previous.device_type if previous is not None else "Unknown"),
                serial_number=serial_number or (previous.serial_number if previous is not None else "Unknown"),
                status="CONNECTING",
                updated_at=_utc_now_iso(),
                last_error=note.strip(),
                process_id=os.getpid(),
                session_id=self._session_id,
            )
            self._devices[key] = status
            self._persist_state_locked()
        self._notify_subscribers()
        self._send_status_email_async(status)

    def register_disconnection(
        self,
        *,
        instrument_key: str,
        model: str,
        device_type: str,
        serial_number: str,
        error_message: str = "",
    ) -> None:
        """
        Register a device disconnection event.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        model : str
            Device model string.
        device_type : str
            Device type string.
        serial_number : str
            Device serial/identifier.
        error_message : str, optional
            Optional final warning/error text, by default ``""``.

        Returns
        -------
        None
        """
        key = self._build_key(instrument_key, serial_number)
        with self._lock:
            previous = self._devices.get(key)
            status = DeviceStatus(
                key=key,
                model=model or (previous.model if previous is not None else instrument_key),
                device_type=device_type or (previous.device_type if previous is not None else "Unknown"),
                serial_number=serial_number
                or (previous.serial_number if previous is not None else "Unknown"),
                status="DISCONNECTED",
                updated_at=_utc_now_iso(),
                last_error=error_message.strip(),
                process_id=os.getpid(),
                session_id=self._session_id,
            )
            self._devices[key] = status
            self._persist_state_locked()
        self._notify_subscribers()
        self._send_status_email_async(status)

    def register_failure(
        self,
        *,
        instrument_key: str,
        model: str,
        device_type: str,
        serial_number: str,
        error_message: str,
        unrecoverable: bool = True,
    ) -> None:
        """
        Register a device failure event.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        model : str
            Device model string.
        device_type : str
            Device type string.
        serial_number : str
            Device serial/identifier.
        error_message : str
            Human-readable error detail.
        unrecoverable : bool, optional
            Whether the failure is unrecoverable, by default True.

        Returns
        -------
        None
        """
        key = self._build_key(instrument_key, serial_number)
        status = DeviceStatus(
            key=key,
            model=model or instrument_key,
            device_type=device_type or "Unknown",
            serial_number=serial_number or "Unknown",
            status="UNRECOVERABLE_FAILURE" if unrecoverable else "WARNING",
            updated_at=_utc_now_iso(),
            last_error=error_message,
            process_id=os.getpid(),
            session_id=self._session_id,
        )
        with self._lock:
            self._devices[key] = status
            self._persist_state_locked()
        self._notify_subscribers()
        self._send_status_email_async(status)

    def clear_entries(self, *, statuses: tuple[str, ...] | None = None) -> int:
        """
        Remove entries from the state map.

        Parameters
        ----------
        statuses : tuple[str, ...] | None, optional
            Status filter. When None, all entries are removed.

        Returns
        -------
        int
            Number of removed entries.
        """
        should_notify = False
        removed = 0
        with self._lock:
            self._load_state_from_file_locked()
            if not statuses:
                removed = len(self._devices)
                self._devices.clear()
                self._persist_state_locked()
                should_notify = removed > 0
            else:
                wanted = {str(item).strip().upper() for item in statuses if str(item).strip()}
                removed_keys = [key for key, item in self._devices.items() if item.status.upper() in wanted]
                for key in removed_keys:
                    self._devices.pop(key, None)
                removed = len(removed_keys)
                if removed_keys:
                    self._persist_state_locked()
                    should_notify = True

        if should_notify:
            self._notify_subscribers()
        return removed

    def reconcile_stale_entries(self) -> int:
        """
        Mark dead-process connected entries as stale.

        Returns
        -------
        int
            Number of modified entries.
        """
        changed_items: list[DeviceStatus] = []
        with self._lock:
            self._load_state_from_file_locked()
            before = {key: asdict(item) for key, item in self._devices.items()}
            statuses = list(self._devices.values())
            changed = self._reconcile_status_list(statuses)
            if not changed:
                return 0
            for item in statuses:
                previous = before.get(item.key)
                current = asdict(item)
                if previous != current:
                    changed_items.append(item)
            self._devices = {item.key: item for item in statuses}
            self._persist_state_locked()
        self._notify_subscribers()
        for item in changed_items:
            self._send_status_email_async(item)
        return changed

    def _build_key(self, instrument_key: str, serial_number: str) -> str:
        """
        Build deterministic registry key from model and serial.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        serial_number : str
            Device serial.

        Returns
        -------
        str
            Registry key.
        """
        if self._is_mantiscam_instrument_key(instrument_key):
            return _MANTISCAM_ACTIVE_KEY
        serial = serial_number or "Unknown"
        return f"{instrument_key}:{serial}"

    @staticmethod
    def _is_mantiscam_instrument_key(instrument_key: str) -> bool:
        """
        Check whether a logical instrument key refers to MantisCam.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.

        Returns
        -------
        bool
            True when key resolves to MantisCam.
        """
        return str(instrument_key or "").strip().lower() == "mantiscam"

    @staticmethod
    def _instrument_from_key(key: str) -> str:
        """
        Extract logical instrument key prefix from registry key.

        Parameters
        ----------
        key : str
            Registry key.

        Returns
        -------
        str
            Instrument key prefix.
        """
        return str(key or "").split(":", 1)[0]

    def _is_entry_owned_by_current_runtime(self, item: DeviceStatus) -> bool:
        """
        Check whether a status entry belongs to current process/runtime session.

        Parameters
        ----------
        item : DeviceStatus
            Status entry.

        Returns
        -------
        bool
            True when entry owner matches current runtime.
        """
        if int(item.process_id or 0) != os.getpid():
            return False
        item_session = str(item.session_id or "")
        return item_session == "" or item_session == self._session_id

    def _cleanup_owner_entries_for_instrument_locked(
        self,
        *,
        instrument_key: str,
        keep_key: str,
        remove_connecting_only: bool,
    ) -> None:
        """
        Remove duplicate owner entries for one instrument prior to status update.

        Parameters
        ----------
        instrument_key : str
            Logical instrument key.
        keep_key : str
            Key that should be retained.
        remove_connecting_only : bool
            If True, only pending ``CONNECTING`` duplicates are removed.

        Returns
        -------
        None
        """
        target = str(instrument_key or "").strip().lower()
        to_remove: list[str] = []
        for existing_key, existing in self._devices.items():
            if existing_key == keep_key:
                continue
            if not self._is_entry_owned_by_current_runtime(existing):
                continue

            existing_inst = self._instrument_from_key(existing_key).strip().lower()
            same_instrument = existing_inst == target
            if self._is_mantiscam_instrument_key(instrument_key) and self._is_mantiscam_entry(existing):
                same_instrument = True
            if not same_instrument:
                continue

            if remove_connecting_only and str(existing.status).upper() != "CONNECTING":
                continue
            to_remove.append(existing_key)

        for existing_key in to_remove:
            self._devices.pop(existing_key, None)

    def _normalize_device_payload(self, payload: dict) -> DeviceStatus | None:
        """
        Normalize one persisted payload dictionary to ``DeviceStatus``.

        Parameters
        ----------
        payload : dict
            Raw JSON payload item.

        Returns
        -------
        DeviceStatus | None
            Parsed status object or None when payload is invalid.
        """
        try:
            base = {
                "key": payload.get("key", ""),
                "model": payload.get("model", "Unknown"),
                "device_type": payload.get("device_type", "Unknown"),
                "serial_number": payload.get("serial_number", "Unknown"),
                "status": payload.get("status", "Unknown"),
                "updated_at": payload.get("updated_at", _utc_now_iso()),
                "last_error": payload.get("last_error", ""),
                "process_id": int(payload.get("process_id", 0) or 0),
                "session_id": str(payload.get("session_id", "") or ""),
            }
            if not base["key"]:
                key = self._build_key(base["model"], base["serial_number"])
                base["key"] = key
            return DeviceStatus(**base)
        except Exception:
            return None

    def _reconcile_status_list(self, statuses: list[DeviceStatus]) -> int:
        """
        Reconcile stale status entries in-place.

        Parameters
        ----------
        statuses : list[DeviceStatus]
            Mutable status list.

        Returns
        -------
        int
            Number of modified entries.
        """
        now = datetime.now(timezone.utc)
        changed = 0
        live_states = {"CONNECTING", "CONNECTED", "WARNING"}
        mantiscam_alive_cache: bool | None = None

        for item in statuses:
            if item.status.upper() not in live_states:
                continue

            pid = int(item.process_id or 0)
            is_alive = self._is_process_alive(pid) if pid > 0 else None
            update_time = _parse_utc_iso(item.updated_at)

            if is_alive is False:
                item.status = "STALE_SESSION"
                if not item.last_error:
                    item.last_error = "Owning process is no longer running."
                item.updated_at = _utc_now_iso()
                changed += 1
                continue

            if self._is_mantiscam_entry(item):
                if mantiscam_alive_cache is None:
                    mantiscam_alive_cache = self._is_mantiscam_service_alive()
                if not mantiscam_alive_cache:
                    item.status = "DISCONNECTED"
                    item.last_error = (
                        "MantisCamUnified is not reachable on local command ports "
                        f"{_MANTISCAM_CMD_PORTS}."
                    )
                    item.updated_at = _utc_now_iso()
                    changed += 1
                    continue

            if pid <= 0 and update_time is not None:
                if not item.session_id:
                    item.status = "STALE_SESSION"
                    if not item.last_error:
                        item.last_error = "Legacy status entry has no owner process metadata."
                    item.updated_at = _utc_now_iso()
                    changed += 1
                    continue
                age_sec = (now - update_time).total_seconds()
                if age_sec >= _STALE_UNKNOWN_PID_SEC:
                    item.status = "STALE_SESSION"
                    if not item.last_error:
                        item.last_error = "Legacy status entry exceeded stale timeout."
                    item.updated_at = _utc_now_iso()
                    changed += 1

        return changed

    @staticmethod
    def _is_process_alive(process_id: int) -> bool:
        """
        Check if a process id is currently alive.

        Parameters
        ----------
        process_id : int
            Process identifier.

        Returns
        -------
        bool
            True when process appears alive.
        """
        if process_id <= 0:
            return False
        try:
            os.kill(process_id, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    @staticmethod
    def _is_mantiscam_entry(item: DeviceStatus) -> bool:
        """
        Check whether a status entry corresponds to MantisCam.

        Parameters
        ----------
        item : DeviceStatus
            Status entry to classify.

        Returns
        -------
        bool
            True when entry appears to represent a MantisCam device.
        """
        key = str(item.key or "").strip().lower()
        device_type = str(item.device_type or "").strip().lower()
        model = str(item.model or "").strip().lower()
        return (
            key.startswith("mantiscam:")
            or device_type.startswith("mantiscam")
            or model.startswith("mantiscam")
        )

    @staticmethod
    def _can_connect_tcp(host: str, port: int, *, timeout_sec: float = 0.2) -> bool:
        """
        Check whether a TCP endpoint accepts local connections.

        Parameters
        ----------
        host : str
            Host address.
        port : int
            TCP port number.
        timeout_sec : float, optional
            Socket connect timeout in seconds, by default ``0.2``.

        Returns
        -------
        bool
            True when connect succeeds.
        """
        try:
            with socket.create_connection((host, int(port)), timeout=timeout_sec):
                return True
        except Exception:
            return False

    @classmethod
    def _is_mantiscam_service_alive(cls) -> bool:
        """
        Check whether MantisCamUnified command endpoints are reachable.

        Returns
        -------
        bool
            True when all required command ports respond.
        """
        for port in _MANTISCAM_CMD_PORTS:
            if not cls._can_connect_tcp(_MANTISCAM_HOST, int(port), timeout_sec=0.2):
                return False
        return True

    def _notify_subscribers(self) -> None:
        """
        Notify in-process subscribers with latest snapshot.

        Returns
        -------
        None
        """
        snapshot = self.get_snapshot()
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(snapshot)
            except Exception as exc:
                logger.warning("Device monitor callback failed: {}", exc)

    def _persist_state_locked(self) -> None:
        """
        Persist in-memory device snapshot to disk.

        Returns
        -------
        None
        """
        payload = {
            "devices": [asdict(self._devices[key]) for key in sorted(self._devices)],
        }
        _atomic_write_json(_STATE_FILE, payload)

    def _load_state_from_file(self) -> None:
        """
        Load device snapshot from disk into memory.

        Returns
        -------
        None
        """
        with self._lock:
            self._load_state_from_file_locked()

    def _load_state_from_file_locked(self) -> None:
        """
        Load device snapshot from disk into memory (lock must be held).

        Returns
        -------
        None
        """
        payload = _read_json(_STATE_FILE, {"devices": []})
        loaded: dict[str, DeviceStatus] = {}
        for item in payload.get("devices", []):
            normalized = self._normalize_device_payload(item)
            if normalized is None:
                continue
            loaded[normalized.key] = normalized
        self._devices = loaded

    def _persist_email_config_locked(self) -> None:
        """
        Persist email config to disk.

        Returns
        -------
        None
        """
        _atomic_write_json(_EMAIL_FILE, asdict(self._email))

    def _load_email_config_from_file(self) -> None:
        """
        Load email config from disk and merge into current config.

        Returns
        -------
        None
        """
        payload = _read_json(_EMAIL_FILE, asdict(EmailAlertConfig()))
        defaults = asdict(EmailAlertConfig())
        sanitized = dict(payload)
        # Legacy auth fields are ignored; this module is OAuth-only.
        sanitized.pop("app_password", None)
        sanitized.pop("auth_mode", None)
        if "default_categories" in sanitized:
            sanitized["default_categories"] = self._sanitize_alert_categories(
                sanitized.get("default_categories"),
                fallback=list(_DEFAULT_ALERT_CATEGORIES),
            )
        if "instrument_category_matrix" in sanitized:
            sanitized["instrument_category_matrix"] = self._sanitize_instrument_category_matrix(
                sanitized.get("instrument_category_matrix")
            )
        merged = {**defaults, **{k: v for k, v in sanitized.items() if k in defaults}}
        try:
            with self._lock:
                self._email = EmailAlertConfig(**merged)
        except Exception:
            pass

    @staticmethod
    def _normalize_alert_category(value: str) -> str | None:
        """
        Normalize a status category string.

        Parameters
        ----------
        value : str
            Raw category text.

        Returns
        -------
        str | None
            Normalized category or None when unsupported.
        """
        token = str(value or "").strip().upper()
        return token if token in _ALERT_CATEGORIES else None

    @classmethod
    def _sanitize_alert_categories(
        cls,
        values: list[str] | tuple[str, ...] | set[str] | None,
        *,
        fallback: list[str],
    ) -> list[str]:
        """
        Sanitize and normalize category list.

        Parameters
        ----------
        values : list[str] | tuple[str, ...] | set[str] | None
            Raw category collection.
        fallback : list[str]
            Fallback categories when input is missing/invalid.

        Returns
        -------
        list[str]
            Sanitized category list.
        """
        if values is None:
            return list(fallback)
        if not isinstance(values, (list, tuple, set)):
            return list(fallback)
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = cls._normalize_alert_category(str(value))
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @classmethod
    def _sanitize_instrument_category_matrix(
        cls,
        raw_matrix: dict[str, list[str] | tuple[str, ...]] | None,
    ) -> dict[str, list[str]]:
        """
        Sanitize per-instrument category override matrix.

        Parameters
        ----------
        raw_matrix : dict[str, list[str] | tuple[str, ...]] | None
            Raw matrix payload.

        Returns
        -------
        dict[str, list[str]]
            Sanitized matrix mapping.
        """
        if raw_matrix is None or not isinstance(raw_matrix, dict):
            return {}
        cleaned: dict[str, list[str]] = {}
        for raw_key, raw_categories in raw_matrix.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            categories = cls._sanitize_alert_categories(raw_categories, fallback=[])
            cleaned[key] = categories
        return cleaned

    def _load_oauth_credentials(self, cfg: EmailAlertConfig):
        """
        Load and refresh OAuth credentials for Gmail Workspace sending.

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.

        Returns
        -------
        Credentials
            Valid OAuth credentials object.

        Raises
        ------
        RuntimeError
            If credentials cannot be loaded/refreshed.
        """
        if Credentials is None or Request is None:
            raise RuntimeError(
                "google-auth libraries are not installed. Install google-auth and google-auth-oauthlib."
            )

        token_file = Path(cfg.oauth_token_file or str(_DEFAULT_OAUTH_TOKEN_FILE)).expanduser()
        if not token_file.exists():
            raise RuntimeError(f"OAuth token file not found: {token_file}")

        token_scopes = _read_token_scopes(token_file)
        required_scope = _GMAIL_SCOPES[0]
        if token_scopes and required_scope not in token_scopes:
            if _LEGACY_GMAIL_SEND_SCOPE in token_scopes:
                raise RuntimeError(
                    "OAuth token uses legacy scope `gmail.send`, but SMTP XOAUTH2 requires "
                    "`https://mail.google.com/`. Click 'Authorize Google Workspace' in the GUI "
                    "to refresh OAuth permissions."
                )
            raise RuntimeError(
                "OAuth token scopes do not include SMTP requirement `https://mail.google.com/`. "
                "Click 'Authorize Google Workspace' in the GUI to refresh OAuth permissions."
            )

        creds = Credentials.from_authorized_user_file(str(token_file), scopes=list(_GMAIL_SCOPES))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_file.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError("OAuth credentials are invalid. Re-run Google Workspace authorization.")
        return creds

    def _status_instrument_key(self, status: DeviceStatus) -> str:
        """
        Extract logical instrument key from a status snapshot.

        Parameters
        ----------
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        str
            Logical instrument key.
        """
        return self._instrument_from_key(status.key).strip()

    def _resolve_alert_categories_for_instrument(
        self,
        cfg: EmailAlertConfig,
        instrument_key: str,
    ) -> list[str]:
        """
        Resolve effective alert categories for one instrument.

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.
        instrument_key : str
            Logical instrument key.

        Returns
        -------
        list[str]
            Effective category list.
        """
        target = str(instrument_key or "").strip().lower()
        matrix = self._sanitize_instrument_category_matrix(cfg.instrument_category_matrix)
        for key, categories in matrix.items():
            if str(key).strip().lower() == target:
                return list(categories)
        return self._sanitize_alert_categories(cfg.default_categories, fallback=list(_DEFAULT_ALERT_CATEGORIES))

    def _should_send_alert_for_status(self, cfg: EmailAlertConfig, status: DeviceStatus) -> bool:
        """
        Check whether current policy should send email for a status event.

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        bool
            True when status should trigger an email.
        """
        category = self._normalize_alert_category(status.status)
        if category is None:
            return False
        instrument_key = self._status_instrument_key(status)
        allowed = self._resolve_alert_categories_for_instrument(cfg, instrument_key)
        return category in set(allowed)

    def _send_status_email_async(self, status: DeviceStatus) -> None:
        """
        Dispatch async email alert for a device status event.

        Parameters
        ----------
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        None
        """
        cfg = self.get_email_config()
        if not cfg.enabled:
            return

        if not self._should_send_alert_for_status(cfg, status):
            return

        if not cfg.recipient_email:
            logger.warning("Email alerts enabled but recipient is missing. Skipping alert delivery.")
            return

        token_file = Path(cfg.oauth_token_file or str(_DEFAULT_OAUTH_TOKEN_FILE)).expanduser()
        if not token_file.exists():
            logger.warning(
                "OAuth token file not found at {}. Run Google Workspace authorization first.",
                token_file,
            )
            return

        thread = threading.Thread(
            target=self._send_status_email,
            args=(cfg, status),
            daemon=True,
            name="bsl-email-alert",
        )
        thread.start()

    def _send_failure_email_async(self, status: DeviceStatus) -> None:
        """
        Backward-compatible alias for status-based alert dispatch.

        Parameters
        ----------
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        None
        """
        self._send_status_email_async(status)

    def _deliver_email(self, cfg: EmailAlertConfig, *, subject: str, body: str) -> None:
        """
        Deliver an email using Gmail OAuth (XOAUTH2).

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.
        subject : str
            Subject line.
        body : str
            Plain text body.

        Returns
        -------
        None
        """
        msg = EmailMessage()
        msg["From"] = cfg.sender_email
        msg["To"] = cfg.recipient_email
        msg["Subject"] = subject
        msg.set_content(body)

        creds = self._load_oauth_credentials(cfg)
        access_token = creds.token
        if not access_token:
            raise RuntimeError("OAuth token is empty after refresh.")

        context = ssl.create_default_context()

        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()

            auth_string = f"user={cfg.sender_email}\x01auth=Bearer {access_token}\x01\x01"
            auth_b64 = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
            try:
                code, resp = smtp.docmd("AUTH", f"XOAUTH2 {auth_b64}")
            except smtplib.SMTPAuthenticationError as exc:
                smtp_resp = exc.smtp_error
                if isinstance(smtp_resp, bytes):
                    smtp_resp = smtp_resp.decode("utf-8", errors="replace")
                raise RuntimeError(
                    "XOAUTH2 authentication failed. "
                    f"SMTP response: {exc.smtp_code} {smtp_resp}. "
                    "Re-authorize in the GUI, ensure the signed-in Google account matches sender_email "
                    "(or has send-as permission), and verify Workspace SMTP AUTH is allowed for the account."
                ) from exc
            if int(code) != 235:
                if isinstance(resp, bytes):
                    resp_text = resp.decode("utf-8", errors="replace")
                else:
                    resp_text = str(resp)
                raise RuntimeError(
                    "XOAUTH2 authentication failed. "
                    f"SMTP response: {code} {resp_text}. "
                    "Re-authorize in the GUI, ensure the signed-in Google account matches sender_email "
                    "(or has send-as permission), and verify Workspace SMTP AUTH is allowed for the account."
                )

            smtp.send_message(msg)

    def _send_status_email(self, cfg: EmailAlertConfig, status: DeviceStatus) -> None:
        """
        Send status alert email via configured provider.

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        None
        """
        try:
            instrument_key = self._status_instrument_key(status)
            category = self._normalize_alert_category(status.status) or str(status.status).upper()
            self._deliver_email(
                cfg,
                subject=f"[BSL Alert:{category}] {status.model}",
                body=(
                    "A bsl_universal device status event matched your email alert policy.\n\n"
                    f"Category: {category}\n"
                    f"Instrument: {instrument_key}\n"
                    f"Model: {status.model}\n"
                    f"Type: {status.device_type}\n"
                    f"Serial: {status.serial_number}\n"
                    f"Status: {status.status}\n"
                    f"Updated (UTC): {status.updated_at}\n"
                    f"Error: {status.last_error}\n"
                ),
            )
            logger.success(
                "Status alert email sent to {} for {} [{}] ({})",
                cfg.recipient_email,
                status.model,
                category,
                status.serial_number,
            )
        except Exception as exc:
            logger.error("Failed to send status alert email: {}", exc)

    def _send_failure_email(self, cfg: EmailAlertConfig, status: DeviceStatus) -> None:
        """
        Backward-compatible alias for status alert sender.

        Parameters
        ----------
        cfg : EmailAlertConfig
            Email configuration.
        status : DeviceStatus
            Device status snapshot.

        Returns
        -------
        None
        """
        self._send_status_email(cfg, status)


# Shared singleton used by all instrument constructors and monitor UI.
device_health_hub = DeviceHealthHub()
