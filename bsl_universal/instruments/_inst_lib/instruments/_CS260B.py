from ..interfaces._bsl_visa import _bsl_visa as bsl_visa
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, sys

class CS260B:   
    def __init__(self, device_sn:str="") -> None:
        self.inst = inst.CS260B
        self.device_id="" 
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - CS260B-Q-MC-D({device_sn})...")
        if self.__visa_connect(device_sn) == 0:
            self.logger.device_id = self.device_id
            self.__equipmnet_init()
            self.logger.success(f"READY - Newport CS260B Monochromator.\n\n\n")
        else:
            self.logger.error(f"FAILED to connect to Newport CS260B Monochromator ({device_sn})!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    
    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None


    def __visa_connect(self, device_sn:str="") -> int:
        try:
            self._com = bsl_visa(inst.CS260B, device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
            sys.exit(-1)
        if self._com is None:
            if self._com.com_port is None:
                return -1
        self.device_id = self._com.device_id
        return 0


    def __equipmnet_init(self):
        self.get_idle(blocking=True)
        self.__set_gethome()
        self.get_errors()
        self.set_wavelength(450.0)
        self.get_idle(blocking=True)
        return 0    
    

    def __set_gethome(self) -> int:
        """
        Cause the grating rotation stage to rotate to its mechanical “home” position. 
        This position does not correspond to any wavelength.
        """
        self._com.write("FINDHOME")
        self.get_idle(blocking=True)
        self.logger.info("Device grating is homed.")
        return 0


    def __auto_grating(self, wavelength:float) -> int:
        """        
        - This monochromator has four default gratings all with the same Groove Density at 600 lines/mm
          Below are the four gratings' blaze wavelength w/ corresponding intersection wavelength:
            Grating 1: 400nm;   xG3:540nm  @65%;   xG2:660nm @48%;   xG4:1000nm @20%
            Grating 2: 600nm;   xG3:760nm  @66%
            Grating 3: 1000nm;  xG4:1295nm @59%
            Grating 4: 1850nm;
        
        - Sequential operation order of the gratings is #1 -> #3 -> #2 -> #4
        """
        # set grating based on wavelength and grating efficiency curves:
        if wavelength < 540:
            self.set_grating(1)
        elif wavelength < 760:
            self.set_grating(3)
        elif wavelength < 1295:
            self.set_grating(2)
        elif wavelength < 2501:
            self.set_grating(4)
        return 0
    

    def __auto_filter(self, wavelength:float) -> int:
        """
        - set filter wheel from position #1 to #6

        - This filterwheel has six installed filters all with following wavelength:
            Filter 1: 335nm Long-pass       Worst-case non-normal incidence cutoff: 315nm
            Filter 2: 590nm Long-pass       Worst-case non-normal incidence cutoff: 570nm
            Filter 3: 1000nm Long-pass      Worst-case non-normal incidence cutoff: 980nm
            Filter 4: 1500nm Long-pass      Worst-case non-normal incidence cutoff: unknown
            Filter 5: No filter; the light is not filtered
            Filter 6: No filter; the light is not filtered
        """
        # set grating based on wavelength and filter transmission curves:
        if wavelength < 315:
            self.set_filter(1)
        elif wavelength < 570:
            self.set_filter(2)
        elif wavelength < 980:
            self.set_filter(3)
        elif wavelength < 1480:
            self.set_filter(4)
        elif wavelength < 2501:
            self.set_filter(5)
        return 0
    

    def open_shutter(self) -> int:
        """
        Open the input shutter of the monochromator.
        """
        self._com.write("SHUTTER 1")
        self.logger.debug(f"Setting shutter to OPEN")
        self.get_idle(blocking=True)
        cur_shutter = self.get_shutter_status()

        if cur_shutter != 1:
            self.logger.error(f"Failed to open the input shutter!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Device input shutter is OPENED.")
        return 0
    

    def close_shutter(self) -> bool:
        """
        Close the input shutter of the monochromator.
        """
        self._com.write("SHUTTER 0")
        self.logger.debug(f"Setting shutter to CLOSE")
        self.get_idle(blocking=True)

        cur_shutter = self.get_shutter_status()
        if cur_shutter != 0:
            self.logger.error(f"Failed to open the input shutter!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Device input shutter is CLOSED.")
        return 0


    def set_wavelength(self, wavelength:float=0.0, auto_grating:bool = True, auto_filter:bool = False) -> float:
        """
        - set output wavelength of the monochromator in nm.

        - This monochromator has recommended operation range from 250nm to 2500nm.
          When set to 0.0nm, broadspectra will be outputted.

        Parameters
        ----------
        wavelength : `float` (Default: 0.0)
            Desired wavelength in nm, default to broad-spectrum.
        
        auto_grating : `bool` (Default: True)
            Auto adjust grating setting based on requested wavelength.
        
        auto_filter : `bool` (Default: False)
            Auto adjust filter setting based on requested wavelength.

        Returns
        -------
        result : `int`
            0 if success, -1 if fail
        """
        if wavelength < 0 or wavelength > 2500:
            bsl_logger.error("wavelength out of range!")
            return -1

        if auto_grating:
            self.__auto_grating(wavelength)

        if auto_filter:
            self.__auto_filter(wavelength)

        self._com.write(f"GOWAVE {wavelength:.3f}")
        self.logger.debug(f"Setting wavelength to {wavelength:.3f}")
        self.get_idle(blocking=True)
        cur_wavelength = self.get_wavelength()

        if round(cur_wavelength) != round(wavelength):
            self.logger.error(f"Failed to set output wavelength to {wavelength:.3f}! Readback wavelength @ {cur_wavelength:.3f}!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info(f"Device output wavelength set to {cur_wavelength}.")
        return 0    


    def set_grating(self, grating:int) -> int:
        """
        - set grating from grating #1 to #4, should be accessed automatically via 'set_wavelength()'
          function, do not mannully set grating unless you know what you are doing!

        - Sequential operation order of the gratings is #1 -> #3 -> #2 -> #4

        - This monochromator has four default gratings all with the same Groove Density at 600 lines/mm
          Below are the four gratings' blaze wavelength w/ corresponding intersection wavelength:
            Grating 1: 400nm;   xG3:540nm  @65%;   xG2:660nm @48%;   xG4:1000nm @20%
            Grating 2: 600nm;   xG3:760nm  @66%
            Grating 3: 1000nm;  xG4:1295nm @59%
            Grating 4: 1850nm;

        Parameters
        ----------
        grating : `int`
            Desired grating number from 1 to 4.

        Returns
        -------
        result : `int`
            0 if success, -1 if fail
        """
        if grating < 1 or grating > 4:
            bsl_logger.error("grating out of range!")
            return -1

        #Check current grating setting before setting new grating:
        if self.get_grating() == grating:
            return 0
        self.logger.debug(f"Setting grating position to {grating}.")
        self._com.write(f"GRATing {grating}")
        self.get_idle(blocking=True)        
        cur_grating = self.get_grating()
        if cur_grating != grating:
            self.logger.error(f"Failed to set grating pos. to {grating}, current grating pos, at {cur_grating}!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info(f"Grating position set to {grating}.")
        return 0
    

    def set_filter(self, filter:int=5) -> int:
        """
        - set filter wheel from position #1 to #6

        - This filterwheel has six installed filters all with following wavelength:
            Filter 1: 335nm Long-pass       Worst-case non-normal incidence cutoff: 315nm
            Filter 2: 590nm Long-pass       Worst-case non-normal incidence cutoff: 570nm
            Filter 3: 1000nm Long-pass      Worst-case non-normal incidence cutoff: 980nm
            Filter 4: 1500nm Long-pass      Worst-case non-normal incidence cutoff: unknown
            Filter 5: No filter; the light is not filtered
            Filter 6: No filter; the light is not filtered

        Parameters
        ----------
        filter : `int`
            Desired grating number from 1 to 6.

        Returns
        -------
        result : `int`
            0 if success, -1 if fail
        """
        if filter < 1 or filter > 6:
            bsl_logger.error("filter out of range!")
            return -1
        
        if self.get_filter() == filter:
            return 0
        
        self.logger.debug(f"Setting filter position to {filter}")
        self._com.write(f"FILTER {filter}")
        self.get_idle(blocking=True)        
        cur_filter = self.get_filter()
        if cur_filter != filter:
            self.logger.error(f"Failed to set filter pos. to {filter}, current filter pos, at {cur_filter}!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info(f"Filter position to {filter}")
        return 0
    

    def set_output_axial(self) -> int:
        """
        Select the output port through which light will exit the CS260B to the Axial port.

        Warning: Only ONE output port can be selected at a time. If light was outputted through
        the Lateral port, it will be switched to the Axial port.

        ISSUE: Datasheet inconsistency - Lateral on datasheet with parameter 'L' or '2' is actually
        Axial, and vice versa!
        
        Returns
        -------
        result : `int`
            0 if success.
        """
        self._com.write("OUTPORT L")
        self.logger.debug(f"Setting output port to Axial.")
        self.get_idle(blocking=True)
        cur_outport = self.get_output_port()

        if cur_outport != 2:
            self.logger.error(f"Failed to set output port to Axial!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Device output port is set to Axial.")
        return 0
    

    def set_output_lateral(self) -> int:
        """
        Select the output port through which light will exit the CS260B to the Lateral port.

        Warning: Only ONE output port can be selected at a time. If light was outputted through
        the Axial port, it will be switched to the lateral port.

        ISSUE: Datasheet inconsistency - Lateral on datasheet with parameter 'L' or '2' is actually
        Axial, and vice versa!
        
        Returns
        -------
        result : `int`
            0 if success.
        """
        self._com.write("OUTPORT A")
        self.logger.debug(f"Setting output port to Lateral.")
        self.get_idle(blocking=True)
        cur_outport = self.get_output_port()

        if cur_outport != 1:
            self.logger.error(f"Failed to set output port to Lateral!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Device output port is set to Lateral.")
        return 0
    

    # This should be the safe access for current setting
    # the instrument's actual readout
    def get_wavelength(self) -> float:
        """
        - Get current wavelength setting from the monochromator.

        Returns
        --------
        wavelength : `float`
            Current wavelength setting from the monochromator.
        """
        wavelength = float(self._com.query("WAVE?"))
        self.logger.info(f"Readback wavelength: {wavelength:.3f}")
        return wavelength   
    
    
    def get_grating(self) -> int:
        """
        - Get current grating# setting from the monochromator.

        Returns
        --------
        grating : `int`
            Current grating# setting from the monochromator.
        """
        grating = int(self._com.query("GRATing?").split(',')[0])
        self.logger.info(f"Readback #grating: {grating}")
        return grating   
    

    def get_filter(self) -> int:
        """
        - Get current Filter posiotion setting from the monochromator.

        Returns
        --------
        filter : `int`
            Current ilter posiotion setting from the monochromator.
        """
        filter = int(self._com.query("FILTER?"))
        self.logger.info(f"Readback filter: {filter}")
        return filter   
    

    def get_shutter_status(self) -> int:
        """
        - Get current input shutter status.

        Returns
        --------
        shutter : `int`
            0 -> shutter is CLOSED.
            1 -> shutter is OPENED.
        """
        resp = self._com.query("SHUTTER?")
        if resp == 'O':
            return 1
        elif resp == 'C':
            return 0
        self.logger.info(f"Device shutter status: {resp}")
        return -1


    def get_idle(self, blocking:bool=False, timeout_sec:int=15) -> int:
        """
        - Get current operation status of the monochromator.

        Parameters
        ----------
        blocking : `bool` (Default: FALSE)
            Set blocking to TRUE if blocking/waiting until device is READY is required.
            
        timeout_sec : `int` (Default: 15s)
            Set timeout threshold for IDLE waiting period, error is thrown if reached. 

        Returns
        --------
        IDLE : `int`
            0 -> Monochromator is BUSY.
            1 -> Monochromator is READY for next operation.
        """
        start = time.time()
        idle = int(self._com.query("IDLE?"))
        idle_msg = "BUSY" if (idle == 0) else "READY"
        self.logger.debug(f"Device IDLE readback is {idle_msg}.")

        while (blocking and not idle):
            self.logger.debug(f"Device is BUSY, retrying...")
            time.sleep(0.5)
            idle = int(self._com.query("IDLE?"))
            idle_msg = "BUSY" if (idle == 0) else "READY"
            self.logger.debug(f"Device IDLE readback is {idle_msg}.")
            if (time.time()-start > timeout_sec):
                self.logger.error(f"Device operation TIMEOUT!")
                raise bsl_type.DeviceTimeOutError
        return idle
    

    def get_output_port(self) -> int:
        """
        - Query the output port setting.

        ISSUE: Datasheet inconsistency - Lateral on datasheet with parameter 'L' or '2' is actually
        Axial, and vice versa!

        Returns
        --------
        outport : `int`
            1 -> Light is outputted through the LATERAL port.
            2 -> Light is outputted through the AXIAL port.
        """
        resp = self._com.query("OUTPORT?")
        if resp == '1':
            self.logger.info(f"Device output port is LATERAL.")
        elif resp == '2':
            self.logger.info(f"Device output port is AXIAL.")
        else:
            self.logger.info(f"Device output port status: {resp}")
        return int(resp)
    

    def get_error_legacy(self) -> int:
        """
        - Query the error byte. Legacy mode for quick verification.

        Returns
        --------
        error : `int`
            See logger information for error descriptions.
        """
        err = int(self._com.query("ERROR?"))
        if err == 0:
            self.logger.debug(f"No Error logged, device is operation normal.")
        elif err == 1:
            self.logger.error(f"Error 1: Invalid command previouslly detected.")
        elif err == 2:
            self.logger.error(f"Error 2: Invalid parameter previouslly detected.")
        elif err == 3:
            self.logger.error("Error 2: Destination position for wavelength motion not allowed.")
        elif err == 6:
            self.logger.error("Error 6: Accessory not present (usually filter wheel).")
        elif err == 8:
            self.logger.error("Error 8: Could not home wavelength drive.")
        elif err == 9:
            self.logger.error("Error 9: Label too long (e.g. “filter1label chartreuse”).")
        elif err == 10:
            self.logger.error("Error 10: System error.")
        if err != 0:
            raise bsl_type.DeviceOperationError
        return err
    

    def get_errors(self) -> int:
        """
        - Query the system error information.

        Returns
        --------
        error : `int`
            See logger information for error descriptions.
        """
        count = 1
        (err_code, err_msg) = self._com.query("SYSTEM:ERROR?").split(',')

        if err_code == '0' or err_code == "501":
            return 0

        while (err_code != 0 and count < 11):
            count += 1
            self.logger.error(f"Device Error with error code:{err_code}; error msg: {err_msg}.")
            (err_code, err_msg) = self._com.query("SYSTEM:ERROR?").split(',')
        raise bsl_type.DeviceOperationError
    

    def close(self) -> None:
        if self._com is not None:
            self.close_shutter()
            self._com.close()
            del self._com
        self.logger.info(f"CLOSED - \"{self.device_id}\"\n\n\n")
        pass
    