from ..interfaces._bsl_visa import _bsl_visa as bsl_visa
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

import time, sys

class DC2200:
    def __init__(self, device_sn:str="") -> None:
        self.inst = inst.DC2200
        self.device_id=""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - DC2200({device_sn})...")
        if self._com_connect(device_sn):
            self.logger.device_id = self.device_id
            self.run_update_power_meter()
            self.logger.success(f"READY - Thorlab DC2200 LED Controller \"{self.device_id}\" with LED \"{self.get_LED_id()}\".\n\n\n")
        else:
            self.logger.error(f"FAILED to connect to Thorlab DC2200 ({device_sn}) LED Controller!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None

    def _com_connect(self, device_sn:str) -> bool:
        try:
            self._com = bsl_visa(inst.DC2200, device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
            sys.exit(-1)
        if self._com is None:
            if self._com.com_port is None:
                return False
        self.device_id = self._com.device_id
        return True
    
    # def _check_operation_complete(self) -> bool:
    #     """
    #     - Check if the instrument finished executing previous commands.

    #     Returns
    #     --------
    #     ready : `bool`
    #         'True' indicates instrument is free and ready for new commands.
    #     """

    def _reset_controller(self) -> None:
        """
        - Performs a reset of the LED controller.
        """
        self._com.write("*RST")
        self.logger.info(f"LED Controller is Reset to initial states.")


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
        self._com.write("OUTPut:TERMinal 1")
        self.logger.info(f"Terminal set to: LED1.")
        self._com.write("OUTPut:STATe OFF")
        self.logger.info(f"LED1 state set to OFF.")

    def set_LED2_OFF(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut:TERMinal 2")
        self.logger.info(f"Terminal set to: LED2.")
        self._com.write("OUTPut:STATe OFF")
        self.logger.info(f"LED2 state set to OFF.")

    def set_LED1_ON(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut:TERMinal 1")
        self.logger.info(f"Terminal set to: LED1.")
        self._com.write("OUTPut:STATe ON")
        self.logger.info(f"LED1 state set to ON.")

    def set_LED2_ON(self) -> None:
        """
        - Turn off the output of LED1.
        """
        self._com.write("OUTPut:TERMinal 2")
        self.logger.info(f"Terminal set to: LED2.")
        self._com.write("OUTPut:STATe ON")
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
        self._com.write("OUTPut:TERMinal 1")
        self.logger.info(f"Terminal set to: LED1.")
        self._com.write("SOURce:MODe CC")
        self.logger.info(f"LED1's mode set to Constant Current Mode.")
            
    def get_LED_id(self) -> str:
        """
        - Get the sensor_id from the LED Controller.

        Returns
        --------
        sensor_id : `str`
            Sensor ID of the currently connected sensor.
        """
        sensor_id = self._com.query("SYST:SENS:IDN?").split(",")[0]
        self.logger.info(f"Current connected sensor: {sensor_id}.")
        return sensor_id

    def close(self) -> None:
        if self._com is not None:
            self._com.close()
            del self._com
        self.logger.info(f"CLOSED - Thorlab DC2200 LED Controller \"{self.device_id}\"\n\n\n")
        pass
