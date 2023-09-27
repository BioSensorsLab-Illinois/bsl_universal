from loguru import logger
from ..headers._bsl_inst_info import _bsl_inst_info_list
from ..headers import _bsl_type
import re
try:
    import pyvisa as pyvisa
except ImportError:
    pass
logger_opt = logger.opt(ansi=True)

# @logger_opt.catch
class _bsl_visa:

    def __init__(self, target_inst:_bsl_inst_info_list, device_sn:str="") -> None:
        #Init logger_opt by inherit from parent process or using a new one if no parent logger_opt
        logger_opt.info("    Initiating bsl_visa_service...")
        self.visa_resource_manager = pyvisa.ResourceManager()

        self.inst = target_inst
        self.target_device_sn = device_sn
        self._connect_visa_device()
        if self.com_port is None:
            logger_opt.error(f"<light-blue><italic>{self.inst.MODEL} ({self.target_device_sn})</italic></light-blue> not found on VISA/SCPI ports.")
        pass

    def __del__(self) -> None:
        self.close()

    def _find_device_vpid(self) -> None:
        resource_list = self.visa_resource_manager.list_resources()
        logger.debug(f"    bsl_VISA - Currently opened devices: {repr(self.visa_resource_manager.list_opened_resources())}")
        for port in resource_list:
            logger_opt.debug(f"    Found bus device <light-blue><italic>{port}</italic></light-blue>")
            if port in str(self.visa_resource_manager.list_opened_resources()):
                logger_opt.warning(f"    BUSY - Device <light-blue><italic>{port}</italic></light-blue> is busy, moving to next available device...")
                continue
            if (self.inst.USB_PID in port) and (self.inst.USB_VID in port):
                logger_opt.debug(f"    {self.inst.MODEL} is found with USB_PID/VID search.")
                temp_com_port = self.visa_resource_manager.open_resource(port)
                re_result = re.search(self.inst.SN_REG, temp_com_port.query(self.inst.QUERY_CMD).strip())
                if re_result is not None:
                    device_id = re_result.group(0)
                else:
                    device_id = "UNABLE_TO_OBTAIN"
                if self.target_device_sn not in device_id:
                    temp_com_port.close()
                    logger_opt.warning(f"    S/N Mismatch - Device <light-blue><italic>{port}</italic></light-blue> with S/N <light-blue><italic>{device_id}</italic></light-blue> found, not <light-blue><italic>{self.target_device_sn}</italic></light-blue> as requested, moving to next available device...")
                    continue
                temp_com_port.close()
                return port
            if ( str(int(self.inst.USB_PID,16)) in port and str(int(self.inst.USB_VID,16)) in port):
                logger_opt.debug(f"    {self.inst.MODEL} is found with USB_PID/VID search.")
                temp_com_port = self.visa_resource_manager.open_resource(port)
                device_id = re.search(self.inst.SN_REG, temp_com_port.query(self.inst.QUERY_CMD).strip()).group(1)
                if self.target_device_sn not in device_id:
                    temp_com_port.close()
                    logger_opt.warning(f"    S/N Mismatch - Device <light-blue><italic>{port}</italic></light-blue> with S/N <light-blue><italic>{device_id}</italic></light-blue> found, not <light-blue><italic>{self.target_device_sn}</italic></light-blue> as requested, moving to next available device...")
                    continue
                temp_com_port.close()
                return port
        return None

    def _connect_visa_device(self) -> None:
        port = self._find_device_vpid()
        self.com_port = None
        if port is not None:
            self.com_port = self.visa_resource_manager.open_resource(port)
        if self.com_port is not None:
            self.device_id = self.query(self.inst.QUERY_CMD).strip()
            if self.inst.QUERY_E_RESP not in self.device_id:
                logger_opt.error(f"    FAILED - Wrong device identifier (E_RESP) is returned!")
                raise _bsl_type.DeviceConnectionFailed
            self.device_id = re.search(self.inst.SN_REG, self.device_id).group(0)
            logger_opt.success(f"    {self.inst.MODEL} with DEVICE_ID: <light-blue><italic>{self.device_id}</italic></light-blue> found and connected!")
        pass

    def query(self, cmd:str):
        logger_opt.trace(f"        {self.inst.MODEL} - com-VISA - Query to {self.inst.MODEL} with {cmd}")
        resp = self.com_port.query(cmd).strip()
        logger_opt.trace(f"        {self.inst.MODEL} - com-VISA - Resp from {self.inst.MODEL} with {repr(resp)}")
        return resp
    
    def write(self, cmd:str) -> None:
        logger_opt.trace(f"        {self.inst.MODEL} - com-VISA - Write to {self.inst.MODEL} with {cmd}")
        self.com_port.write(cmd)
        pass

    def set_timeout_ms(self, timeout:int) -> None:
        self.com_port.timeout = timeout
        pass

    def close(self) -> None:
        if self.com_port is not None:
            self.com_port.close()
        pass


        