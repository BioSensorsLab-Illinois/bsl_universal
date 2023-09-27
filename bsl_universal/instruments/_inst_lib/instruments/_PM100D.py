from ..interfaces._bsl_visa import _bsl_visa as bsl_visa
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, sys

class PM100D:
    def __init__(self, device_sn:str="") -> None:
        self.inst = inst.PM100D
        self.device_id=""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - PM100D({device_sn})...")
        if self._com_connect(device_sn):
            self.logger.device_id = self.device_id
            self.run_update_power_meter()
            self.logger.success(f"READY - Thorlab PM100D Power Meter \"{self.device_id}\" with sensor \"{self.get_sensor_id()}\".\n\n\n")
        else:
            self.logger.error(f"FAILED to connect to Thorlab PM100D ({device_sn}) Power Meter!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None

    def _com_connect(self, device_sn:str) -> bool:
        try:
            self._com = bsl_visa(inst.PM100D, device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
            sys.exit(-1)
        if self._com is None:
            if self._com.com_port is None:
                return False
        self.device_id = self._com.device_id
        return True

    def run_update_power_meter(self) -> None:
        """
        - Performs an update to all relevent power meter parameters.

        - Enable info level loggging to see each query results.
        """
        self.get_preset_wavelength()
        self.get_attenuation_dB()
        self.get_average_count()
        self.get_measured_power()
        self.get_power_measuring_range()
        self.get_auto_range_status()
        self.get_measured_frequency()
        self.get_zero_magnitude()
        self.get_zero_state()
        self.get_photodiode_response()
        self.get_current_range()
        self.get_sensor_id()
        self.get_measured_current()
        pass

    def run_zero(self) -> None:
        """
        - Zero the power meter.
        """
        resp = self._com.write("SENS:CORR:COLL:ZERO:INIT")
        time.sleep(0.2)
        self.logger.info("Power Meter Zeroed.")
        return None

    def get_preset_wavelength(self) -> float:
        """
        - Get preset wavelength of interest for power measurement 
        from the power meter.

        Returns
        --------
        wavelength : `float`
            Preset wavelength of interest for power measurement.
        """
        try_count = 0
        while True:
            try:
                wavelength = float(self._com.query("SENS:CORR:WAV?"))
                self.logger.info( f"Current preset wavelenght: {repr(wavelength)}nm")
                break
            except:
                if try_count > 9:
                    self.logger.error("FAILED to acquire wavelength.")
                    raise bsl_type.DeviceOperationError
                else:
                    time.sleep(0.1)  #take a rest..
                    try_count = try_count + 1
                    self.logger.warning("timeout - Trying to get the wavelength again..")
        return wavelength
    
    def set_preset_wavelength(self, wl:float) -> float:
        """
        - Set preset wavelength of interest for power measurement 
        from the power meter.

        Parameters
        ----------
        wl : `float`
            Wavelength of interest for power measurement.

        Returns
        --------
        wavelength : `float`
            Preset wavelength of interest for power measurement readback
            from the power meter.
        """
        try_count = 0
        while True:
            try:
                self._com.write("SENS:CORR:WAV %f" % wl)
                time.sleep(0.005) # Sleep for 5 ms before rereading the wl.
                self.logger.info(f"Wavelength set to {wl:.1f}nm")
                break
            except:
                if try_count > 9:
                    self.logger.error( "Failed to set wavelength." )
                    raise bsl_type.DeviceOperationError
                else:
                    time.sleep(0.1)  #take a rest..
                    try_count = try_count + 1
                    self.logger.warning( "Timeout - trying to set wavelength again.." )

        return self.get_preset_wavelength()
    
    def get_attenuation_dB(self) -> float:
        """
        - Get current dB attenuation from the power meter.

        Returns
        --------
        att_dB : `float`
            Current dB attenuation of the power meter.
        """
        # in dB (range for 60db to -60db) gain or attenuation, default 0 dB
        attenuation_dB = float( self._com.query("SENS:CORR:LOSS:INP:MAGN?") )
        self.logger.info(f"Current attenuation at {attenuation_dB}dB.")
        return attenuation_dB

    def get_average_count(self) -> int:
        """
        - Get measurments count for each power measurement. 

        - Each measurement is approximately 3 ms.

        Returns
        --------
        count : `int`
            Number of measurements made for each power measurement,
            the result is the average of all measurements.
        """
        average_count = int( self._com.query("SENS:AVER:COUNt?") )
        self.logger.info( f"Current average count: {average_count}.")
        return average_count
    
    def set_average_count(self, cnt:int) -> int:
        """
        - Set measurments count for each power measurement,
        the final power measurement is the average of all 
        measured attempts. 

        - Each measurement is approximately 3 ms.

        parameter
        --------
        cnt : `int`
            Number of measurements made for each power measurement,
            the result is the average of all measurements.
        """
        self._com.write("SENS:AVER:COUNT %i" % cnt)
        self.logger.info(f"Average count is set to {cnt}.")
        return self.get_average_count()
            
    def get_measured_power(self) -> float:
        """
        - Get one power measurement form the power meter 
        with amount of `average_count` individual measurements.
        The final result is the average of all of theindividual 
        measurements.

        - Each measurement is approximately `3 * average_count`ms.

        Returns
        --------
        power : `float`
            The average of all of theindividual measurements.
        """
        power = float(self._com.query("MEAS:POW?"))
        self.logger.info(f"Current Power measured: {power*1000:.2f}mW.")
        return power
    
    def get_measured_power_avg(self, avg:int=1) -> float:
        """
        - Get one power measurement form the power meter 
        with amount of `average_count` individual measurements.
        The final result is the average of all of theindividual 
        measurements.

        - Each measurement is approximately `3 * average_count`ms.

        Returns
        --------
        power : `float`
            The average of all of theindividual measurements.
        """
        cnt = 0
        power = 0
        while cnt<avg:
            cnt+=1
            power += float(self._com.query("MEAS:POW?"))
        power = power/avg
        self.logger.info(f"Avg Power measured: {power*1000:.2f}mW.")
        return power
        
    #un tested
    def get_power_measuring_range(self) -> int:
        """
        - ???

        Returns
        --------
        range : `int`
            ???
        """
        power_range = float(self._com.query("SENS:POW:RANG:UPP?")) # CHECK RANGE
        self.logger.info(f"Power measuring range: {power_range*1000:.1f}mW.")
        return power_range

    #un tested
    def set_power_range(self, range:float) -> None:
        """
        - ???

        Parameters
        --------
        range : `float`
            ???
        """
        self._com.write("SENS:POW:RANG:UPP {}".format(range))
        self.logger.info(f"Set Power_measuring_range to {range}mW.")
        pass

    def get_auto_range_status(self) -> bool:
        """
        - Get the status of auto-ranging feature of the power meter.

        Returns
        --------
        auto-range : `bool`
            The status of auto-ranging feature of the power meter.
        """
        resp = self._com.query("SENS:POW:RANG:AUTO?")
        auto_range = bool(int(resp))
        self.logger.info(f"Current Auto_range status: {repr(auto_range)}.")
        return auto_range
    
    def set_auto_range(self, auto:bool = True) -> None:
        """
        - Set the status of auto-ranging feature of the power meter.

        Parameters
        --------
        auto : `bool`
            The requested status of auto-ranging feature of the power meter.
        """
        self.logger.info( f"Set Auto_range to: {repr(auto)}")
        if auto:
            self._com.write("SENS:POW:RANG:AUTO ON") # turn on auto range
        else:
            self._com.write("SENS:POW:RANG:AUTO OFF") # turn off auto range
    
    def get_measured_frequency(self) -> float:
        """
        - Get the measured frequency from the power meter.

        Returns
        --------
        freq : `float`
            Measured frequency `Hz` from the power meter.
        """
        frequency = float(self._com.query("MEAS:FREQ?"))
        self.logger.info(f"Measured frequency: {frequency:.1f}Hz.")
        return frequency

    def get_zero_magnitude(self) -> float:
        """
        - Get the zero_calibration magnitude (`Watts`) from the power meter.

        Returns
        --------
        zero_mag : `float`
            Current zero_calibration magnitude in `Watts`.
        """
        resp = self._com.query("SENS:CORR:COLL:ZERO:MAGN?")
        zero_magnitude = float(resp)
        self.logger.info(f"Current Zero_magnitude: {zero_magnitude*1000:.2f}mW.")
        return zero_magnitude
        
    def get_zero_state(self) -> bool: 
        """
        - Get the zero_calibration state from the power meter.

        Returns
        --------
        zero_state : `bool`
            Current zero_calibration state.
        """
        resp = self._com.query("SENS:CORR:COLL:ZERO:STAT?")
        zero_state = bool(int(resp))
        self.logger.info(f"Zero_state: {repr(zero_state)}.")
        return zero_state

    def get_photodiode_response(self) -> float:
        """
        - Get the photodiode_response magnitude (`A/W`) from the power meter.

        Returns
        --------
        photo_resp : `float`
            Current photodiode_response magnitude in `A/W`.
        """
        resp = self._com.query("SENS:CORR:POW:PDIOde:RESP?")
        #resp = self.ask("SENS:CORR:VOLT:RANG?")
        #resp = self.ask("SENS:CURR:RANG?")
        photodiode_response = float(resp) # A/W
        self.logger.info(f"Current Photodiode_response: {photodiode_response*1000:.1f}mA/W.")
        return photodiode_response 
    
    def get_measured_current(self) -> float:
        """
        - Get the measured_current magnitude (`A`) from the power meter.

        Returns
        --------
        current : `float`
            Current measured_current magnitude in `Amps`.
        """
        resp = self._com.query("MEAS:CURR?")
        current = float(resp)
        self.logger.info(f"Measured current: {current*1000:.1f}mA.")
        return current
    
    def get_current_range(self) -> float:
        """
        - Get the current_range upper bound (`A`) from the power meter.

        Returns
        --------
        max_current : `float`
            Current max current_range magnitude in `Amps`.
        """
        resp = self._com.query("SENS:CURR:RANG:UPP?")
        current_range = float(resp)
        self.logger.info(f"Preset current_range: {current_range*1000:.1f}mA.")
        return current_range

    def get_sensor_id(self) -> str:
        """
        - Get the sensor_id from the power meter.

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
        self.logger.info(f"CLOSED - Thorlab PM100D Power Meter \"{self.device_id}\"\n\n\n")
        pass
