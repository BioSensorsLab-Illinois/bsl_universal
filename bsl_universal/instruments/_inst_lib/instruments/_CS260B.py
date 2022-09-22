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

    def goto(self):
        return 0    

    def open_shutter(self):
        return 0

    def close_shutter(self):
        return 0
    
    def select_grating(self, grating):
        return 0
    
    def select_filter(self, filter):
        return 0

    def set_slit_width(self, slit_width):
        return 0
    
    def set_ON_auto_bandpass_adjust(self):
        return 0
    
    def set_OFF_auto_bandpass_adjust(self):
        return 0

    def power(self):
        return 0    

    # This should be the safe access for current setting
    # the instrument's actual readout
    def get_current_nm(self):
        return 0    

    def get_status(self):
        return 0    

    def disconnect(self):
        return 0    

