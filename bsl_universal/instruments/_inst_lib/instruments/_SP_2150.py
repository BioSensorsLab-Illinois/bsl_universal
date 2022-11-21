from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

import re, time

class SP_2150:  
    def __init__(self, device_sn="") -> None:
        self._target_device_sn = device_sn
        self.inst = inst.SP_2150
        self.device_id = ""
        self.logger = bsl_logger(self.inst)
        
        self.logger.info(f'Initiating bsl_instrument with target S/N="{device_sn}"...')
        n_try = 0
        while (n_try < 3):
            self._com = self._serial_connect()
            if self._com is not None:
                if self._com.serial_port is not None:
                    break
            self.logger.warning(f"{n_try} - Failed to connect, re-trying.....")
            n_try+=1
            time.sleep(2)
        if self._com is not None:
            if self._com.serial_port is not None:
                self.device_id = self._com.device_id
                self.logger.device_id = self._com.device_id
                self.__init_reset()
                self.logger.success(f"READY - Monochromator.\n\n\n")
                return
        self.logger.error(f"FAILED to connect Monochromator!\n\n\n")
        raise bsl_type.DeviceConnectionFailed

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None

    def __init_reset(self) -> None:
        self.logger.info(f"Reseting Monochromator.....")
        self._com_cmd("MONO-RESET")
        self.logger.success(f"Monochronmator Power-On Reset Performed.")
        time.sleep(5)

    def _serial_connect(self) -> bsl_serial:
        try:
            com_port = bsl_serial(inst.SP_2150, self._target_device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
        return com_port

    def set_wavelength(self, wavelength) -> None:
        """
        - Set monochromator to the specified wavelength (in nm).

        Parameters
        -----------
        wavelength : `int`
            Wavelength (in nm) to set the monochromator to.
        """
        self._com_cmd(f"{wavelength} GOTO")
        self.logger.info(f"Output set to {wavelength} nm.")
        return None

    def get_wavelength(self) -> float:
        """
        - Get the current wavelength (in nm) of the monochromator
        with the format 250.0.

        Returns:
        -----------
        wavelength : `float`
            Current wavelength (in nm) of the monochromator.
        """
        wavelength = float(re.findall("\d+\.\d+",self._com_query("?NM"))[0])
        self.logger.info(f"Current operating point is at {wavelength} nm.")
        return wavelength

    def set_grating(self, grating) -> None:
        """
        - Select either the first or second grating. Requires approximately 20 seconds.
        Moves to the same wavelength as the previous grating or 200nm default if wavelength
        is not accessible by the selected grating.

        Parameters
        -----------
        grating : `int`
            Grating (1 or 2). First or second grating.
        """
        if (grating!=1 and grating!=2):
            self.logger.error("Grating must be 1 or 2")
            raise bsl_type.DeviceOperationError
        self._com_cmd(f"{grating} GRATING")
        self.logger.info(f"Grating set to {grating}.")
        return None

    def get_grating(self) -> int:
        """
        - Get the current grating position (1 or 2) of the monochromator.

        Returns:
        -----------
        grating : `int`
            Current grating position (1 or 2) of the monochromoator.
        """
        grating = int(re.findall("\d",self._com_query("?GRATING"))[0])
        self.logger.info(f"Current grating is {grating}.")
        return grating

    def _com_query(self, msg, timeout:float = 0.5) -> str:
        self._com.flush_read_buffer()
        self._com.write(msg+'\r')
        resp = self._com.readline()
        if "SERIAL" in resp:
            self._com.flush_read_buffer()
            self._com.write(msg+'\r')
            resp = self._com.readline()
        if resp in msg:
            resp = self._com.readline()
        return resp

    def _com_cmd(self, msg, timeout:float = 0.5) -> int:
        self._com.flush_read_buffer()
        self._com.write(msg+'\r')
        resp = self._com.readline()
        if "SERIAL" in resp:
            self._com.flush_read_buffer()
            self._com.write(msg+'\r')
            resp = self._com.readline()
        if "ok" not in resp:
            self.logger.error(f"message from device: \"{resp}\"")
            raise bsl_type.DeviceOperationError
        else:
            return 0

    def close(self) -> None:
        if self._com is not None:
            self._com.close()
            del self._com
        self.logger.success(f"CLOSED - Monochromator.\n\n\n")
        del self.logger
        pass

