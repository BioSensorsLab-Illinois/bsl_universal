from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import numpy
try:
    import seabreeze.spectrometers as sb
except Exception:
    sb = None
from numpy.typing import NDArray
import time

class HR4000CG:
    CONNECT_RETRY_COUNT = 3
    CONNECT_RETRY_DELAY_SEC = 0.5

    def __init__(self, device_sn:str=None) -> None:
        """
        Initialize and connect an HR4000CG spectrometer.

        Parameters
        ----------
        device_sn : str | None, optional
            Optional serial selector, by default None.
        """
        self.inst = inst.HR4000CG
        self.target_device_sn = device_sn
        self.device_id=""
        self.device_model=""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - SPEC({device_sn})...")
        
        self.__connect_spectrometer()
            
        if self.spec is not None:
            self.logger.device_id = self.device_id
            self.logger.success(f"READY - OceanOptics HR4000CG Spectrometer \"{self.device_id}\"\n\n")
        return None

    def __del__(self, *args, **kwargs) -> None:
        try:
            self.close()
        except Exception:
            pass
        return None

    def __connect_spectrometer(self) -> None:
        """
        - Try to connect to spectrometer based on the s/n provided, if no
        s/n is provided, connect to the next available spectrometer on the bus.

        Raises:
            self.DeviceConnectionFailed: Failed to connect to spectrometer.
        """
        if sb is None:
            self.logger.error("seabreeze is not installed; HR4000CG communication unavailable.")
            raise bsl_type.DeviceConnectionFailed
        self.spec = None
        devices = sb.list_devices()
        if len(devices) == 0:
            self.logger.error(f"Device not found on communication bus.\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        
        self.logger.trace(f"Devices found on bus: {str(devices)}")
        last_error = None
        for attempt in range(1, self.CONNECT_RETRY_COUNT + 1):
            try:
                if self.target_device_sn in (None, ""):
                    self.spec = sb.Spectrometer.from_first_available()
                elif self.target_device_sn in str(devices):
                    self.spec = sb.Spectrometer.from_serial_number(self.target_device_sn)
                else:
                    self.logger.error(
                        f"FAILED - Device[s] found on the bus, but failed to find requested device with s/n: \"{self.target_device_sn}\".\n\n\n"
                    )
                    raise bsl_type.DeviceConnectionFailed
                break
            except Exception as exc:
                last_error = exc
                self.spec = None
                self.logger.warning(
                    f"Connect attempt {attempt}/{self.CONNECT_RETRY_COUNT} failed for HR4000CG."
                )
                time.sleep(self.CONNECT_RETRY_DELAY_SEC)

        if self.spec is None:
            self.logger.error(
                f"FAILED - Device[s] found on the communication bus, but failed to make connection.\n\n\n"
            )
            raise bsl_type.DeviceConnectionFailed from last_error
            
        self.device_id = self.spec.serial_number
        self.device_model = self.spec.model
        return None

    def reconnect(self, device_sn: str | None = None) -> bool:
        """
        Reconnect to spectrometer.

        Parameters
        ----------
        device_sn : str | None, optional
            Optional serial selector override, by default None.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        if device_sn is not None:
            self.target_device_sn = device_sn
        self.close()
        try:
            self.__connect_spectrometer()
            return self.spec is not None
        except Exception:
            return False

    def reset_connection(self) -> bool:
        """
        Reset spectrometer connection using current selector.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        return self.reconnect(device_sn=self.target_device_sn)

    def get_wavelength(self) -> NDArray[numpy.float64]:
        """
        - wavelength array of the spectrometer
        - wavelengths in (nm) corresponding to each pixel of the spectrometer

        Returns
        -------
        wavelengths : `numpy.ndarray`
            wavelengths in (nm)
        """
        return self.spec.wavelengths()

    def get_intensity(self, correct_dark_counts: bool = False, correct_nonlinearity: bool = False) -> NDArray[numpy.float64]:
        """
        - measured intensity array in (a.u.)

        Measured intensities as numpy array returned by the spectrometer.
        The measuring behavior can be adjusted by setting the trigger mode.
        Pixels at the start and end of the array might not be optically
        active so interpret their returned measurements with care. Refer
        to the spectrometer's datasheet for further information.

        Parameters
        ----------
        correct_dark_counts : `bool`
            If requested and supported the average value of electric dark
            pixels on the ccd of the spectrometer is subtracted from the
            measurements to remove the noise floor in the measurements
            caused by non optical noise sources.
        correct_nonlinearity : `bool`
            Some spectrometers store non linearity correction coefficients
            in their eeprom. If requested and supported by the spectrometer
            the readings returned by the spectrometer will be linearized
            using the stored coefficients.

        Returns
        -------
        intensities : `numpy.ndarray`
            measured intensities in (a.u.)
        """
        return self.spec.intensities(correct_dark_counts, correct_nonlinearity)

    def get_spectrum(self, correct_dark_counts:bool=False, correct_nonlinearity:bool=False) -> NDArray[numpy.float64]:
        """
        - returns wavelengths and intensities as single array

        Uses
        ----------
        >>> (wavelengths, intensities) = spec.spectrum()

        Parameters
        ----------
        correct_dark_counts : `bool`
            see `Spectrometer.intensities`
        correct_nonlinearity : `bool`
            see `Spectrometer.intensities`

        Returns
        -------
        spectrum : `numpy.ndarray`
            combined array of wavelengths and measured intensities
        """
        temp = self.spec.spectrum(correct_dark_counts, correct_nonlinearity)
        return self.spec.spectrum(correct_dark_counts, correct_nonlinearity)

    def set_integration_time_micros(self, exp_us:int) -> None:
        """
        - set the integration time in microseconds

        Parameters
        ----------
        integration_time_micros : `int`
            integration time in microseconds
        """
        self.spec.integration_time_micros(exp_us)
        return None

    @property
    def integration_time_limit_us(self) -> 'tuple[int,int]':
        """
        - return the hardcoded minimum and maximum integration time

        Returns
        -------
        integration_time_micros_min_max : `tuple[int, int]`
            min and max integration time in micro seconds
        """
        return self.spec.integration_time_micros_limits
    
    @property
    def device_max_intensity(self) -> float:
        """
        - return the maximum intensity of the spectrometer

        Returns
        -------
        max_intensity : `float`
            the maximum intensity that can be returned by the spectrometer in (a.u.)
            It's possible that the spectrometer saturates already at lower values.
        """
        return self.spec.max_intensity

    @property
    def device_pixel_count(self) -> int:
        """the spectrometer's number of pixels"""
        return self.spec.pixels

    def close(self) -> None:
        """
        Close spectrometer resources safely.
        """
        try:
            spec_obj = getattr(self, "spec", None)
            if spec_obj is not None:
                spec_obj.close()
        except Exception:
            pass
        self.spec = None
        self.logger.success(f"CLOSED - OceanOptics HR4000CG Spectrometer \"{self.device_id}\"\n\n\n")
        return None
