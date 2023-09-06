from ._inst_lib.instruments import _HR4000CG, _M69920, _PM100D, _RS_7_1, _SP_2150, _mantisCam, _DC2200, _CS260B, _Futek_USB_520
from loguru import logger as __logger
import sys as __sys

__is_logger_ready = False
__GLOBAL_LOG_LEVEL = "DEBUG"

def init_logger(LOG_LEVEL:str="DEBUG"):
    global __is_logger_ready
    global __GLOBAL_LOG_LEVEL
    __GLOBAL_LOG_LEVEL = LOG_LEVEL
    __format_str = "<cyan>{time:MM-DD at HH:mm:ss}</cyan> | <level>{level:7}</level> | {file:15}:{line:4} | <level>{message}</level>"
    __logger.remove()
    __logger.add(__sys.stdout, colorize=True, format=__format_str, level=LOG_LEVEL, diagnose=False)
    __logger.success(f"Logger initlized with LOG_LEVEL = \"{LOG_LEVEL}\".")
    __is_logger_ready = True
    return None

# Instrument Class for Thorlabs PM100D Power Meter
def PM100D(device_sn:str="") -> _PM100D.PM100D:
    if not __is_logger_ready:
        init_logger()
    return _PM100D.PM100D(device_sn)

# Instrument Class for Thorlabs DC2200 DC LED Driver
def DC2200(device_sn:str="") -> _DC2200.DC2200:
    if not __is_logger_ready:
        init_logger()
    return _DC2200.DC2200(device_sn)

# Instrument Class for NewPort Arc Lamp Supply
def M69920(device_sn:str="") -> _M69920.M69920:
    if not __is_logger_ready:
        init_logger()
    return _M69920.M69920(device_sn)

def CS260B(device_sn:str="") -> _CS260B.CS260B:
    if not __is_logger_ready:
        init_logger()
    return _CS260B.CS260B(device_sn)

# Instrument Class for OceanOptics HR4000CG Spectrometer
def HR4000CG(device_sn:str="") -> _HR4000CG.HR4000CG:
    if not __is_logger_ready:
        init_logger()
    return _HR4000CG.HR4000CG(device_sn)

# Instrument Class for Gamma Scientific RS-7-1 MultiSpectral LED Source
def RS_7_1(device_sn:str="", power_on_test:bool=True) -> _RS_7_1.RS_7_1:
    if not __is_logger_ready:
        init_logger()
    return _RS_7_1.RS_7_1(device_sn, power_on_test)

# Instrument Class for Princeton Instruments SP-2150 MonoChromator
def SP_2150(device_sn:str="") -> _SP_2150.SP_2150:
    if not __is_logger_ready:
        init_logger()
    return _SP_2150.SP_2150(device_sn)

# Instrument Class for Futek USB-520 Load Cell USB ADC
def USB_520(device_sn:str="", tear_on_startup:bool = True, reverse_negative:bool = True) -> _Futek_USB_520.USB_520:
    if not __is_logger_ready:
        init_logger()
    return _Futek_USB_520.USB_520(device_sn, tear_on_startup=tear_on_startup, reverse_negative=reverse_negative)

def mantisCam(device_sn:str="", is_GSENSE:bool = False) -> _mantisCam.MantisCamCtrl:
    if not __is_logger_ready:
        init_logger()
    return _mantisCam.MantisCamCtrl(device_sn, log_level=__GLOBAL_LOG_LEVEL, is_GSENSE = is_GSENSE)