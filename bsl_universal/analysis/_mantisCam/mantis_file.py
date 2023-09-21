import h5py,cv2,concurrent.futures
import numpy as np
from pathlib import Path
from loguru import logger

(GS_NIR_X, GS_NIR_Y) = (1,1)
(GS_RED_X, GS_RED_Y) = (1,2)
(GS_GREEN_X, GS_GREEN_Y) = (2,1)
(GS_BLUE_X, GS_BLUE_Y) = (2,2)

class mantis_file:
    def __init__(self, path: Path, x3_conv: bool = False, conv_param: float = 0.48):
        logger.trace(f"Init mantisCam video file {path}.")
        self.path = path
        self.x3_conv = x3_conv
        self.conv_param = conv_param

    def __getitem__(self, i) -> np.ndarray:
        if self.x3_conv:
            with h5py.File(self.path, 'r') as file:
                return self.__conv_opencv(np.array(file['camera']['frames'][i]))
        else:
            with h5py.File(self.path, 'r') as file:
                return np.array(file['camera']['frames'][i])
    

    def __conv_opencv(self, frames: np.ndarray) -> np.ndarray:
        filter = np.array([[1 +  self.conv_param, - self.conv_param]])
        if len(frames.shape) == 4:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {executor.submit(self.__process_frame_cv2, frame, filter): i for i, frame in enumerate(frames)}
            
                results = [None] * len(frames)
                for future in concurrent.futures.as_completed(futures):
                    # Retrieve original index of the frame
                    index = futures[future]
                    results[index] = future.result()
                return np.array(results)
        else:
            return self.__process_frame_cv2(frames,filter)


    def __process_frame_cv2(self, frame: np.ndarray, filter: np.ndarray) -> np.ndarray:
        # Ensure the frame is float for proper convolution. Convert it back to uint16 later.
        frame_float = np.flip(frame).astype(np.float32)
        result = cv2.filter2D(frame_float, -1, filter)
        return np.roll(np.flip(result), 1, axis=1)
    

    @property
    def file_name(self) -> str:
        return str(self.path.name)

    @property
    def system_infos(self) -> dict:
        sys_info = dict()
        with h5py.File(self.path, 'r') as file:
            for attr in file.attrs:
                sys_info[attr] = file.attrs[attr]
        return sys_info
    
    @property
    def frames(self) -> np.ndarray:
        '''
        Return all the frames inside this file with following shape:
        numpy.ndarray[#frame, #rows, #cols, #channels]
        '''
        with h5py.File(self.path, 'r') as file:
            if self.x3_conv:
                return self.__conv_opencv(np.array(file['camera']['frames']))
            else:
                return np.array(file['camera']['frames'])

    @property
    def exposure_times(self) -> np.ndarray:
        '''
        Return correspoding exposure times in us for all frames in file as a ndarray.
        '''
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['integration-time-expected'])
    
    @property
    def timestamps(self) -> np.ndarray:
        '''
        Return correspoding timestamps for all frames in file as a ndarray.
        '''
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['timestamp'])

    @property
    def frames_GS_high_gain(self) -> np.ndarray:
        with h5py.File(self.path) as file:
            return self.frames[:,:,0:self.n_cols//2,:]

    @property
    def frames_GS_low_gain(self) -> np.ndarray:
        with h5py.File(self.path) as file:
            return self.frames[:,:,self.n_cols//2:,:]

    # @property
    # def frames_GS_low_gain_NIR(self) -> np.ndarray:
    #     with h5py.File(self.path) as file:
    #         return self.frames_GS_low_gain_NIR()[:,GS_NIR_X::4,GS_NIR_Y::4,:]

    # @property
    # def frames_GS_low_gain_RGB(self) -> np.ndarray:
    #     with h5py.File(self.path) as file:
    #         return self.frames_GS_low_gain_NIR()[:,GS_NIR_X::4,GS_NIR_Y::4,:]

    
    @property
    def n_frames(self) -> int:
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[0]
    
    @property
    def n_rows(self) -> int:
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[1]

    @property
    def n_cols(self) -> int:
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[2]

    @property
    def n_chans(self) -> int:
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[3]
    
    @property
    def is_monochrome(self) -> bool:
        if self.n_chans == 1:
            return True
        return False

    @property
    def raw_data_shape(self) -> 'tuple([int,int,int,int])':
        '''
        Return the raw data shape of the file in following order:
        [#_frames, #_rows, #_cols, #_channels]
        '''
        return (self.n_frames, self.n_rows, self.n_cols, self.n_chans)
    
    @property
    def frame_shape(self) -> 'tuple([int,int,int])':
        '''
        Return the raw data shape of the file in following order:
        [#_rows, #_cols, #_channels]
        '''
        return (self.n_rows, self.n_cols, self.n_chans)
