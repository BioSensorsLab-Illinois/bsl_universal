from __future__ import annotations

"""
Robust VISA interface wrapper with retry and reconnect behavior.
"""

import re
import time
from typing import Any, Callable

from loguru import logger

from ..headers._bsl_inst_info import _bsl_inst_info_list
from ..headers._bsl_type import _bsl_type as bsl_type

try:
    import pyvisa
except ImportError:
    pyvisa = None

try:
    from bsl_universal.core.device_health import device_health_hub
except Exception:
    device_health_hub = None

logger_opt = logger.opt(ansi=True)


class _bsl_visa:
    """
    VISA transport helper used by instrument drivers.

    Parameters
    ----------
    target_inst : _bsl_inst_info_list
        Instrument metadata descriptor.
    device_sn : str, optional
        Optional serial selector for device matching, by default ``""``.
    """

    MAX_CONNECT_RETRY = 3
    MAX_IO_RETRY = 3
    RETRY_DELAY_SEC = 0.25

    def __init__(self, target_inst: _bsl_inst_info_list, device_sn: str = "") -> None:
        """
        Initialize VISA transport helper.

        Parameters
        ----------
        target_inst : _bsl_inst_info_list
            Instrument metadata descriptor.
        device_sn : str, optional
            Optional serial selector for device matching, by default ``""``.
        """
        self.inst = target_inst
        self.target_device_sn = device_sn
        self.device_id = ""
        self.com_port = None
        self.visa_resource_manager = None

        logger_opt.info("    Initiating bsl_visa_service...")
        self._init_resource_manager()
        self._connect_visa_device()

        if self.com_port is None:
            logger_opt.error(
                "<light-blue><italic>{} ({})</italic></light-blue> not found on VISA/SCPI ports.",
                self.inst.MODEL,
                self.target_device_sn,
            )

    def __del__(self) -> None:
        self.close()

    def _init_resource_manager(self) -> None:
        """
        Initialize the PyVISA resource manager.
        """
        if pyvisa is None:
            logger_opt.error("PyVISA is not installed; VISA communication unavailable.")
            return
        try:
            self.visa_resource_manager = pyvisa.ResourceManager()
        except Exception as exc:
            logger_opt.error("Failed to initialize VISA resource manager: {}", exc)
            self.visa_resource_manager = None

    def _find_device_vpid(self) -> str | None:
        """
        Find matching VISA resource by USB identifiers and serial filter.

        Returns
        -------
        str | None
            VISA resource name if found, otherwise ``None``.
        """
        if self.visa_resource_manager is None:
            return None
        try:
            resource_list = self.visa_resource_manager.list_resources()
            opened = str(self.visa_resource_manager.list_opened_resources())
        except Exception as exc:
            logger_opt.warning("Unable to enumerate VISA resources: {}", exc)
            return None

        logger.debug("    bsl_VISA - Currently opened devices: {}", opened)
        for port in resource_list:
            logger_opt.debug("    Found bus device <light-blue><italic>{}</italic></light-blue>", port)
            if port in opened:
                logger_opt.warning(
                    "    BUSY - Device <light-blue><italic>{}</italic></light-blue> is busy, moving to next available device...",
                    port,
                )
                continue
            if not self._port_matches_usb_id(port):
                continue
            if self._port_matches_serial(port):
                return port
        return None

    def _port_matches_usb_id(self, port: str) -> bool:
        """
        Check whether a VISA resource name matches configured PID/VID.

        Parameters
        ----------
        port : str
            VISA resource string.

        Returns
        -------
        bool
            True if PID/VID appears to match metadata.
        """
        pid = str(self.inst.USB_PID)
        vid = str(self.inst.USB_VID)
        if pid in port and vid in port:
            return True
        try:
            pid_dec = str(int(pid, 16))
            vid_dec = str(int(vid, 16))
            return pid_dec in port and vid_dec in port
        except Exception:
            return False

    def _port_matches_serial(self, port: str) -> bool:
        """
        Validate serial match for a candidate VISA resource.

        Parameters
        ----------
        port : str
            VISA resource string.

        Returns
        -------
        bool
            True if serial filtering passes.
        """
        if self.visa_resource_manager is None:
            return False
        temp_com_port = None
        try:
            temp_com_port = self.visa_resource_manager.open_resource(port)
            response = temp_com_port.query(self.inst.QUERY_CMD).strip()
            match = re.search(self.inst.SN_REG, response)
            candidate_id = match.group(0) if match is not None else "UNABLE_TO_OBTAIN"
            if self.target_device_sn and self.target_device_sn not in candidate_id:
                logger_opt.warning(
                    "    S/N Mismatch - Device <light-blue><italic>{}</italic></light-blue> with S/N <light-blue><italic>{}</italic></light-blue> found, not <light-blue><italic>{}</italic></light-blue> as requested, moving to next available device...",
                    port,
                    candidate_id,
                    self.target_device_sn,
                )
                return False
            return True
        except Exception as exc:
            logger_opt.warning("VISA probe failed on {}: {}", port, exc)
            return False
        finally:
            try:
                if temp_com_port is not None:
                    temp_com_port.close()
            except Exception:
                pass

    def _connect_visa_device(self) -> None:
        """
        Connect to a VISA device with bounded retries.
        """
        self.com_port = None
        self.device_id = ""
        for attempt in range(1, self.MAX_CONNECT_RETRY + 1):
            port = self._find_device_vpid()
            if port is None:
                time.sleep(self.RETRY_DELAY_SEC)
                continue
            try:
                self.com_port = self.visa_resource_manager.open_resource(port)
                identity = self.com_port.query(self.inst.QUERY_CMD).strip()
                if self.inst.QUERY_E_RESP not in identity:
                    raise bsl_type.DeviceConnectionFailed(
                        f"Wrong identifier returned: {identity}"
                    )
                match = re.search(self.inst.SN_REG, identity)
                self.device_id = match.group(0) if match is not None else identity
                logger_opt.success(
                    "    {} with DEVICE_ID: <light-blue><italic>{}</italic></light-blue> found and connected!",
                    self.inst.MODEL,
                    self.device_id,
                )
                return
            except Exception as exc:
                logger_opt.warning(
                    "VISA connect attempt {}/{} failed for {}: {}",
                    attempt,
                    self.MAX_CONNECT_RETRY,
                    self.inst.MODEL,
                    exc,
                )
                try:
                    if self.com_port is not None:
                        self.com_port.close()
                except Exception:
                    pass
                self.com_port = None
                time.sleep(self.RETRY_DELAY_SEC)

    def _reconnect(self) -> bool:
        """
        Try to restore VISA connection.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        self.close()
        if self.visa_resource_manager is None:
            self._init_resource_manager()
        self._connect_visa_device()
        return self.com_port is not None

    def _report_unrecoverable_failure(self, message: str) -> None:
        """
        Report unrecoverable transport failure to runtime health registry.

        Parameters
        ----------
        message : str
            Error message.
        """
        if device_health_hub is None:
            return
        try:
            device_health_hub.register_failure(
                instrument_key=str(self.inst.MODEL),
                model=str(self.inst.MODEL),
                device_type=str(getattr(self.inst, "TYPE", "Unknown")),
                serial_number=str(self.device_id or self.target_device_sn or "Unknown"),
                error_message=message,
                unrecoverable=True,
            )
        except Exception:
            pass

    def _run_with_reconnect(
        self,
        operation_name: str,
        callback: Callable[[], Any],
    ) -> Any:
        """
        Execute an operation with automatic reconnect retries.

        Parameters
        ----------
        operation_name : str
            Label used for logging/reporting.
        callback : Callable[[], Any]
            Operation callback to execute.

        Returns
        -------
        Any
            Callback result.

        Raises
        ------
        bsl_type.DeviceOperationError
            If operation fails after retry attempts.
        """
        for attempt in range(1, self.MAX_IO_RETRY + 1):
            if self.com_port is None and not self._reconnect():
                time.sleep(self.RETRY_DELAY_SEC)
                continue
            try:
                return callback()
            except Exception as exc:
                logger_opt.warning(
                    "VISA {} attempt {}/{} failed for {}: {}",
                    operation_name,
                    attempt,
                    self.MAX_IO_RETRY,
                    self.inst.MODEL,
                    exc,
                )
                self._reconnect()
                time.sleep(self.RETRY_DELAY_SEC)
        message = (
            f"{self.inst.MODEL} VISA {operation_name} failed after "
            f"{self.MAX_IO_RETRY} attempts."
        )
        logger_opt.error(message)
        self._report_unrecoverable_failure(message)
        raise bsl_type.DeviceOperationError(message)

    def query(self, cmd: str) -> str:
        """
        Query the device via VISA/SCPI.

        Parameters
        ----------
        cmd : str
            SCPI query command string.

        Returns
        -------
        str
            Trimmed response payload.
        """
        logger_opt.trace(
            "        {} - com-VISA - Query to {} with {}",
            self.inst.MODEL,
            self.inst.MODEL,
            cmd,
        )

        def _run_query() -> str:
            resp = self.com_port.query(cmd).strip()
            logger_opt.trace(
                "        {} - com-VISA - Resp from {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(resp),
            )
            return resp

        return self._run_with_reconnect("query", _run_query)

    def write(self, cmd: str) -> None:
        """
        Write a command to the device via VISA/SCPI.

        Parameters
        ----------
        cmd : str
            SCPI write command string.
        """
        logger_opt.trace(
            "        {} - com-VISA - Write to {} with {}",
            self.inst.MODEL,
            self.inst.MODEL,
            cmd,
        )

        def _run_write() -> None:
            self.com_port.write(cmd)

        self._run_with_reconnect("write", _run_write)

    def set_timeout_ms(self, timeout: int) -> None:
        """
        Set VISA timeout in milliseconds.

        Parameters
        ----------
        timeout : int
            Timeout in milliseconds.
        """
        def _set_timeout() -> None:
            self.com_port.timeout = timeout

        self._run_with_reconnect("set-timeout", _set_timeout)

    def close(self) -> None:
        """
        Close VISA resources safely.
        """
        try:
            if self.com_port is not None:
                self.com_port.close()
        except Exception:
            pass
        finally:
            self.com_port = None
