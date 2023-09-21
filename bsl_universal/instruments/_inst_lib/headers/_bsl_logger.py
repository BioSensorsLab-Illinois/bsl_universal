from loguru import logger
from ._bsl_type import _bsl_type as bsl_type
from ._bsl_inst_info import _bsl_inst_info_class as inst

logger_opt = logger.opt(ansi=True)

# @logger.catch(exclude=(bsl_type.DeviceConnectionFailed,bsl_type.DeviceInconsistentError,bsl_type.DeviceOperationError))
class _bsl_logger:
    def __init__(self, cur_inst: inst, device_id: str="N/A") -> None:
        self.__inst = cur_inst
        self.device_id = device_id
        logger.info(f"    {self.__inst.MODEL}  ({self.device_id}) - Logger instance initilized")
        pass

    def __del__(self, *args, **kwargs) -> None:
        self.close()

    def error(self, msg:str="") -> None:
        logger.error(f"ERROR - {self.__inst.MODEL}  ({self.device_id})- {msg}")
        # raise bsl_type.DeviceOperationError

    def warning(self, msg:str="") -> None:
        logger.warning(f"    {self.__inst.MODEL}  ({self.device_id}) - {msg}")

    def info(self, msg:str="") -> None:
        logger.info(f"    {self.__inst.MODEL}  ({self.device_id}) - {msg}")

    def trace(self, msg:str="") -> None:
        logger.trace(f"    {self.__inst.MODEL}  ({self.device_id}) - {msg}")

    def debug(self, msg:str="") -> None:
        logger.debug(f"    {self.__inst.MODEL}  ({self.device_id}) - {msg}")

    def success(self, msg:str="") -> None:
        logger.success(f"    {self.__inst.MODEL}  ({self.device_id}) - {msg}")

    def close(self) -> None:
        logger.info(f"    - Logger instance terminated")