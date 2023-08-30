from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import enum, time

# The Arc Lamp used in the housing with model number "6296" (1000W Xe UV Enhanced)
# The Arc Lamp's nominal opreating parameters are:
#   Power Range: 800 - 1100W
#   Current (Typical): 43.5A (DC)
#   Voltage (Typical): 23V (DC)
#   Lamp Life: 1000 Hours

class M69920:
    class SUPPLY_MODE(enum.Enum):
        CURRENT_MODE = 1
        POWER_MODE = 0

    def __init__(self, device_sn="", *, mode=SUPPLY_MODE.POWER_MODE, lim_current:int=50, lim_power:int=1200, default_power:int=1000) -> None:
        self.target_device_sn = device_sn
        self.inst = inst.M69920
        self.device_id = ""
        self.logger = bsl_logger(self.inst)
        self.logger.info(f"Initiating bsl_instrument - M69920({device_sn})...")
        if self._serial_connect():
            self.logger.success(f"Connected - Newport M69920 Lamp Power Supply.\n\n\n")
            self.__init_lamp(mode, lim_current, lim_power, default_power)
            self.logger.warning(f"This Arc Lamp Power Supply has been configured to work with the UV-Enhanced Xeon Arc Lamp.")
            self.logger.warning(f"All the operation parameter has been preset for this specific Arc Lamp.")
            self.logger.warning(f"You should ONLY use readonly features/functions and Lamp ON/OFF functions for the operation!")
            self.logger.warning(f"All other operation are reserved for internal useages and experimental project!")
            self.logger.success(f"READY - Newport M69920 Lamp Power Supply.\n\n\n")
        else:
            self.logger.error(f"FAILED to connect to M69920 Arc lamp's power supply! ({device_sn})!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None

    def _serial_connect(self) -> bool:
        try:
            self.serial = bsl_serial(inst.M69920, self.target_device_sn)
        except Exception as e:
            self.logger.error(f"{type(e)}")
            
        if self.serial.serial_port is None:
            return False
        return self.serial.serial_port.is_open


    def serial_command(self, msg) -> int:
        time.sleep(0.05)
        self.serial.flush_read_buffer()
        self.serial.writeline(msg)
        time.sleep(0.05)
        resp = self.serial.read_all()
        return resp
    

    def serial_query(self, msg) -> float:
        time.sleep(0.05)
        self.serial.flush_read_buffer()
        self.serial.writeline(msg)
        time.sleep(0.05)
        resp = self.serial.read_all()
        return float(resp.decode('utf-8'))

    
    def __init_lamp(self, mode=SUPPLY_MODE.POWER_MODE, lim_current:int=50, lim_power:int=1200, default_power:int=1000) -> int:
        self.serial_command("RST")
        time.sleep(5)
        self.lamp_OFF()
        self.__set_lamp_mode(mode)
        self.set_lamp_current_limit(lim_current)
        self.set_lamp_power_limit(lim_power)
        self.set_lamp_power(default_power)
        self.logger.success(f"Arc Lamp power supply RESETTED!")
        return 0


    def __STB_query(self, retry:int=3) -> int:
        count = 1
        resp=""
        while ("STB" not in str(resp)) and (count <= retry):
            resp = self.serial_command("STB?").decode('utf-8')
            count += 1

        # Parse the status bit from incomming msg
        h_status = int(resp[3:5],16)
        # Check bit-7 for lamp status
        if (h_status &0b1000_0000) != 0:
            self.__is_lamp_ON = True
        else:
            self.__is_lamp_ON = False
        # Check bit-5 for power_supply limit mode
        if (h_status &0b0010_0000) != 0:
            self.__mode = self.SUPPLY_MODE.POWER_MODE
        else:
            self.__mode = self.SUPPLY_MODE.CURRENT_MODE
        # Check bit-3 for errors
        if (h_status &0b0000_1000) != 0:
            self.logger.warning("Arc Lamp Supply ERROR detected! Possible ignition failiure.")
            self.__error_checking()
        # Check bit-2 for front panel lock status
        if (h_status &0b0000_0100) != 0:
            self.__frontpanel_lock = True
        else:
            self.__frontpanel_lock = False
            # self.logger.warning("Arc Lamp Power Supply front panel is not locked, take caution!")
        # Check bit-1 for power_supply limit status
        if (h_status &0b0000_0010) != 0:
            self.logger.error("Arc Lamp Power Supply LIMIT REACHED, please adjust output or increase PWR/CUR limits!")
        # Check bit-0 for interlock status
        if (h_status &0b0000_0001) == 0:
            self.logger.error("Arc Lamp Power Supply INTERLOCK ERROR, please confirm interlock status!")
        self.__error_checking()
        return 0
    

    def __error_checking(self, retry:int=3) -> int:
        count = 1
        resp=""
        while ("ESR" not in str(resp)) and (count <= retry):
            resp = self.serial_command("ESR?")
            count += 1

        # Parse the status bit from incomming msg
        err_status = int(resp[3:5],16)

        # Check bit-7 for power ON error
        if (err_status &0b1000_0000) != 0:
            self.logger.error("Arc Lamp Power Supply Power ON ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-6 for User Request Error
        if (err_status &0b0100_0000) != 0:
            self.logger.error("Arc Lamp Power Supply User Request ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-5 for Command Error
        if (err_status &0b0010_0000) != 0:
            self.logger.error("Arc Lamp Power Supply Command ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-4 for Execution Error
        if (err_status &0b0001_0000) != 0:
            self.logger.error("Arc Lamp Power Supply Execution ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-3 for Device Dependant Error
        if (err_status &0b0000_1000) != 0:
            self.logger.error("Arc Lamp Power Supply Device Dependant ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-2 for Query Error
        if (err_status &0b0000_0100) != 0:
            self.logger.error("Arc Lamp Power Supply Query ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-1 for Request Control Error
        if (err_status &0b0000_0010) != 0:
            self.logger.error("Arc Lamp Power Supply Request Control ERROR!")
            raise bsl_type.DeviceOperationError
        return 0


    def lamp_ON(self, retry:int=20) -> int:
        count = 1
        self.logger.debug("Truing ON the Arc Lamp.")
        
        while (not self.is_lamp_ON() and count < retry):
            if count > 1:
                self.logger.warning("Lamp ignition failed! Retrying...")
                self.__init_lamp()
            self.serial_command("START")
            time.sleep(6)
            count+=1
        
        if self.is_lamp_ON():
            self.logger.success("Arc Lamp turned ON.")
        else:
            self.logger.error("Failed to turn ON the Lamp. Timed out!")
            raise bsl_type.DeviceOperationError
        return 0
    
    
    def lamp_OFF(self, timeout_sec:int=45) -> int:
        start = time.time()
        self.logger.debug("Truing OFF the Arc Lamp.")

        while (self.is_lamp_ON() and (time.time()-start)<timeout_sec):
            self.serial_command("STOP")
            time.sleep(5)
        
        if not self.is_lamp_ON():
            self.logger.success("Arc Lamp turned OFF.")
        else:
            self.logger.error("Failed to turn OFF the Lamp. Timed out!")
            raise bsl_type.DeviceOperationError
        return 0

    def is_lamp_ON(self) -> bool:
        self.__STB_query()
        return self.__is_lamp_ON
    
    def is_front_panel_locked(self) -> bool:
        self.__STB_query()
        return self.__frontpanel_lock
    
    def get_lamp_mode(self) -> int:
        """
        - Get Arc Lamp operation mode.

        Returns
        -------
        mode : `int`
            0 -> Power Mode
            1 -> Current Mode
        """
        self.__STB_query()
        self.logger.debug(f"Arc Lamp mode readback as:{self.__mode}")
        return self.__mode


# This is made to be a privare function since it's not recommended to change the power supply mode for this lamp.
    def __set_lamp_mode(self, mode:SUPPLY_MODE) -> int:
        self.logger.debug(f"Setting Arc Lamp to {mode} mode.")

        if self.is_lamp_ON():
            self.logger.warning("Lamp need to be turned OFF before changing PWR mode!")
            self.lamp_OFF()
            
        if mode == self.SUPPLY_MODE.CURRENT_MODE:
            # Set MODE=1 for current mode operation
            self.serial_command("MODE=1")
        else:
            # Set MODE=0 for power mode operation
            self.serial_command("MODE=0")
        
        if self.get_lamp_mode() != mode:
            self.logger.error(f"FAILED to change Operation mode!")
            raise bsl_type.DeviceInconsistentError
        
        self.logger.info(f"Arc Lamp Set to {mode} mode.")
        return 0

    def lock_front_panel(self) -> int:
        # Set COMM=1 to lock front panel access
        self.logger.debug(f"Locking Arc Lamp frontpanel.")
        self.serial_command('COMM=1')
        
        if self.is_front_panel_locked() != True:
            self.logger.error(f"FAILED to lock front panel!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Arc Lamp frontpanel locked.")
        return 0

    def unlock_front_panel(self) -> int:
        # Set COMM=0 to unlock front panel access
        self.logger.debug(f"Releasing Arc Lamp frontpanel.")
        self.serial_command('COMM=0')
        
        if self.is_front_panel_locked() == True:
            self.logger.error(f"FAILED to unlock front panel!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info("Arc Lamp frontpanel unlocked.")
        return 0

# For this Xe UV Enhanced lamp, the current setting of 43.5 is required for operation.
    def set_lamp_current(self, current:float = 43.5) -> int:
        self.logger.debug(f"Setting Arc Lamp current to {current:.1f}A.")
        # Check if current power supply mode is current mode
        if self.get_lamp_mode() != self.SUPPLY_MODE.CURRENT_MODE:
            self.logger.error(f"FAILED to set lamp current, power supply is in POWER_MODE!")
            raise bsl_type.DeviceInconsistentError
        # Check if the desired current is smaller than current limits
        if current >= self.current_limit:
            self.logger.error(f"FAILED to set lamp current to {current:.1f} since current limit is set to {self.current_limit:.1f}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'A-PRESET={current:.1f}'
        self.serial_command(msg)

        if self.get_current_limit() != current:
            self.logger.error(f"FAILED to set lamp current to {current:.1f} with read back current {self.preset_current:.1f}!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info(f"Lamp current set to {self.preset_current:.1f}A")    
        pass
    
    def set_lamp_power(self, power:int) -> int:
        self.logger.debug(f"Setting Arc Lamp power to {power:04d}W.")
        # Check if current power supply mode is current mode
        if self.get_lamp_mode() != self.SUPPLY_MODE.POWER_MODE:
            self.logger.error(f"FAILED to set lamp power, power supply is in CURRENT_MODE!")
            raise bsl_type.DeviceInconsistentError
        # Check if the desired current is smaller than current limits
        if power >= self.get_power_limit():
            self.logger.error(f"FAILED to set lamp power to {power:04d} since current limit is set to {int(self.get_power_limit()):04d}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'P-PRESET={power:04d}'
        self.serial_command(msg)

        if self.get_preset_power() != power:
            self.logger.error(f"    FAILED to set lamp power to {power:04d} with read back power {int(self.get_preset_power()):04d}!")
        self.logger.info(f"Lamp power set to {int(self.get_preset_power()):04d}W")       
        return 0
    

    def set_lamp_current_limit(self, lim_I=50) -> int:
        self.logger.debug(f"Setting Arc Lamp current limit to {lim_I:.1f}A.")
        # Check if the desired current is smaller than current limits
        if lim_I <= self.get_preset_current():
            self.logger.error(f"FAILED to set lamp current_limit to {lim_I:.1f} since current limit is smaller than preset_current {self.preset_current:.1f}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'A-LIM={lim_I:.1f}'
        self.serial_command(msg)

        if self.get_current_limit() != lim_I:
            self.logger.error(f"FAILED to set lamp current_limit to {lim_I:.1f} with read back current {self.get_current_limit():.1f}!")
            raise bsl_type.DeviceInconsistentError
        self.logger.info(f"Lamp current_limit set to {self.get_current_limit():.1f}A")       
        return 0


    def set_lamp_power_limit(self, lim_P=1200) -> int:
        self.logger.debug(f"Setting Arc Lamp power limit to {int(lim_P):4d}W.")
        # Check if the desired current is smaller than current limits
        if lim_P <= self.get_preset_power():
            self.logger.error(f"FAILED to set lamp power_limit to {lim_P:04d} since it's smaller than preset power {int(self.get_preset_power()):04d}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'P-LIM={lim_P:04d}'
        self.serial_command(msg)
  
        if self.get_power_limit() != lim_P:
            self.logger.error(f"FAILED to set lamp power_limit to {lim_P:04d} with read back power {int(self.get_power_limit()):04d}!")
        self.logger.info(f"Lamp power_limit set to {int(self.get_power_limit()):4d}W")       
        return 0



    def get_current_current(self) -> float:
        # Request current reading from the power supply.
        resp = self.serial_query('AMPS?')
        return resp

    def get_current_voltage(self) -> float:
        # Request current reading from the power supply.
        resp = self.serial_query('VOLTS?')
        return resp

    def get_current_power(self) -> int:
        # Request current reading from the power supply.
        resp = self.serial_query('WATTS?')
        return resp

    def get_lamp_hours(self) -> int:
        # Request current reading from the power supply.
        resp = self.serial_query('LAMP HRS?')
        return resp
    
    def get_preset_current(self) -> float:
        # Request current reading from the power supply.
        resp = self.serial_query('A-PRESET?')
        return resp

    def get_preset_power(self) -> int:
        # Request current reading from the power supply.
        resp = self.serial_query('P-PRESET?')
        return resp

    def get_current_limit(self) -> float:
        # Request current reading from the power supply.
        resp = self.serial_query('A-LIM?')
        return resp

    def get_power_limit(self) -> int:
        # Request current reading from the power supply.
        resp = self.serial_query('P-LIM?')
        return resp
    
    def _get_lamp_id(self):
        pass
    
    def lamp_shut_down(self) -> int:
        self.lamp_OFF()
        self.unlock_front_panel()
        return 0

    def close(self) -> None:
        if self.serial is not None:
            self.lamp_shut_down()
            self.serial.close()
            del self.serial
        self.logger.info(f"CLOSED - Arc lamp's power supply.\n\n\n")
        pass