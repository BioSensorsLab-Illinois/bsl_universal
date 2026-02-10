from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

import re, time

class SP_2150:  
    CONNECT_RETRY_COUNT = 3
    CONNECT_RETRY_DELAY_SEC = 2

    def __init__(self, device_sn="") -> None:
        """
        Initialize and connect an SP-2150 monochromator.

        Parameters
        ----------
        device_sn : str, optional
            Optional serial selector, by default ``""``.
        """
        self._target_device_sn = device_sn
        self.inst = inst.SP_2150
        self.device_id = ""
        self.logger = bsl_logger(self.inst)
        
        self.logger.info(f'Initiating bsl_instrument with target S/N="{device_sn}"...')
        n_try = 0
        while (n_try < self.CONNECT_RETRY_COUNT):
            self._com = self._serial_connect()
            if self._com is not None:
                if self._com.serial_port is not None:
                    break
            self.logger.warning(f"{n_try} - Failed to connect, re-trying.....")
            n_try+=1
            time.sleep(self.CONNECT_RETRY_DELAY_SEC)
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
        try:
            self.close()
        except Exception:
            pass
        return None

    def __init_reset(self) -> None:
        self.logger.info(f"Reseting Monochromator.....")
        self._com_cmd("MONO-RESET")
        self.logger.success(f"Monochronmator Power-On Reset Performed.")
        time.sleep(5)

    def _serial_connect(self) -> bsl_serial:
        """
        Connect to SP-2150 serial interface.

        Returns
        -------
        bsl_serial | None
            Serial interface instance when successful.
        """
        com_port = None
        try:
            com_port = bsl_serial(inst.SP_2150, self._target_device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
        return com_port

    def reconnect(self, device_sn: str = "", reset_controller: bool = True) -> bool:
        """
        Reconnect to SP-2150 controller.

        Parameters
        ----------
        device_sn : str, optional
            Optional serial selector override, by default ``""``.
        reset_controller : bool, optional
            Run `MONO-RESET` after reconnect, by default True.

        Returns
        -------
        bool
            True when reconnection succeeds.
        """
        if device_sn:
            self._target_device_sn = device_sn
        self.close()
        n_try = 0
        while n_try < self.CONNECT_RETRY_COUNT:
            self._com = self._serial_connect()
            if self._com is not None and getattr(self._com, "serial_port", None) is not None:
                self.device_id = getattr(self._com, "device_id", "")
                self.logger.device_id = self.device_id
                if reset_controller:
                    self.__init_reset()
                return True
            n_try += 1
            time.sleep(self.CONNECT_RETRY_DELAY_SEC)
        return False

    def reset_controller(self) -> bool:
        """
        Perform SP-2150 controller reset sequence.

        Returns
        -------
        bool
            True when reset succeeds.
        """
        try:
            self.__init_reset()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to reset SP_2150: {type(exc)}")
            return False

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
        wavelength = float(re.findall(r"\d+\.\d+", self._com_query("?NM"))[0])
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
        grating = int(re.findall(r"\d", self._com_query("?GRATING"))[0])
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
        """
        Close SP-2150 communication resources safely.
        """
        com_obj = getattr(self, "_com", None)
        if com_obj is not None:
            try:
                com_obj.close()
            except Exception:
                pass
            self._com = None
        self.logger.success(f"CLOSED - Monochromator.\n\n\n")
        pass
