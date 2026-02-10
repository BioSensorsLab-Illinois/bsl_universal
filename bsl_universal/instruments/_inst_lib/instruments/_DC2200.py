from ..interfaces._bsl_visa import _bsl_visa as bsl_visa
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

import time

class DC2200:
    CONNECT_RETRY_COUNT = 3
    CONNECT_RETRY_DELAY_SEC = 0.5

    def __init__(self, device_sn:str="") -> None:
        """
        Initialize and connect a DC2200 LED controller.

        Parameters
        ----------
        device_sn : str, optional
            Optional serial selector, by default ``""``.
        """
        self.inst = inst.DC2200
        self.device_id=""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - DC2200({device_sn})...")
        if self._com_connect(device_sn):
            self.logger.device_id = self.device_id
            self.logger.success(f"READY - Thorlab DC2200 LED Controller \"{self.device_id}\"\".\n\n\n")
            self._reset_controller()
        else:
            self.logger.error(f"FAILED to connect to Thorlab DC2200 ({device_sn}) LED Controller!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    def __del__(self, *args, **kwargs) -> None:
        try:
            self.close()
        except Exception:
            pass
        return None

    def _com_connect(self, device_sn:str) -> bool:
        """
        Connect to DC2200 with bounded retries.

        Parameters
        ----------
        device_sn : str
            Optional serial selector.

        Returns
        -------
        bool
            True when connection succeeds.
        """
        self._com = None
        last_error = None
        for attempt in range(1, self.CONNECT_RETRY_COUNT + 1):
            try:
                candidate = bsl_visa(inst.DC2200, device_sn)
                if candidate is None or getattr(candidate, "com_port", None) is None:
                    raise bsl_type.DeviceConnectionFailed("No VISA communication port found.")
                self._com = candidate
                self.device_id = getattr(candidate, "device_id", "")
                return True
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    f"Connection attempt {attempt}/{self.CONNECT_RETRY_COUNT} failed: {type(exc)}"
                )
                time.sleep(self.CONNECT_RETRY_DELAY_SEC)
        self.logger.error(f"Unable to connect DC2200 after retries: {repr(last_error)}")
        return False

    def reconnect(self, device_sn: str = "", reset_controller: bool = False) -> bool:
        """
        Reconnect to the DC2200 controller.

        Parameters
        ----------
        device_sn : str, optional
            Optional serial selector, by default ``""``.
        reset_controller : bool, optional
            Reset controller state after reconnect, by default False.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        self.close()
        connected = self._com_connect(device_sn)
        if connected and reset_controller:
            self._reset_controller()
        return connected


    def _reset_controller(self) -> None:
        """
        - Performs a reset of the LED controller.
        """
        self._com.write("*RST")
        self.logger.info(f"LED Controller is Reset to initial states.")

    def reset_controller(self) -> bool:
        """
        Reset LED controller to default state.

        Returns
        -------
        bool
            True when reset succeeds.
        """
        try:
            self._reset_controller()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to reset DC2200: {type(exc)}")
            return False


    def get_screen_brightness(self) -> int:
        """
        - Get current on-boadr touch screen brightness in percentage.

        Returns
        --------
        brightness : `int`
            0 - 100 percent of current screen brightness.
        """
        brightness = int(float(self._com.query("DISPlay:BRIGhtness?"))*100)
        self.logger.info(f"Current screen brightness: {brightness}.")
        return brightness
    

    def set_screen_brightness(self, brightness:int) -> int:
        """
        - Set the on-boadr touch screen brightness in percentage from 0 to 100.

        Parameter
        --------
        brightness : `int`
            0 - 100 percent of current screen brightness.
        
        Returns
        --------
        brightness_readback : `int`
            0 - 100 percent of current screen brightness readback.
        """
        assert(brightness>=0 and brightness<=100)
        self._com.write("DISPlay:BRIGhtness %f" % (brightness/100))
        self.logger.info(f"Screen set to: {brightness}%.")
        brightness = int(float(self._com.query("DISPlay:BRIGhtness?"))*100)
        self.logger.info(f"Current screen brightness: {brightness}%.")
        return brightness
    

    def set_LED1_OFF(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut1:STATe OFF")
        self.logger.info(f"LED1 state set to OFF.")


    def set_LED2_OFF(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut2:STATe OFF")
        self.logger.info(f"LED2 state set to OFF.")


    def set_LED1_ON(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut1:STATe ON")
        self.logger.info(f"LED1 state set to ON.")


    def set_LED2_ON(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut2:STATe ON")
        self.logger.info(f"LED2 state set to ON.")


    def set_LED1_constant_current(self, current_mA:float) -> None:
        """
        - Set the LED1 to Constant Current mode with specified current setting.

        Parameter
        --------
        current_mA : `float`
            Desired current output in mA.
        """
        self.set_LED1_OFF()
        self._com.write("SOURce1:MODe CC")
        self.logger.info(f"LED1's mode set to Constant Current Mode.")
        self._com.write(f"SOURCE1:CCURENT:CURRENT {(current_mA/1000):.2f}")
        self.logger.info(f"LED1's output current set to {current_mA}mA")
        self.set_LED1_ON()


    def set_LED2_constant_current(self, current_mA:float) -> None:
        """
        - Set the LED1 to Constant Current mode with specified current setting.

        Parameter
        --------
        current_mA : `float`
            Desired current output in mA.
        """
        self.set_LED2_OFF()
        self._com.write("SOURce2:MODe CC")
        self.logger.info(f"LED2's mode set to Constant Current Mode.")
        self._com.write(f"SOURCE2:CCURENT:CURRENT {(current_mA/1000):.2f}")
        self.logger.info(f"LED2's output current set to {current_mA}mA")
        self.set_LED2_ON()

    def set_LED1_constant_brightness(self, percent:float) -> None:
        """
        - Set the LED1 to Constant Brightness mode with specified limit setting in 
            percentage from 0 to 100%.

        Parameter
        --------
        percent : `float`
            Desired brightness output in %Limit.
        """
        self.set_LED1_OFF()
        self._com.write("SOURce1:MODe CB")
        self.logger.info(f"LED1's mode set to Constant Brightness Mode.")
        self._com.write(f"SOURCE1:CBRightness:BRIGhtness {(percent):.2f}")
        self.logger.info(f"LED1's output brightness set to {percent}% of maximum limit.")
        self.set_LED1_ON()

    def set_LED2_constant_brightness(self, percent:float) -> None:
        """
        - Set the LED2 to Constant Brightness mode with specified limit setting in 
            percentage from 0 to 100%.

        Parameter
        --------
        percent : `float`
            Desired brightness output in %Limit.
        """
        self.set_LED2_OFF()
        self._com.write("SOURce2:MODe CB")
        self.logger.info(f"LED2's mode set to Constant Brightness Mode.")
        self._com.write(f"SOURCE2:CBRightness:BRIGhtness {(percent):.2f}")
        self.logger.info(f"LED2's output brightness set to {percent}% of maximum limit.")
        self.set_LED2_ON()

    def set_LED1_PWM(self, current_mA:float, frequency:float, duty_cycle:float, count:int=0) -> None:
        """
        - Set the LED1 to PWM mode with specified current in mA, switching frequency, duty_cycle in 
        percentage, and pulse counts.

        Parameter
        --------
        current_mA : `float`
            Desired current output in mA.

        frequency : `float`
            Desired PWM switching frequency in Hz.

        duty_cycle : 'float'
            Desired PWM Duty cycles.
        
        count : 'int' (default to 0)
            Desired pulse count, set to 0 for continuous operation
        """
        self.set_LED1_OFF()
        self._com.write("SOURce1:MODe PWM")
        self.logger.info(f"LED1's mode set to PWM Mode.")
        self._com.write(f"SOURCE1:PWM:CURRent {(current_mA/1000):.2f}")
        self.logger.info(f"LED1's output current set to {current_mA}mA.")
        self._com.write(f"SOURCE1:PWM:FREQency {frequency}.")
        self.logger.info(f"LED1's PWM frequency set to {frequency}Hz.")
        self._com.write(f"SOURCE1:PWM:DCYCle {duty_cycle}")
        self.logger.info(f"LED1's PWM Duty cycle set to {duty_cycle:.2f}%.")
        self._com.write(f"SOURCE1:PWM:COUNt {count}")
        self.logger.info(f"LED1's PWM pulse count set to {count}.")
        self.set_LED1_ON()

    def set_LED2_PWM(self, current_mA:float, frequency:float, duty_cycle:float, count:int=0) -> None:
        """
        - Set the LED2 to PWM mode with specified current in mA, switching frequency, duty_cycle in 
        percentage, and pulse counts.

        Parameter
        --------
        current_mA : `float`
            Desired current output in mA.

        frequency : `float`
            Desired PWM switching frequency in Hz.

        duty_cycle : 'float'
            Desired PWM Duty cycles.
        
        count : 'int' (default to 0)
            Desired pulse count, set to 0 for continuous operation
        """
        self.set_LED2_OFF()
        self._com.write("SOURce2:MODe PWM")
        self.logger.info(f"LED2's mode set to PWM Mode.")
        self._com.write(f"SOURCE2:PWM:CURRent {(current_mA/1000):.2f}")
        self.logger.info(f"LED2's output current set to {current_mA}mA.")
        self._com.write(f"SOURCE2:PWM:FREQency {frequency}.")
        self.logger.info(f"LED2's PWM frequency set to {frequency}Hz.")
        self._com.write(f"SOURCE2:PWM:DCYCle {duty_cycle}")
        self.logger.info(f"LED2's PWM Duty cycle set to {duty_cycle:.2f}%.")
        self._com.write(f"SOURCE2:PWM:COUNt {count}")
        self.logger.info(f"LED2's PWM pulse count set to {count}.")
        self.set_LED2_ON()

    # def get_LED_id(self) -> str:
    #     """
    #     - Get the sensor_id from the LED Controller.

    #     Returns
    #     --------
    #     sensor_id : `str`
    #         Sensor ID of the currently connected sensor.
    #     """
    #     sensor_id = self._com.query("SYST:SENS:IDN?").split(",")[0]
    #     self.logger.info(f"Current connected sensor: {sensor_id}.")
    #     return sensor_id


    def close(self) -> None:
        """
        Close DC2200 communication resources safely.
        """
        com_obj = getattr(self, "_com", None)
        if com_obj is not None:
            try:
                com_obj.close()
            except Exception:
                pass
            self._com = None
        self.logger.info(f"CLOSED - Thorlab DC2200 LED Controller \"{self.device_id}\"\n\n\n")
        pass
