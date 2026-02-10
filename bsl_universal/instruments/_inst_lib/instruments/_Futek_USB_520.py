from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, re, enum

class USB_520:
    CONNECT_RETRY_COUNT = 3
    CONNECT_RETRY_DELAY_SEC = 0.5

    class USB_520_SN(enum.Enum):
        CH1 = '1066656'; CH2 = '1066657'; CH3 = '1066658'; CH4 = '1066659'

    def __init__(self, device_sn='', tear_on_startup:bool = True, reverse_negative:bool = True) -> None:
        """
        Read the latest force measurement from the device in grams.

        Parameters
        ----------
        device_sn : `str`, optional
            The serial number of the device to connect to. 
            If not specified, the first available device will be connected.
        
        tear_on_startup : `bool`, optional
            If True, the tear calibration will be performed on startup.
            The default is True.
        
        reverse_negative : `bool`, optional
            If True, the force reading will be reversed for positive values.
            The default is True.
            
        Returns
        -------
        status : `int`
            0 if successful, otherwise raise an exception.
        """
        if "CH" in device_sn:
            try:
                device_sn = self.USB_520_SN[device_sn].value
            except KeyError as exc:
                raise bsl_type.DeviceConnectionFailed(
                    f"Unknown USB_520 channel alias: {device_sn}"
                ) from exc
            
        self._target_device_sn = device_sn
        self.inst = inst.USB_520
        self.flip_result = reverse_negative
        self.device_id = ""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - Futek USB_520({device_sn})...")

        self.serial = None
        if self._target_device_sn != "":
            if self._serial_connect():
                self.logger.device_id = self.serial.device_id.split('-')[-1]
                self.__system_init(tear_on_startup)
                self.logger.success(f"READY - Futek USB DAC.\n\n\n")
                return None
            self.logger.error(f"FAILED to connect to Futek USB DAC!\n\n\n")
            raise bsl_type.DeviceConnectionFailed

        for target_sn in self.USB_520_SN:
            target_sn = target_sn.value
            self._target_device_sn = target_sn
            if self._serial_connect():
                self.logger.device_id = self.serial.device_id.split('-')[-1]
                self.__system_init(tear_on_startup)
                self.logger.success(f"READY - Futek USB DAC.\n\n\n")
                return None
        
        self.logger.error(f"FAILED to connect to Futek USB DAC!\n\n\n")
        raise bsl_type.DeviceConnectionFailed

    def __del__(self, *args, **kwargs) -> None:
        try:
            self.close()
        except Exception:
            pass
        return None
    
    
    def __system_init(self, tear_on_startup:bool = True) -> int:
        self.tear_calibration = 0.0
        if tear_on_startup:
            self.set_tear_calibration()
        return 0
    

    def _serial_connect(self) -> bool:
        """
        Connect to USB-520 serial interface with bounded retries.

        Returns
        -------
        bool
            True when connection succeeds.
        """
        self.serial = None
        last_error = None
        for attempt in range(1, self.CONNECT_RETRY_COUNT + 1):
            try:
                candidate = bsl_serial(inst.USB_520, self._target_device_sn)
                if candidate is None or getattr(candidate, "serial_port", None) is None:
                    raise bsl_type.DeviceConnectionFailed("No serial communication port found.")
                if not candidate.serial_port.is_open:
                    raise bsl_type.DeviceConnectionFailed("Serial port is not open.")
                self.serial = candidate
                return True
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    f"Connection attempt {attempt}/{self.CONNECT_RETRY_COUNT} failed: {type(exc)}"
                )
                time.sleep(self.CONNECT_RETRY_DELAY_SEC)
        self.logger.error(f"Unable to connect USB_520 after retries: {repr(last_error)}")
        return False

    def reconnect(self, device_sn: str = "", tear_on_startup: bool = False) -> bool:
        """
        Reconnect to USB-520 device.

        Parameters
        ----------
        device_sn : str, optional
            Optional serial selector override, by default ``""``.
        tear_on_startup : bool, optional
            Run tare calibration after reconnect, by default False.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        if device_sn:
            self._target_device_sn = device_sn
        self.close()
        if not self._serial_connect():
            return False
        self.__system_init(tear_on_startup=tear_on_startup)
        return True

    def reset_tear_calibration(self, average_count: int = 10) -> bool:
        """
        Re-run tare calibration from fresh measurements.

        Parameters
        ----------
        average_count : int, optional
            Number of samples for tare averaging, by default 10.

        Returns
        -------
        bool
            True when calibration succeeds.
        """
        try:
            self.set_tear_calibration(average_count=average_count)
            return True
        except Exception as exc:
            self.logger.error(f"Failed to reset USB_520 tare calibration: {type(exc)}")
            return False
    

    def __extract_float(self, msg:str) -> float:
        match = re.search(r'([+-]?\d+\.\d+)\s*g', msg)
        if match:
            return float(match.group(1))
        else:
            self.logger.warning("Unable to find a force reading! please check the device.")
            return 999
    
    
    def get_new_measurement(self, timeout_ms:int = 10000, enable_tear:bool = True) -> float:
        """
        Read the latest force measurement from the device in grams.

        Parameters
        ----------
        timeout_ms : `int`, optional
            The timeout in milliseconds for the measurement to be read back from the device. 
            The default is 10000ms.

        enable_tear : `bool`, optional
            If True, the tear calibration value will be subtracted from the measurement.
            The default is True.
        
        Returns
        -------
        force : `float`
            The force value in grams read back from the sensor.
        """
        self.serial.serial_port.timeout = (timeout_ms/1000)
        self.serial.flush_read_buffer()
        msg = ""
        start = time.time()

        self.logger.debug("Waiting for new measurement...")
        while ("g" not in msg) and ((time.time()-start) < (timeout_ms/1000)):
            msg = self.serial.readline()
            if "g" in msg:
                self.logger.debug(f"New measurement received: {msg}")
                force = self.__extract_float(msg)
                if force == 999:
                    msg = ""
                    self.logger.warning("Retrying...")
                    pass
                else:
                    if self.flip_result:
                        force *= -1
                    if enable_tear:
                        force -= self.tear_calibration
                    return force

        self.logger.warning(f"Timeout! No new measurement received in {timeout_ms}ms.")
        raise bsl_type.DeviceTimeOutError
    
    
    def set_tear_calibration(self, average_count:int=10) -> float:
        """
        Read new force measurements and set it as the tear calibration value.
        
        Parameters
        ----------
        average_count : `int`, optional
            The number of measurements to average for the calibration.

        Returns
        -------
        force : `float`
            The force value in grams for the calibration.
        """
        self.logger.debug("Setting tear calibration...")
        count = 0
        sum = 0.0
        while (count < average_count):
            sum += self.get_new_measurement(enable_tear=False)
            count += 1
        self.tear_calibration = sum/count
        self.logger.success(f"Tear calibration set to {self.tear_calibration} grams.")
        return self.tear_calibration
    

    def close(self) -> None:
        """
        Close USB-520 communication resources safely.
        """
        serial_obj = getattr(self, "serial", None)
        if serial_obj is not None:
            try:
                serial_obj.close()
            except Exception:
                pass
            self.serial = None
        self.logger.success(f"CLOSED - Futek USB DAC.\n\n\n")
        pass
