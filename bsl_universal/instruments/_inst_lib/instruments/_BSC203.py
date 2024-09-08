import time
from thorlabs_apt_device import BSC

class BSC203(BSC):
    """
    A class for ThorLabs APT device model BSC203.

    It is based off :class:`BSC`, but looking for a serial number starting with ``"70"`` and setting ``x = 1`` (should be ``x = 3``).

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
    def __init__(self, serial_port=None, vid=None, pid=None, manufacturer=None, product=None, serial_number="70", location=None, home=True, invert_direction_logic=False, swap_limit_switches=True):
         super().__init__(serial_port=serial_port, vid=vid, pid=pid, manufacturer=manufacturer, product=product, serial_number=serial_number, location=location, x=1, home=home, invert_direction_logic=invert_direction_logic, swap_limit_switches=swap_limit_switches)

class BSC203_HDR50(BSC203):
    """
    A class for ThorLabs APT device model BSC203 with the HDR50 rotating stage.

    It is based off :class:`BSC203`, but with sensible default movement parameters configured for the actuator.

    For the HDR50, there are 66*409600 microsteps per revolution of the stage

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


    def __init__(self, serial_port=None, vid=None, pid=None, manufacturer=None, product=None, serial_number="70", location=None, home=True, invert_direction_logic=False, swap_limit_switches=True):
        super().__init__(serial_port, vid, pid, manufacturer, product, serial_number, location, home, invert_direction_logic, swap_limit_switches)

        for bay_i, _ in enumerate(self.bays):
            for channel_i, _ in enumerate(self.channels):
                self.set_velocity_params(acceleration=40960, max_velocity=10*4096000, bay=bay_i, channel=channel_i)
                self.set_home_params(velocity=10*4096000,offset_distance=224000, bay=bay_i, channel=channel_i)

    def __del__(self, *args, **kwargs) -> None:
        self.close()
        return None
    
    def home(self, bay=0, channel=0):
        super().home(bay, channel)
        return 1
    
    def step(self, stepnum):
        """
        move in steps of 0.45 degrees, with 800 steps a revolution
        home before use
        """
        super().move_relative(stepnum*self.MOTOR_RUN_STEP)
        return 1


