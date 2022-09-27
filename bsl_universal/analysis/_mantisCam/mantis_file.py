import h5py
import numpy as np
from loguru import logger
import scipy.ndimage as image

class mantis_file:
    def __init__(self, path):
        logger.trace(f"Init mantisCam video file {path}.")
        self.path = path
        self.RUN_CHARGE_SHR_CORRECTION = True
        self.FIR = [1.488, -0.488]

    def __getitem__(self, i) -> np.ndarray:
        with h5py.File(self.path, 'r') as file:
            if file['camera']['frames'].shape[3] == 3:
                return self.frame_charge_shr_correction(np.array(file['camera']['frames'][i]))
            else:
                return np.array(file['camera']['frames'][i])
    
    def __len__(self) -> int:
        return self.n_frames

    # This function run convolution along x axis for a single frame with shape row x col x chs
    def video_charge_shr_correction(self, data_in):
        return image.convolve1d(data_in, self.FIR, axis = 2, mode = 'constant', origin = -1)

    # This function run convolution along x axis for a single frame with shape row x col x chs
    def frame_charge_shr_correction(self, data_in):
        return image.convolve1d(data_in, self.FIR, axis = 1, mode = 'constant', origin = -1)

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
            if file['camera']['frames'].shape[3] == 3:
                return self.video_charge_shr_correction(np.array(file['camera']['frames']))
            else:
                return np.array(file['camera']['frames'])

    @property
    def frames_raw(self) -> np.ndarray:
        '''
        Return all the frames inside this file with following shape:
        numpy.ndarray[#frame, #rows, #cols, #channels]
        '''
        with h5py.File(self.path, 'r') as file:
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
        return self.frames[:,:,0:self.n_cols//2,:]
    @property
    def frames_GS_low_gain(self) -> np.ndarray:
        return self.frames[:,:,self.n_cols//2:,:]


    @property
    def frames_checkerboard_chan_0(self) -> np.ndarray:
        return self.__checkboard_frame_data_parsing(self.frames, channel=0)
    @property
    def frames_checkerboard_chan_1(self) -> np.ndarray:
        return self.__checkboard_frame_data_parsing(self.frames, channel=1)


    def frames_2x2_chan_n(self, channel:int=0) -> np.ndarray:
        return self.__2x2_frame_data_parsing(self.frames, channel=channel)
    @property
    def frames_2x2_chan_0(self) -> np.ndarray:
        return self.frames_2x2_chan_n(channel=0)
    @property
    def frames_2x2_chan_1(self) -> np.ndarray:
        return self.frames_2x2_chan_n(channel=1)
    @property
    def frames_2x2_chan_2(self) -> np.ndarray:
        return self.frames_2x2_chan_n(channel=2)
    @property
    def frames_2x2_chan_3(self) -> np.ndarray:
        return self.frames_2x2_chan_n(channel=3)


    def frames_3x3_chan_n(self, channel:int=0) -> np.ndarray:
        return self.__3x3_frame_data_parsing(self.frames, channel=channel)
    @property
    def frames_3x3_chan_0(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=0)
    @property
    def frames_3x3_chan_1(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=1)
    @property
    def frames_3x3_chan_2(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=2)
    @property
    def frames_3x3_chan_3(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=3)
    @property
    def frames_3x3_chan_4(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=4)
    @property
    def frames_3x3_chan_5(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=5)
    @property
    def frames_3x3_chan_6(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=6)
    @property
    def frames_3x3_chan_7(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=7)
    @property
    def frames_3x3_chan_8(self) -> np.ndarray:
        return self.frames_3x3_chan_n(channel=8)
    

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


    def __checkboard_frame_data_parsing(self, data_in:np.ndarray, channel:int=0) -> np.ndarray:
        #Calculate the frame size of the interleaving frame by keeping framecounts, number of rows, and number of channels the same
        #while dividing number of columns by 2
        shape_frame_raw = data_in.shape
        shape_frame_original = [shape_frame_raw[0],shape_frame_raw[1] , (shape_frame_raw[2] - shape_frame_raw[2]%2), shape_frame_raw[3]]
        shape_frame_interleave = [shape_frame_original[0], shape_frame_original[1], shape_frame_original[2]//2, shape_frame_raw[3]]
        data_out = np.empty(shape_frame_interleave, dtype=data_in.dtype)
        #Create a 2D boolean checker baord pattern then make it a mask with the same shape as the original frame
        n_row = shape_frame_original[1]
        n_col = shape_frame_original[2]
        cord = np.ogrid[0:n_row, 0:n_col]
        index = (cord[0] + cord[1])%2 == channel
        idx = np.broadcast_to(index[None,:,:,None], shape_frame_original)
        #Applying the checkerboard pattern mask to each frametype in the dataset
        #Also copying all attributes from the datasets in the original frame into the interleaving frames
        cur_dataset = data_in[:,:,:-1,:] if shape_frame_raw[2]%2 else data_in
        data_out = cur_dataset[idx].reshape(shape_frame_interleave)
        return data_out

    def __2x2_frame_data_parsing(self, data_in:np.ndarray, channel:int=0) -> np.ndarray:
        assert(channel>=0 and channel<4)
        frame_new = data_in[:,0:894, 0:1344,:]
        row = 0 if channel < 2 else 1
        col = 1 if channel % 2 else 0
        return frame_new[:, row::2, col::2, :]

    def __3x3_frame_data_parsing(self, data_in:np.ndarray, channel:int=0) -> np.ndarray:
        assert(channel>=0 and channel<9)
        frame_new = data_in[0:,:894, 0:1344,:]
        row = (channel)//3
        col = (channel) %3
        return frame_new[:, row::3, col::3, :]