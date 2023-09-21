from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, re, enum

class USB_520:
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
            device_sn = self.USB_520_SN[device_sn].value
            
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
        self.close()
        return None
    
    
    def __system_init(self, tear_on_startup:bool = True) -> int:
        self.tear_calibration = 0.0
        if tear_on_startup:
            self.set_tear_calibration()
        return 0
    

    def _serial_connect(self) -> bool:
        try:
            self.serial = bsl_serial(inst.USB_520, self._target_device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
            
        if self.serial.serial_port is None:
            return False
        return self.serial.serial_port.is_open
    

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
        if self.serial is not None:
            self.serial.close()
            del self.serial
        self.logger.success(f"CLOSED - Futek USB DAC.\n\n\n")
        pass