from __future__ import annotations

"""
Robust serial interface wrapper with retry and reconnect behavior.
"""

import platform
import re
import subprocess
import time
from typing import Any, Callable

from loguru import logger

try:
    import serial
    from serial.tools.list_ports import comports
except Exception:
    serial = None

    def comports():
        return []

from ..headers._bsl_inst_info import _bsl_inst_info_list
from ..headers._bsl_type import _bsl_type as bsl_type

try:
    from bsl_universal.core.device_health import device_health_hub
except Exception:
    device_health_hub = None

logger_opt = logger.opt(ansi=True)


class _bsl_serial:
    """
    Serial transport helper used by instrument drivers.

    Parameters
    ----------
    target_inst : _bsl_inst_info_list
        Instrument metadata descriptor.
    device_sn : str, optional
        Optional serial selector for device matching, by default ``""``.
    """

    MAX_CONNECT_RETRY = 3
    MAX_IO_RETRY = 3
    RETRY_DELAY_SEC = 0.2

    def __init__(self, target_inst: _bsl_inst_info_list, device_sn: str = "") -> None:
        """
        Initialize serial transport helper.

        Parameters
        ----------
        target_inst : _bsl_inst_info_list
            Instrument metadata descriptor.
        device_sn : str, optional
            Optional serial selector for device matching, by default ``""``.
        """
        logger_opt.info("    Initiating bsl_serial_service...")
        self.device_id = ""
        self.inst = target_inst
        self.target_device_sn = device_sn
        self.serial_port_name = None
        self.baudrate = self.inst.BAUDRATE if self.inst.BAUDRATE else 9600
        if serial is None:
            self.serial_port = None
            logger_opt.error(
                "pyserial is not installed; serial communication unavailable for {}.",
                self.inst.MODEL,
            )
            return
        self.serial_port = self._connect_serial_device()
        if self.serial_port is None:
            logger_opt.error(
                "<light-blue><italic>{} ({})</italic></light-blue> not found on serial ports.",
                self.inst.MODEL,
                self.target_device_sn,
            )

    def __del__(self) -> None:
        self.close()
        return None

    def _connect_serial_device(self) -> serial.Serial | None:
        """
        Connect to a matching serial device with bounded retries.

        Returns
        -------
        serial.Serial | None
            Open serial object when successful, otherwise ``None``.
        """
        if serial is None:
            return None

        for attempt in range(1, self.MAX_CONNECT_RETRY + 1):
            if self._find_device():
                try:
                    ser = serial.Serial(self.serial_port_name, self.baudrate, timeout=0.1)
                    logger_opt.success(
                        "    {} with DEVICE_ID: <light-blue><italic>{}</italic></light-blue> found and connected!",
                        self.inst.MODEL,
                        self.device_id,
                    )
                    return ser
                except Exception as exc:
                    logger_opt.warning(
                        "Open serial port failed on attempt {}/{}: {}",
                        attempt,
                        self.MAX_CONNECT_RETRY,
                        exc,
                    )
            time.sleep(self.RETRY_DELAY_SEC)
        return None

    def _reconnect(self) -> bool:
        """
        Attempt to restore serial connection.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        if serial is None:
            return False

        try:
            if self.serial_port is not None:
                self.serial_port.close()
        except Exception:
            pass
        self.serial_port = None

        # Fast path: reopen known port and baud first.
        if self.serial_port_name:
            try:
                self.serial_port = serial.Serial(
                    self.serial_port_name,
                    self.baudrate,
                    timeout=0.1,
                )
                return True
            except Exception:
                self.serial_port = None

        # Full rescan fallback.
        self.serial_port = self._connect_serial_device()
        return self.serial_port is not None

    def _find_device(self) -> bool:
        """
        Search COM ports for a matching instrument.

        Returns
        -------
        bool
            True if a candidate device is found and validated.
        """
        if serial is None:
            return False

        com_ports_list = list(comports())
        logger_opt.trace("    Devices found on bus: {}", [p[0] for p in com_ports_list])

        for port in com_ports_list:
            temp_port = None

            if self.inst.SERIAL_SN in port[0]:
                logger_opt.info(
                    "    Specified device <light-blue><italic>{}</italic></light-blue> with Serial SN <light-blue><italic>{}</italic></light-blue> found on port <light-blue><italic>{}</italic></light-blue> by Device Serial SN search.",
                    self.inst.MODEL,
                    self.inst.SERIAL_SN,
                    port[0],
                )
                temp_port = port[0]

            if self.target_device_sn and self.target_device_sn in port[0]:
                self.device_id = port[0]
                logger_opt.info(
                    "    Specified device <light-blue><italic>{}</italic></light-blue> with Serial SN <light-blue><italic>{}</italic></light-blue> found on port <light-blue><italic>{}</italic></light-blue> by Device Serial SN search.",
                    self.inst.MODEL,
                    self.target_device_sn,
                    port[0],
                )
                temp_port = port[0]

            if self.inst.SERIAL_NAME in port[1]:
                logger_opt.info(
                    "    Specified device <light-blue><italic>{}</italic></light-blue> with Serial_Name <light-blue><italic>{}</italic></light-blue> found on port <light-blue><italic>{}</italic></light-blue> by Device name search.",
                    self.inst.MODEL,
                    self.inst.SERIAL_NAME,
                    port[0],
                )
                temp_port = port[0]

            if (self.inst.USB_PID in port[2]) or (self._hex_to_dec(self.inst.USB_PID) in port[2]):
                logger_opt.info(
                    "    Specified device <light-blue><italic>{}</italic></light-blue> with USB_PID: <light-blue><italic>{}</italic></light-blue> found on port <light-blue><italic>{}</italic></light-blue> by USB_PID search.",
                    self.inst.MODEL,
                    self.inst.USB_PID,
                    port[0],
                )
                temp_port = port[0]

            if temp_port is not None:
                found_port, baudrate = self._check_device_resp(temp_port)
                if found_port is not None:
                    self.baudrate = baudrate
                    self.serial_port_name = found_port
                    return True

        if self.target_device_sn and self.inst.MODEL == "USB_520":
            logger_opt.error(
                "<light-blue><italic>{} ({})</italic></light-blue> not found on serial ports.",
                self.inst.MODEL,
                self.target_device_sn,
            )
            raise bsl_type.DeviceConnectionFailed

        logger.warning("    No device found based on USB_PID/VID or Serial Name search!")

        # Full brute-force probe fallback.
        for port in com_ports_list:
            found_port, baudrate = self._check_device_resp(port[0])
            if found_port is not None:
                self.baudrate = baudrate
                self.serial_port_name = found_port
                return True
        return False

    def _hex_to_dec(self, value: str) -> str:
        """
        Convert hex string to decimal string.

        Parameters
        ----------
        value : str
            Hexadecimal string.

        Returns
        -------
        str
            Decimal representation or empty string on failure.
        """
        try:
            return str(int(value, 16))
        except Exception:
            return ""

    def _check_device_resp(self, temp_port: str) -> tuple[str | None, int | None]:
        """
        Probe a serial port for expected identification response.

        Parameters
        ----------
        temp_port : str
            Candidate serial port path.

        Returns
        -------
        tuple[str | None, int | None]
            Matched port and baudrate on success, otherwise ``(None, None)``.
        """
        if serial is None:
            return None, None

        if self.inst.BAUDRATE != 0:
            baudrates = [self.inst.BAUDRATE]
        else:
            baudrates = [4800, 9600, 19200, 28800, 38400, 115200]

        if not self.is_port_free(temp_port):
            logger_opt.warning(
                "    BUSY - Device <light-blue><italic>{}</italic></light-blue> is busy, moving to next available device...",
                temp_port,
            )
            return None, None

        try:
            for baudrate in baudrates:
                logger_opt.info(
                    "    Inquiring serial port <light-blue><italic>{}</italic></light-blue> with Baudrate={}",
                    temp_port,
                    baudrate,
                )
                with serial.Serial(temp_port, baudrate, timeout=0.1) as device:
                    logger_opt.trace(
                        "        Connected to <light-blue><italic>{}</italic></light-blue> on port <light-blue><italic>{}</italic></light-blue>",
                        device.name,
                        temp_port,
                    )
                    if self.inst.QUERY_CMD != "N/A":
                        device.reset_input_buffer()
                        device.write(bytes(self.inst.QUERY_CMD, "utf-8"))
                        logger_opt.trace(
                            "        Query <light-blue><italic>{}</italic></light-blue> sent to <light-blue><italic>{}</italic></light-blue>",
                            repr(self.inst.QUERY_CMD),
                            device.name,
                        )
                        time.sleep(0.5)
                    try:
                        resp = repr(device.read(100).decode("utf-8")).strip("\n\r")
                    except Exception:
                        resp = "ERROR in interpreting as UTF-8."
                    logger_opt.trace(
                        "        Response from <light-blue><italic>{}</italic></light-blue>: {}",
                        device.name,
                        resp,
                    )

                    if self.inst.QUERY_E_RESP in resp:
                        if self.inst.QUERY_SN_CMD == "N/A":
                            return temp_port, baudrate

                        logger_opt.info(
                            "        <light-blue><italic>{}</italic></light-blue> found on serial bus on port <light-blue><italic>{}</italic></light-blue>.",
                            self.inst.MODEL,
                            temp_port,
                        )
                        device.reset_input_buffer()
                        device.write(bytes(self.inst.QUERY_SN_CMD, "utf-8"))
                        time.sleep(0.5)
                        resp = device.read(100).decode("utf-8").strip("\n\r")
                        logger_opt.trace(
                            "        Response from <light-blue><italic>{}</italic></light-blue>: {}",
                            device.name,
                            resp,
                        )
                        match = re.search(self.inst.SN_REG, resp)
                        device_id = match.group(0) if match is not None else "UNKNOWN"
                        if self.target_device_sn in device_id or not self.target_device_sn:
                            self.device_id = device_id.strip("\r\n")
                            return temp_port, baudrate
                        logger_opt.warning(
                            "    S/N Mismatch - Device <light-blue><italic>{}</italic></light-blue> with S/N <light-blue><italic>{}</italic></light-blue> found, not <light-blue><italic>{}</italic></light-blue> as requested, moving to next available device...",
                            temp_port,
                            device_id,
                            self.target_device_sn,
                        )
                        break
        except Exception:
            logger_opt.warning(
                "    BUSY - Device <light-blue><italic>{}</italic></light-blue> is busy, moving to next available device...",
                temp_port,
            )
            return None, None
        return None, None

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
        Execute an operation with reconnect retries.

        Parameters
        ----------
        operation_name : str
            Label used for logs and failure reports.
        callback : Callable[[], Any]
            Operation callback.

        Returns
        -------
        Any
            Callback return value.

        Raises
        ------
        bsl_type.DeviceOperationError
            If retries are exhausted.
        """
        serial_errors = (OSError, AttributeError, UnicodeDecodeError)
        if serial is not None:
            serial_errors = (serial.SerialException,) + serial_errors

        for attempt in range(1, self.MAX_IO_RETRY + 1):
            if self.serial_port is None and not self._reconnect():
                time.sleep(self.RETRY_DELAY_SEC)
                continue
            try:
                return callback()
            except serial_errors as exc:
                logger_opt.warning(
                    "Serial {} attempt {}/{} failed for {}: {}",
                    operation_name,
                    attempt,
                    self.MAX_IO_RETRY,
                    self.inst.MODEL,
                    exc,
                )
                self._reconnect()
                time.sleep(self.RETRY_DELAY_SEC)

        message = (
            f"{self.inst.MODEL} serial {operation_name} failed after "
            f"{self.MAX_IO_RETRY} attempts."
        )
        logger_opt.error(message)
        self._report_unrecoverable_failure(message)
        raise bsl_type.DeviceOperationError(message)

    def readline(self) -> str:
        """
        Read one line from the serial stream.

        Returns
        -------
        str
            UTF-8 decoded line with trailing CR/LF removed.
        """
        def _run() -> str:
            resp = self.serial_port.readline().decode("utf-8")
            logger_opt.trace(
                "        {} - com-Serial - Resp from {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(resp),
            )
            return resp.strip("\n\r")

        return self._run_with_reconnect("readline", _run)

    def read(self, n_bytes: int) -> str:
        """
        Read fixed number of bytes from the serial stream.

        Parameters
        ----------
        n_bytes : int
            Number of bytes to read.

        Returns
        -------
        str
            UTF-8 decoded payload with trailing CR/LF removed.
        """
        def _run() -> str:
            resp = self.serial_port.read(n_bytes).decode("utf-8")
            logger_opt.trace(
                "        {} - com-Serial - Resp from {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(resp),
            )
            return resp.strip("\n\r")

        return self._run_with_reconnect("read", _run)

    def read_all(self) -> bytes:
        """
        Read all currently buffered bytes.

        Returns
        -------
        bytes
            Buffered payload with surrounding whitespace removed.
        """
        def _run() -> bytes:
            resp = self.serial_port.read_all()
            logger_opt.trace(
                "        {} - com-Serial - Resp from {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(resp),
            )
            return resp.strip()

        return self._run_with_reconnect("read-all", _run)

    def write(self, msg: str) -> int:
        """
        Write bytes to serial stream.

        Parameters
        ----------
        msg : str
            Payload string to write.

        Returns
        -------
        int
            Number of bytes written.
        """
        def _run() -> int:
            logger_opt.trace(
                "        {} - com-Serial - Write to {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(msg),
            )
            return self.serial_port.write(bytes(msg, "utf-8"))

        return self._run_with_reconnect("write", _run)

    def writeline(self, msg: str) -> int:
        """
        Write a CRLF-terminated line to serial stream.

        Parameters
        ----------
        msg : str
            Line payload (without CRLF).

        Returns
        -------
        int
            Number of bytes written.
        """
        def _run() -> int:
            line = msg + "\r\n"
            logger_opt.trace(
                "        {} - com-Serial - Write to {} with {}",
                self.inst.MODEL,
                self.inst.MODEL,
                repr(line),
            )
            return self.serial_port.write(bytes(line, "utf-8"))

        return self._run_with_reconnect("writeline", _run)

    def query(self, cmd: str) -> str:
        """
        Execute a write/read query cycle.

        Parameters
        ----------
        cmd : str
            Command payload written as a line.

        Returns
        -------
        str
            Device response line.
        """
        def _run() -> str:
            self.serial_port.reset_input_buffer()
            line = cmd + "\r\n"
            self.serial_port.write(bytes(line, "utf-8"))
            resp = self.serial_port.readline().decode("utf-8")
            return resp.strip("\n\r")

        return self._run_with_reconnect("query", _run)

    def flush_read_buffer(self) -> None:
        """
        Clear incoming serial buffer.
        """
        def _run() -> None:
            self.serial_port.reset_input_buffer()

        self._run_with_reconnect("flush", _run)

    def set_serial_timeout(self, timeout: int) -> None:
        """
        Set serial read timeout in seconds.

        Parameters
        ----------
        timeout : int
            Timeout in seconds.
        """
        def _run() -> None:
            self.serial_port.timeout = timeout

        self._run_with_reconnect("set-timeout", _run)

    def is_port_free(self, port_name: str) -> bool:
        """
        Check whether a serial port is available on macOS.

        Parameters
        ----------
        port_name : str
            Full path to the serial device, e.g. ``/dev/tty.usbserial``.

        Returns
        -------
        bool
            True when the port appears free.
        """
        if platform.system() != "Darwin":
            return True

        try:
            result = subprocess.run(
                ["lsof", port_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if port_name in result.stdout:
                return False
            return True
        except Exception as exc:
            logger_opt.warning("Port availability check failed for {}: {}", port_name, exc)
            return True

    def close(self) -> None:
        """
        Close the serial port safely.
        """
        try:
            if self.serial_port is not None:
                self.serial_port.close()
        except Exception:
            pass
        finally:
            self.serial_port = None
