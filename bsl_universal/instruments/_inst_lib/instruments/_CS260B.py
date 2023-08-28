from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

class CS260B:   

    def __init__(self, COM_id):
        return 0

    def __serial_connect(self):
        return 0    

    def __equipmnet_init(self):
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
            self.set_grating(2)
        elif wavelength < 1295:
            self.set_grating(3)
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


    def set_wavelength(self, wavelength:float=0.0, auto_grating:bool = True, auto_filter:bool = True) -> float:
        """
        - set output wavelength of the monochromator in nm.

        - This monochromator has recommended operation range from 250nm to 2500nm.
          When set to 0.0nm, broadspectra will be outputted.

        Parameters
        ----------
        grating : `int`
            Desired grating number from 1 to 4.

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
        return 0    
    

    def open_shutter(self) -> bool:
        return 0

    def close_shutter(self) -> bool:
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
        if self.get_current_grating() == grating:
            return 0
        return 0
    

    def set_filter(self, filter:int) -> int:
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
        
        if self.get_current_filter() == filter:
            return 0
        
        return 0
    
    
    def set_ON_auto_bandpass_adjust(self):
        return 0
    

    def set_OFF_auto_bandpass_adjust(self):
        return 0


    # This should be the safe access for current setting
    # the instrument's actual readout
    def get_current_nm(self) -> float:
        return 0    
    
    def get_current_grating(self) -> int:
        return 0

    def get_current_filter(self) -> int:
        return 0

    def get_status(self):
        return 0    

    def disconnect(self):
        return 0    

