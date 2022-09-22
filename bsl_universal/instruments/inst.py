from ._inst_lib.instruments import _HR4000CG, _M69920, _PM100D, _RS_7_1, _SP_2150, _mantisCam
from loguru import logger as __logger
import sys as __sys

__is_logger_ready = False

def init_logger(LOG_LEVEL:str="DEBUG"):
    global __is_logger_ready
    __format_str = "<cyan>{time:MM-DD at HH:mm:ss}</cyan> | <level>{level:7}</level> | {file:15}:{line:4} | <level>{message}</level>"
    __logger.remove()
    __logger.add(__sys.stdout, colorize=True, format=__format_str, level=LOG_LEVEL, diagnose=False)
    __logger.success(f"Logger initlized with LOG_LEVEL = \"{LOG_LEVEL}\".")
    __is_logger_ready = True
    return None

def PM100D(device_sn:str="") -> _PM100D.PM100D:
    if not __is_logger_ready:
        init_logger()
    return _PM100D.PM100D(device_sn)

def M69920(device_sn:str="") -> _M69920.M69920:
    if not __is_logger_ready:
        init_logger()
    return _M69920.M69920(device_sn)

def HR4000CG(device_sn:str="") -> _HR4000CG.HR4000CG:
    if not __is_logger_ready:
        init_logger()
    return _HR4000CG.HR4000CG(device_sn)

def RS_7_1(device_sn:str="", power_on_test:bool=True) -> _RS_7_1.RS_7_1:
    if not __is_logger_ready:
        init_logger()
    return _RS_7_1.RS_7_1(device_sn, power_on_test)

def SP_2150(device_sn:str="") -> _SP_2150.SP_2150:
    if not __is_logger_ready:
        init_logger()
    return _SP_2150.SP_2150(device_sn)

def mantisCam(device_sn:str="", is_GSENSE:bool = False) -> _mantisCam.MantisCamCtrl:
    if not __is_logger_ready:
        init_logger()
    return _mantisCam.MantisCamCtrl(device_sn, log_level=GLOBAL_LOG_LEVEL, is_GSENSE = is_GSENSE)