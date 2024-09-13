from ._thorlabs_apt_device.devices import BSC
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, sys
import numpy as np

class BSC203(BSC):
    """
    A class for ThorLabs APT device model BSC203.

    It is based off :class:`BSC`, but looking for a serial number starting with ``"70"`` and setting ``x = 1`` (should be ``x = 3``)--FOR FUTURE.

    :param serial_port: Serial port device the device is connected to.
    :param vid: Numerical USB vendor ID to match.
    :param pid: Numerical USB product ID to match.
    :param manufacturer: Regular expression to match to a device manufacturer string.
    :param product: Regular expression to match to a device product string.
    :param serial_number: Regular expression to match to a device serial number.
    :param home: Perform a homing operation on initialisation.
    :param invert_direction_logic: Invert the meaning of "forward" and "reverse" directions.
    :param swap_limit_switches: Swap "forward" and "reverse" limit switch values.
    """
    def __init__(self, serial_port=None, vid=None, pid=None, manufacturer=None, product=None, serial_number="70", location=None, home=False, invert_direction_logic=False, swap_limit_switches=True):
         super().__init__(serial_port=serial_port, vid=vid, pid=pid, manufacturer=manufacturer, product=product, serial_number=serial_number, location=location, x=1, home=home, invert_direction_logic=invert_direction_logic, swap_limit_switches=swap_limit_switches)

