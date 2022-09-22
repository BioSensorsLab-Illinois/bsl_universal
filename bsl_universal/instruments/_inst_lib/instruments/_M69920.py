from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import enum, time

class M69920:
    class SUPPLY_MODE(enum.Enum):
        CURRENT_MODE = 1
        POWER_MODE = 0


    def __init__(self, device_sn="", *, mode=0, lim_current=0, lim_power=0) -> None:
        self.target_device_sn = device_sn
        self.serial_port = None
        self.device_id = ""
        logger = bsl_logger()
        logger.info(f"Initiating bsl_instrument - M69920({device_sn})...")
        if self._serial_connect():
            logger.info("M69920 Monochromator lamp's power supply connected!")
            self._update_lamp_op_status()
            self._update_lamp_power_status()
            self.lamp_OFF()
            self.set_lamp_mode(mode)
            self.set_lamp_current_limit(lim_current)
            self.set_lamp_power_limit(lim_power)
            self.set_lamp_current(0.0)
            self.set_lamp_power(0)
            logger.success("READY - M69920 Monochromator lamp's power supply.")
        else:
            logger.error(f"FAILED to connect to M69920 Monochromator lamp's power supply!\n\n\n")
            raise bsl_type.DeviceConnectionFailed
        pass

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None

    def _serial_connect(self) -> bool:
        try:
            self.serial = bsl_serial(inst.M69920, self.target_device_sn)
        except Exception as e:
            logger.error(f"{type(e)}")
            
        if self.serial.serial_port is None:
            return False
        return self.serial.serial_port.is_open

    def lamp_ON(self) -> None:
        self.serial.writeline('START')
        self._update_lamp_op_status()
        if self.is_lamp_ON:
            logger.success("    M69920 lamp turned ON.")
        else:
            logger.error("    Failed to turn ON - M69920 Monochromator_Lamp's Power Supply")
            raise bsl_type.DeviceOperationError
        time.sleep(0.2)
        pass
    
    def lamp_OFF(self) -> None:
        self.serial.writeline('STOP')
        self._update_lamp_op_status()
        if not self.is_lamp_ON:
            logger.success("    M69920 lamp turned OFF.")
        else:
            logger.error("    Failed to turn OFF - M69920 Monochromator_Lamp's Power Supply")
            raise bsl_type.DeviceOperationError
        time.sleep(0.2)
        pass

    def set_lamp_mode(self, mode:SUPPLY_MODE) -> None:
        if self.is_lamp_ON:
            logger.error("    Lamp need to be turned OFF before changing PWR mode!")
            self.lamp_OFF()
            
        if mode == self.SUPPLY_MODE.CURRENT_MODE:
            # Set MODE=1 for current mode operation
            self.serial.writeline('MODE=1')
        else:
            # Set MODE=0 for power mode operation
            self.serial.writeline('MODE=0')
        
        self._update_lamp_op_status()
        if self.mode != mode:
            logger.error(f"    FAILED to change M69920 Operation mode!")
            raise bsl_type.DeviceInconsistentError
        time.sleep(0.2)
        pass

    def lock_front_panel(self) -> None:
        # Set COMM=1 to lock front panel access
        self.serial.writeline('COMM=1')
        
        self._update_lamp_op_status()
        if self.frontpanel_lock != True:
            logger.error(f"    FAILED to lock M69920 front panel!")
            raise bsl_type.DeviceInconsistentError
        time.sleep(0.2)
        pass

    def unlock_front_panel(self) -> None:
        # Set COMM=0 to unlock front panel access
        self.serial.writeline('COMM=0')
        
        self._update_lamp_op_status()
        if self.frontpanel_lock == True:
            logger.error(f"    FAILED to unlock M69920 front panel!")
            raise bsl_type.DeviceInconsistentError
        time.sleep(0.2)
        pass

    def set_lamp_current(self, current:float) -> None:
        # Check if current power supply mode is current mode
        if self.mode == self.SUPPLY_MODE.CURRENT_MODE:
            logger.error(f"    FAILED to set M69920 lamp current, power supply is in POWER_MODE!")
            raise bsl_type.DeviceInconsistentError
        # Check if the desired current is smaller than current limits
        if current >= self.current_limit:
            logger.error(f"    FAILED to set M69920 lamp current to {current:.1f} since current limit is set to {self.current_limit:.1f}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'A-PRESET={current:.1f}'
        self.serial.writeline(msg)
        time.sleep(0.2)
        self._update_lamp_op_status()
        self._update_lamp_power_status()
        if self.preset_current != current:
            logger.error(f"    FAILED to set M69920 lamp current to {current:.1f} with read back current {self.preset_current:.1f}!")
            raise bsl_type.DeviceInconsistentError
        logger.success(f"    M69920 lamp current set to {self.preset_current:.1f}")    
        time.sleep(0.2)   
        pass
    
    def set_lamp_power(self, power:int) -> None:
        # Check if current power supply mode is current mode
        if self.mode == self.SUPPLY_MODE.POWER_MODE:
            logger.error(f"    FAILED to set M69920 lamp current, power supply is in CURRENT_MODE!")
            raise bsl_type.DeviceInconsistentError
        # Check if the desired current is smaller than current limits
        if power >= self.power_limit:
            logger.error(f"    FAILED to set M69920 lamp power to {power:04d} since current limit is set to {self.power_limit:04d}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'P-PRESET={power:04d}'
        self.serial.writeline(msg)
        time.sleep(0.2)
        self._update_lamp_op_status()
        self._update_lamp_power_status()
        if self.preset_power != power:
            logger.error(f"    FAILED to set M69920 lamp power to {power:04d} with read back power {self.preset_power:04d}!")
        logger.success(f"    M69920 lamp power set to {self.preset_power:04d}")       
        time.sleep(0.2)
        pass
    
    def set_lamp_current_limit(self, lim_I) -> None:
        # Check if the desired current is smaller than current limits
        if lim_I <= self.preset_current:
            logger.error(f"    FAILED to set M69920 lamp current_limit to {lim_I:.1f} since current limit is smaller than preset_current {self.preset_current:.1f}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'A-LIM={lim_I:.1f}'
        self.serial.writeline(msg)
        time.sleep(0.2)
        self._update_lamp_op_status()
        self._update_lamp_power_status()
        if self.current_limit != lim_I:
            logger.error(f"    FAILED to set M69920 lamp current_limit to {lim_I:.1f} with read back current {self.current_limit:.1f}!")
            raise bsl_type.DeviceInconsistentError
        logger.success(f"    M69920 lamp current_limit set to {self.current_limit:.1f}")       
        time.sleep(0.2)
        pass

    def set_lamp_power_limit(self, lim_P) -> None:
        # Check if the desired current is smaller than current limits
        if lim_P <= self.preset_power:
            logger.error(f"    FAILED to set M69920 lamp power_limit to {lim_P:04d} since it's smaller than preset power {self.preset_power:04d}!")
            raise bsl_type.DeviceInconsistentError
            
        msg = f'P-LIM={lim_P:04d}'
        self.serial.writeline(msg)
        time.sleep(0.2)
        self._update_lamp_op_status()
        self._update_lamp_power_status()
        if self.power_limit != lim_P:
            logger.error(f"    FAILED to set M69920 lamp power_limit to {lim_P:04d} with read back power {self.power_limit:04d}!")
        logger.success(f"    M69920 lamp power_limit set to {self.power_limit:04d}")       
        time.sleep(0.2)
        pass

    def _update_lamp_op_status(self) -> None:
        time.sleep(0.2)
        # Request status register from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('STB?')
        resp = self.serial.serial_port.readline()

        # Make sure reply from the power supply satisfy format.
        assert len(resp == 5)
        # Parse the status bit from incomming msg
        h_status = int(resp[3:5],16)

        # Check bit-7 for lamp status
        if (h_status &0b1000_0000) != 0:
            self.is_lamp_ON = True
        else:
            self.is_lamp_ON = False
        # Check bit-5 for power_supply limit mode
        if (h_status &0b0010_0000) != 0:
            self.mode = self.SUPPLY_MODE.POWER_MODE
        else:
            self.mode = self.SUPPLY_MODE.CURRENT_MODE
        # Check bit-3 for errors
        if (h_status &0b0000_1000) != 0:
            logger.error("Monochromator Power Supply ERROR detected!")
            self._read_error_register()
        # Check bit-2 for front panel lock status
        if (h_status &0b0000_0100) != 0:
            self.mode = self.frontpanel_lock = True
        else:
            self.mode = self.frontpanel_lock = False
            logger.error("Monochromator Power Supply front panel is not locked, take caution!")
        # Check bit-1 for power_supply limit status
        if (h_status &0b0000_0010) != 0:
            logger.error("Monochromator Power Supply LIMIT REACHED, please adjust output or increase PWR/CUR limits!")
        # Check bit-0 for interlock status
        if (h_status &0b0000_0001) == 0:
            logger.error("Monochromator Power Supply INTERLOCK ERROR, please confirm interlock status!")
        self._read_error_register()
        pass
    
    def _update_lamp_power_status(self) -> None:
        self.cur_current = self._read_current_current()
        self.cur_voltage = self._read_current_voltage()
        self.cur_power = self._read_current_power()
        self.cur_lamp_hours = self._read_current_lamp_hours()
        self.preset_current = self._read_set_current()
        self.preset_power = self._read_set_power()
        self.current_limit = self._read_set_current_limit()
        self.power_limit = self._read_set_power_limit()
        logger.trace("  Lamp power related parameters updated from the power supply M69920.")
        pass

    def _read_error_register(self) -> None:
        time.sleep(0.2)
        # Request status register from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('ESR?')
        resp = self.serial.serial_port.readline()

        # Make sure reply from the power supply satisfy format "ESRXX".
        assert len(resp == 5)
        # Parse the status bit from incomming msg
        h_status = int(resp[3:5],16)

        # Check bit-7 for power ON error
        if (h_status &0b1000_0000) != 0:
            logger.error("    M69920 Lamp Power Supply Power ON ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-6 for User Request Error
        if (h_status &0b0100_0000) != 0:
            logger.error("    M69920 Lamp Power Supply User Request ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-5 for Command Error
        if (h_status &0b0010_0000) != 0:
            logger.error("    M69920 Lamp Power Supply Command ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-4 for Execution Error
        if (h_status &0b0001_0000) != 0:
            logger.error("    M69920 Lamp Power Supply Execution ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-3 for Device Dependant Error
        if (h_status &0b0000_1000) != 0:
            logger.error("    M69920 Lamp Power Supply Device Dependant ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-2 for Query Error
        if (h_status &0b0000_0100) != 0:
            logger.error("    M69920 Lamp Power Supply Query ERROR!")
            raise bsl_type.DeviceOperationError
        # Check bit-1 for Request Control Error
        if (h_status &0b0000_0010) != 0:
            logger.error("    M69920 Lamp Power Supply Request Control ERROR!")
            raise bsl_type.DeviceOperationError
        pass

    def _read_current_current(self) -> float:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('AMPS?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XX.X" Amps.
        assert len(resp == 4)
        return float(resp.decode('utf-8'))

    def _read_current_voltage(self) -> float:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('VOLTS?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XX.X" Volts.
        assert len(resp == 4)
        return float(resp.decode('utf-8'))

    def _read_current_power(self) -> int:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('WATTS?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XXXX" Watts.
        assert len(resp == 4)
        return int(resp.decode('utf-8'))

    def _read_current_lamp_hours(self) -> int:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('LAMP HRS?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XXXX" Hours.
        assert len(resp == 4)
        return int(resp.decode('utf-8'))
    
    def _read_set_current(self) -> float:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('A-PRESET?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XX.X" Amps.
        assert len(resp == 4)
        return float(resp.decode('utf-8'))

    def _read_set_power(self) -> int:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('P-PRESET?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XXXX" Watts.
        assert len(resp == 4)
        return int(resp.decode('utf-8'))

    def _read_set_current_limit(self) -> float:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('A-LIM?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XX.X" Amps.
        assert len(resp == 4)
        return float(resp.decode('utf-8'))

    def _read_set_power_limit(self) -> int:
        time.sleep(0.2)
        # Request current reading from the power supply.
        self.serial.flush_read_buffer()
        self.serial.writeline('P-LIM?')
        resp = self.serial.serial_port.readline()
        # Make sure reply from the power supply satisfy format "XXXX" Watts.
        assert len(resp == 4)
        return int(resp.decode('utf-8'))
    
    def _get_lamp_id(self):
        pass
    
    def lamp_shut_down(self) -> None:
        self.lamp_OFF()
        self.set_lamp_current(0.0)
        self.set_lamp_power(0.0)
        self.unlock_front_panel()
        pass

    def close(self) -> None:
        if self.serial_port is not None:
            self.lamp_shut_down()
            self.serial.close()
            del self.serial
        logger.info(f"CLOSED - M69920 Monochromator lamp's power supply \"{self.device_id}\"\n\n\n")
        pass