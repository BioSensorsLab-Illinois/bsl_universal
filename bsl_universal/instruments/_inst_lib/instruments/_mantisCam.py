from typing import Any
from loguru import logger
import numpy as np
from datetime import datetime, timezone

from ..interfaces._bsl_serial import _bsl_serial as bsl_serial
from ..headers._bsl_inst_info import _bsl_inst_info_list as inst
from ..headers._bsl_logger import _bsl_logger as bsl_logger
from ..headers._bsl_type import _bsl_type as bsl_type

try:
    from MantisCam import Messenger
    import zmq
except ImportError:
    pass
import enum, sys, os, atexit, time
logger_opt = logger.opt(ansi=True)

class MantisCamCtrl:
    TIMEOUT_SEC = 120
    __ZMQ_CMD_DELAY = 0.01

    class FILE_SAVING_MODE(enum.Enum):
        CUSTOM = "Custom"; TIMSSTAMP = "Timestamp"

    def __init__(self, device_sn="", port_cmd_pub: int=60000, port_cmd_sub: int=60001, port_vid_sub: int=60011, *, log_level: str = "TRACE", is_GSENSE: bool = False):
        logger_opt.info(f"Initiating bsl_instrument - MantisCam({device_sn})...")
        url_prefix = 'tcp://127.0.0.1:'

        self.url_cmd_pub = url_prefix + str(port_cmd_pub)
        self.url_cmd_sub = url_prefix + str(port_cmd_sub)
        self.url_vid_sub = url_prefix + str(port_vid_sub)
        
        self.log_level = log_level
        self.is_recording = False
        self.__e_exp_time = 50
        self.__e_exp_matched = False
        self.__is_GSENSE = is_GSENSE
        
        self.cur_exp_time_ms = 0

        self.__logger_init()
        self.__zmq_init()
        time.sleep(1)
        logger.success(f"Camera - ZMQ interface connected, camera initlized!")
        self.set_file_name(time_stamp_only=True)
        return


    def __zmq_init(self):
        # Initialize ZMQ for receiving video metadata and command, and send commands
        self.ctx = zmq.Context()
        self.cmd = Messenger(self.ctx, self.url_cmd_pub, self.url_cmd_sub, 'cmd', '')
        self.vid = Messenger(self.ctx, None, self.url_vid_sub, 'vid', '')
        # We register ther termination function so we don't have to explicitly call it upon normal and abnormal termination
        atexit.register(self.__zmq_term)
        self.poller = zmq.Poller()
        self.poller.register(self.cmd.skt_sub, zmq.POLLIN)
        self.poller.register(self.vid.skt_sub, zmq.POLLIN)
        self.__zmq_send('cam', 'exp-00', dict([('exp-00', self.__e_exp_time)]))
        self.__zmq_send('widget', 'exp-00', dict([('exp-00', self.__e_exp_time)]))
        logger.success(f"Command PUB [{self.url_cmd_pub}] SUB [{self.url_cmd_sub}]")
        logger.success(f"Video SUB [{self.url_vid_sub}]")


    def __zmq_term(self):
        self.cmd.close()
        self.vid.close()
        self.ctx.term()
        logger.trace(f"ZMQ terminated.")

    def __zmq_vid_reset(self):
        self.vid.close()
        self.vid = Messenger(self.ctx, None, self.url_vid_sub, 'vid', '')
        self.poller.register(self.vid.skt_sub, zmq.POLLIN)
        logger.trace(f"Video socket reset.")


    def __zmq_update_mean(self, desired_frame_name: str, sub_frame_type:str='') -> float:
        skts = dict(self.poller.poll(timeout=0))
                        
        if self.vid.skt_sub in skts:
            topic, name, msg, frame_dump = self.vid.peak_frame()
            logger.trace(f"Topic '{topic}' received.")

            if topic != 'isp':
                return -1
            if 'frame_name' not in msg:
                return -1
            if msg['frame_name'] != desired_frame_name:
                return -1
            
            frame_name = msg['frame_name']
            logger.trace(f"Received frame {frame_name}.")

            if 'statistics' not in msg:
                return -1
            if frame_name != desired_frame_name:
                return -1
            if 'frame-mean' not in msg['statistics']:
                return -1
            
            if sub_frame_type != '':
                if sub_frame_type not in msg['statistics']:
                    return -1
                logger.trace(f"    Received frame mean {msg['statistics'][f"frame-mean-{sub_frame_type}"]} with sub-frame-type {sub_frame_type}.")
                return msg['statistics'][sub_frame_type]

            logger.trace(f"    Received frame mean {msg['statistics']['frame-mean']}.")
            return msg['statistics']['frame-mean']
        
        time.sleep(self.__ZMQ_CMD_DELAY)
        return -1



    def __zmq_recv(self):
        skts = dict(self.poller.poll(timeout=0))
        if self.cmd.skt_sub in skts:
            topic, name, msg = self.cmd.recv()
            if topic == 'file':
                if name == 'recording_status':
                    self.is_recording = msg['recording']
                        
        if self.vid.skt_sub in skts:
            # We always need to peak frame, because otherwise it will queue up in our receiving end
            topic, name, msg, frame_dump = self.vid.peak_frame()
            # If user hit run button (self.procedure_run), and we are waiting for exposure to match (that's why we need
            #   to read frame metadata at first place: see if the incoming frame exposure match our set exposure), and
            #   we are not waiting for complete. This limits the checking phase to the Smart mode, and only the period
            #   after set exposure and before start recording

            if topic == 'raw':
                if 'frame_meta' in msg:
                    if 'int-set' in msg['frame_meta']:
                        received_exposure_ms = round(float(msg['frame_meta']['int-set']), 0)
                        #logger.trace(f"Received frame exposure {received_exposure_ms}, expected frame exposure {self.__e_exp_time}.")
                        # If match, we procede to the next phase: recording
                        if received_exposure_ms == self.__e_exp_time:
                            self.__e_exp_matched = True
                        if self.__is_GSENSE:
                            self.__e_exp_matched = True
        time.sleep(self.__ZMQ_CMD_DELAY)


    def __zmq_send(self, topic: str, name: str, msg: Any):
        # Abstracted zmq command send with logging
        logger.trace(f"Sending t:n:m={topic}:{name}:{msg}")
        self.cmd.send(name, msg, topic=topic)
        time.sleep(self.__ZMQ_CMD_DELAY)


    def __logger_init(self):
        home_dir = os.path.expanduser('~')
        # Log to file and terminal at the same time
        logger.remove()
        logger.add(os.path.join(home_dir, 'MantisCam', 'AutoRecord', 'logs', datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S_%f')[:-3]+'.log'), 
                        enqueue=True, level=0, backtrace=True, diagnose=True,
                        format="{time:YYYY-MM-DD HH:mm:ss.SSSZZ} | {process: <5} | {level: <8} | {file}:{function}:{line} > {message}")
        logger.add(sys.stdout, 
                        enqueue=True, level=self.log_level, backtrace=True, diagnose=True,
                        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSSZZ}</green> | <magenta>{process: <5}</magenta> | <level>{level: <8}</level> | <blue>{file}:{function}:{line}</blue> > <level>{message}</level>")
        atexit.register(self.__logger_term)


    def __set_frames_per_file(self, frames: int):
        # Send frames per file value to the file saving process
        self.__zmq_send('file', 'frames_per_file', dict(frames_per_file=frames))

    
    def get_frame_mean_gs_hg(self, timeout_ms:int = 5000) -> float:
        """
        - Get the mean value of the High Gain frame.

        Parameters
        ----------
        timeout_ms : `int`
            (default to 5000)
            Timeout in milliseconds for the function to wait for the frame to be received.

        Returns
        -------
        mean : `float`
            Mean value of the High Gain frame.
        """
        return self.get_frame_mean_name('High Gain', timeout_ms)
            

    def get_frame_mean_gs_lg(self, timeout_ms:int = 5000) -> float:
        """
        - Get the mean value of the High Gain frame.

        Parameters
        ----------
        timeout_ms : `int`
            (default to 5000)
            Timeout in milliseconds for the function to wait for the frame to be received.

        Returns
        -------
        mean : `float`
            Mean value of the High Gain frame.
        """
        return self.get_frame_mean_name('Low Gain', timeout_ms)
            
    
    def get_frame_mean_name(self, frame_name:str="High Gain", sub_frame_type:str='', timeout_ms:int = 5000) -> float:
        """
        - Get the mean value of the High Gain frame.

        Parameters
        ----------
        frame_name : `str`
            (default to 'High Gain')
            Name of the frame to get the mean value from.
            Options: 'High Gain', 'Low Gain', others

        timeout_ms : `int`
            (default to 5000)
            Timeout in milliseconds for the function to wait for the frame to be received.

        sub_frame_type : `str`
            (default to '')
            Sub-frame type to get the mean value from.
            Options: 'red', 'green', 'blue'

        Returns
        -------
        mean : `float`
            Mean value of the High Gain frame.
        """
        self.__zmq_vid_reset()
        self.__zmq_recv()
        time_start = time.time()
        while True:
            mean = self.__zmq_update_mean(desired_frame_name=frame_name, sub_frame_type=sub_frame_type)
            if mean != -1:
                return mean
            if time.time() - time_start > timeout_ms/1000:
                logger.error(f"ERROR - Unable to receive {frame_name} frame, timed out!")
                raise bsl_type.DeviceTimeOutError

    

    def set_exposure_ms(self, exp_time_ms: float) -> None:
        """
        - Set the camera exposure time to desired value in milliseconds.

        Parameters
        ----------
        exp_time_ms : `int`
            Desired exposure time in milliseconds.
        """

        # Helper function to set camera and GUI exposure values
        self.__zmq_send('cam', 'exp-00', dict([('exp-00', exp_time_ms)]))
        self.__zmq_send('widget', 'exp-00', dict([('exp-00', exp_time_ms)]))
        cur_exp_time = self.__e_exp_time
        self.__e_exp_time = exp_time_ms
        self.__e_exp_matched = False
        time_start = time.time()
        self.__zmq_vid_reset()
        while True:
            self.__zmq_recv()
            if self.__e_exp_matched:
                self.cur_exp_time_ms = cur_exp_time
                if self.__is_GSENSE:
                    total_sleep_time = cur_exp_time/1000 + exp_time_ms/1000
                    time.sleep(total_sleep_time*4 + 2)
                logger.info(f"Camera - Exposure time set to {self.__e_exp_time}ms and verified.")
                break
            if time.time() - time_start > self.TIMEOUT_SEC:
                logger.error(f"ERROR - Camera exposure time not match, timed out!")
                raise bsl_type.DeviceTimeOutError


    def set_file_name(self, file_name: str="video", time_stamp_only:bool=False) -> None:
        """
        - Set the file name to be saved. 

        Parameters
        ----------
        file_name : `str`
            (ONLY used when time_stamp_only is set to False)
            Desired saving file name.
            Warning: If filename already existed in the saving directory, following files will have a 
            timestamp attached to the end.

        time_stamp_only : 'bool'
            (default to False)
            Enable timestamp only file name mode. No file_name string need to be provided then.
        """
        if time_stamp_only:
            self.__zmq_send('file', 'file_name', dict([('mode', 'Timestamp')]))
            logger.info(f'Camera recording filename changed to Timestamp only mode')
        else:
            self.__zmq_send('file', 'file_name', dict([('mode', 'Custom'), ('name', file_name)]))
            logger.info(f'Camera recording filename changed to {file_name}')


    def run_auto_exposure(self, frame_name:str='High Gain', sub_frame_type:str='', min_exp_ms = 1, max_exp_ms = 2500, target_mean = 30000, max_iter = 10, hysterisis=2000) -> bool:
        """
        - Run auto exposure to adjust the exposure time to reach the target mean value.

        Parameters
        ----------
        frame_name : `str`
            (default to 'hg')
            Channel to run auto exposure on. 
            Options: 'hg', 'lg', 'NIR', 'RGB' etc.,

        sub_frame_type : `str`
            (default to '')
            Sub-frame type to run auto exposure on.
            Options: 'red', 'green', 'blue'

        min_exp_ms : `int`
            (default to 1)
            Minimum exposure time in milliseconds.

        max_exp_ms : `int`
            (default to 2500)
            Maximum exposure time in milliseconds.

        target_mean : `int`
            (default to 30000)
            Target mean value for the exposure.

        max_iter : `int`
            (default to 10)
            Maximum iteration for the auto exposure to reach the target mean value.

        hysterisis : `int`
            (default to 2000)
            Hysterisis for the auto exposure to reach the target mean value.

        Returns
        -------
        result : `bool`
            True if the target mean value is reached, False if not.
        """
        for i in range(max_iter):
            cur_exp = self.__e_exp_time

            cur_mean = self.get_frame_mean_name(frame_name, sub_frame_type=sub_frame_type)
            cur_mean_offset = cur_mean - 1900
            target_mean_offset = target_mean - 1900

            if abs(cur_mean - target_mean) < hysterisis:
                logger.info(f"Auto-Exposure - Target mean {target_mean} value reached @ {cur_mean}!")
                return True
            
            exp_ratio = target_mean_offset/cur_mean_offset
            if cur_mean > 63000:
                exp_ratio = 0.2
            next_exp = np.round(cur_exp * exp_ratio, 2)
            logger.info(f"Auto-Exposure - Iteration {i+1}/{max_iter}, current exposure: {cur_exp}ms, current mean: {cur_mean}, next exposure: {next_exp}ms")
            
            if next_exp < min_exp_ms:
                next_exp = min_exp_ms
            if next_exp > max_exp_ms:
                next_exp = max_exp_ms

            self.set_exposure_ms(next_exp)

            if next_exp == min_exp_ms or next_exp == max_exp_ms:
                logger.warning(f"Auto-Exposure - Exposure time reached the limit, auto exposure terminated.")
                return False

        return False
            
        
            




    def set_folder_name(self, create_new_folder:bool=True, time_stamp_only:bool=False, folder_name: set="video"):
        """
        - Set the file name to be saved. 

        Parameters
        ----------
        create_new_folder : 'bool'
            (default to True)
            If set to False, all recording files will be saved to the ROOT folder of the saving path.

        time_stamp_only : 'bool'
            (default to False)
            Enable timestamp only folder_name mode. No folder_name string need to be provided then.

        folder_name : `str`
            (ONLY used when 'time_stamp_only' is set to False AND 'create_new_folder' is set to True)
            Desired saving folder name.
        """
        if create_new_folder:
            if time_stamp_only:
                self.__zmq_send('file', 'folder_name', dict([('mode', 'Timestamp')]))
                logger.info(f'Camera recording folder name changed to Timestamp only mode.')
            else:
                self.__zmq_send('file', 'folder_name', dict([('mode', 'Custom'), ('name', folder_name)]))
                logger.info(f'Camera recording folder name changed to {folder_name}.')
        else:
            self.__zmq_send('file', 'folder_name', dict([('mode', 'Do Not Create New Folder')]))
            logger.info(f"No new folder will be created for the recording files.")



    def set_start_record(self, n_frames: int = 100, wait_until_done: bool = True):
        """
        - Start recording with desired frame counts per file, optional blocking/non-blocking recording
        that is default to blocking recording.

        Parameters
        ----------
        n_frames : `int`
            (default to 100)
            Desired number of frame per file.

        wait_until_done : `bool`
            (default to True)
            Blocking/non-blocking recording select.
            If True: this function will halt until the recording is done and camera is ready again.
            If False: this function will return as soon as camera started recording.
        """
        logger.info(f"Camera - Start recording...")
        # Set the frame per file
        self.__set_frames_per_file(n_frames)
        # Set start recording to GUI and file saving process
        self.__zmq_send('file', 'record', dict(record=True))
        time_start = time.time()
        while True:
            self.__zmq_recv()
            if self.is_recording:
                break
            if time.time() - time_start > 5:
                logger.error(f"ERROR - Unable to start recording, timed out!")
                raise bsl_type.DeviceTimeOutError
        logger.info(f"Camera - Recording with {n_frames} frames per file and exposure time of {self.__e_exp_time}ms.")
        if wait_until_done:
            time_start = time.time()
            while True:
                self.__zmq_recv()
                if not self.is_recording:
                    break
                if time.time() - time_start > (self.__e_exp_time * n_frames)/500 + 20:
                    logger.error(f"ERROR - Unable to finish recording, timed out! timeout @ {time.time() - time_start:.0f} seconds.")
                    # raise bsl_type.DeviceTimeOutError
        logger.info("Camera - Recording Finished!")
        


    def __logger_term(self):
        logger.info("Auto-Recording Utility terminated.")
        logger.complete()