class BSC203_HDR50(BSC203):
    """
    A class for ThorLabs APT device model BSC203 with the HDR50 rotating stage.

    It is based off :class:`BSC203`, but with sensible homing and velocity parameters.

    For the HDR50, there are 66*409600 microsteps per revolution of the stage, defined in the datasheet

    :param closed_loop: Boolean to indicate the use of an encoded stage (the "E" in LNR502E) in closed-loop mode, default is False.
    :param serial_port: Serial port device the device is connected to.
    :param vid: Numerical USB vendor ID to match.
    :param pid: Numerical USB product ID to match.
    :param manufacturer: Regular expression to match to a device manufacturer string.
    :param product: Regular expression to match to a device product string.
    :param serial_number: Regular expression to match to a device serial number.
    :param home: Perform a homing operation on initialisation.
    :param invert_direction_logic: Invert the meaning of "forward" and "reverse" directions.
    :param swap_limit_switches: Swap "forward" and "reverse" limit switch values.
    """
    
   
    MOTOR_STAGE_RATIO = 66
    MOTOR_FREV_STEP = 409600
    MOTOR_RUN_STEP = int(0.45 / 360 * MOTOR_STAGE_RATIO * MOTOR_FREV_STEP)


    def __init__(self, serial_port=None, vid=None, pid=None, manufacturer=None, product=None, serial_number="70", location=None, home=False, invert_direction_logic=False, swap_limit_switches=True):
        self.inst = inst.BSC203_HDR50
        self.logger = bsl_logger(self.inst)
        self. __curr_step = None
        super().__init__(serial_port, vid, pid, manufacturer, product, serial_number, location, home, invert_direction_logic, swap_limit_switches)
        for bay_i, _ in enumerate(self.bays):
            for channel_i, _ in enumerate(self.channels):
                self.set_velocity_params(acceleration=self.MOTOR_FREV_STEP//10, max_velocity=100*self.MOTOR_FREV_STEP, bay=bay_i, channel=channel_i)
                #velocity params
                self.set_home_params(velocity=100*self.MOTOR_FREV_STEP,offset_distance=224000, bay=bay_i, channel=channel_i) 
                #homing params, might need adjustment individually
        self.logger.warning("Due to OPEN LOOP control, HDR50 is prone to errors, regular homing required.")
        time.sleep(0.3)
        self._home()
        self.logger.success("initial homing complete")
        return


    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None
    
    def _home(self, bay=0, channel=0):
        """
        Cause the rotation stage to rotate to its mechanical “home” position. 
        This should result in the marking to be pointing at "0"
        This is a blocking function
        """
        super().home(bay, channel)
        self.__curr_step = 0
        return self._blocker()
    
    def step(self, stepnum, called_by_home = False):
        """
        move in steps of 0.45 degrees, with 800 steps a revolution (home before use is advised)
        no negative values allowed for steps--FOR FUTURE UPGRADES
        This is a blocking function
        """
        if stepnum == 0:
            return self._blocker()

        if stepnum < 0:
            stepnum = 800-abs(stepnum)
            self.logger.warning("NEGATIVE VALUES NOT ALLOWED! GOING TO DESTINATION in POSITIVE direction...")

        if called_by_home:
            super().move_relative(stepnum*self.MOTOR_RUN_STEP)
            return self._blocker()

        if stepnum <= 100:    
            super().move_relative(stepnum*self.MOTOR_RUN_STEP)
        else:
            self.set_velocity_params(acceleration=self.MOTOR_FREV_STEP//10, max_velocity=200*self.MOTOR_FREV_STEP, bay=0, channel=0)
            time.sleep(0.3)
            super().move_relative(stepnum*self.MOTOR_RUN_STEP)
            self.set_velocity_params(acceleration=self.MOTOR_FREV_STEP//10, max_velocity=100*self.MOTOR_FREV_STEP, bay=0, channel=0)
            time.sleep(0.3)
        
        
        
        try:
            self.__curr_step += stepnum
            self.__curr_step = self.__curr_step % 800
        except:
            self.home()
            self.logger.error("did not home on startup, homing...")
        
        return self._blocker()
    

    def get_curr_angle(self, return_angle = False):
        """
        get the current OPEN LOOP angle of the device, 
        this angle will be close to the actual value but there is no guarentees.
        This is a none-blocking function, do not SPAM
        """
        if self.__curr_step == None: 
            self.logger.error(f"FAILED to get current angle on the HDR50 rotation stage, please home and try again!\n\n\n")
            return None
        self.logger.info(f"Current angle at {self.__curr_step * 0.45} degrees, or {self.__curr_step} steps.")
        if return_angle:
            return self.__curr_step * 0.45
        else:
            return 

    def _is_moving(self):
        """
        True: the system is moving
        False: the system is not moving
        """
        time.sleep(0.3)
        return (self.status['moving_forward'] or self.status['moving_reverse'])
    
    def _blocker(self):
        """
        private function to make functions blocking, when the motor is busy, wait.
        """
        time.sleep(0.3)
        while self._is_moving():
            time.sleep(0.1)
        return 

    def home(self, bay=0, channel=0):
        """
        Optimized homing algorithm. If the current position is very close to 0, it will home normally. 
        But if the current position is far from home, it will home in crazy mode. 
        Be careful, DON'T touch the stage when you use this--Bill Yang
        """
        stepnum = 800 - self.__curr_step
        if stepnum >= 750:
            self._home()
            self.__curr_step = 0
        else:
            self.set_velocity_params(acceleration=self.MOTOR_FREV_STEP//10, max_velocity=1000*self.MOTOR_FREV_STEP, bay=0, channel=0)
            time.sleep(0.3)
            self.step(stepnum-10, called_by_home=True)
            self.set_velocity_params(acceleration=self.MOTOR_FREV_STEP//10, max_velocity=100*self.MOTOR_FREV_STEP, bay=0, channel=0)
            time.sleep(0.3)
            self._home(bay, channel)
            self.__curr_step = 0
        return self._blocker()
    
    def set_angle(self, angle:int, precision = False):
        """
        set the angle of the HDR50
        precision == False; mode does not home before moving
        precision == True; mode homes before moving

        """
        doable_step = int(np.floor(angle/0.45))
        doable_angle = doable_step * 0.45
        if doable_angle != angle:
            self.logger.warning(f"angle given not divisible by step size, moving to step {doable_step}, angle {doable_angle}")
            self.logger.warning(f"angle given not divisible by step size, your error is {angle - doable_angle}")
        else:
            self.logger.info(f"moving to step {doable_step}, angle {doable_angle}")
        if precision == True:    
            self.home()
            self.step(doable_step)
            self.logger.success(f"absolute angle manuver complete, step at {doable_step}, angle at {doable_angle}")
        else:
            self.step(doable_step-self.__curr_step)
        return self._blocker()



