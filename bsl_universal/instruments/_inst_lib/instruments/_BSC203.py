from ._thorlabs_apt_device.devices import BSC
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type
import time, sys

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

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None
    
    def home(self, bay=0, channel=0):
        """
        Cause the rotation stage to rotate to its mechanical “home” position. 
        This should result in the marking to be pointing at "0"
        This is a none-blocking function, do not SPAM
        """
        super().home(bay, channel)
        self.__curr_step = 0
        return None
    
    def step(self, stepnum)->None:
        """
        move in steps of 0.45 degrees, with 800 steps a revolution (home before use is advised)
        no negative values allowed for steps--FOR FUTURE UPGRADES
        This is a none-blocking function, do not SPAM
        """
        if stepnum <= 0:
            stepnum = 800-abs(stepnum)
            self.logger.warning("NEGATIVE VALUES NOT ALLOWED! GOING TO DESTINATION in POSITIVE direction...")
            
        super().move_relative(stepnum*self.MOTOR_RUN_STEP)
        try:
            self.__curr_step += stepnum
            self.__curr_step = self.__curr_step % 800
        except:
            self.home()
            self.logger.error("did not home on startup, homing...")
    
    def get_curr_angle(self):
        """
        get the current OPEN LOOP angle of the device, 
        this angle will be close to the actual value but there is no guarentees.
        This is a none-blocking function, do not SPAM
        """
        if self.__curr_step == None: 
            self.logger.error(f"FAILED to get current angle on the HDR50 rotation stage, please home and try again!\n\n\n")
            return None
        self.logger.info(f"Current angle at {self.__curr_step * 0.45} degrees, or {self.__curr_step} steps.")
        return self.__curr_step * 0.45

    # def fast_homing_beta(self, bay=0, channel=0):
    #     """
    #     Optimized homing algorithm
    #     """
    #     stepnum = 800 - self.__curr_step
    #     super().move_relative((stepnum-10)*self.MOTOR_RUN_STEP)
    #     time.sleep(5+stepnum*0.01)
    #     super().home(bay, channel)
    #     self.__curr_step = 0
    #     return 1

