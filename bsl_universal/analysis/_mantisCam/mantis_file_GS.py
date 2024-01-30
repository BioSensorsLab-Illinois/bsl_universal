import h5py
import numpy as np
from pathlib import Path
from loguru import logger
import colour
from colour_demosaicing import (
    demosaicing_CFA_Bayer_Menon2007)

class mantis_file_GS:
    K_HG_BSI = 1.813 * 16
    K_LG_BSI = 0.274 * 16
    K_HG_FSI = 2.931 * 16
    K_LG_FSI = 0.119 * 16
    Threshold_BSI =  3300 * 16
    Threshold_FSI = 3500 * 16
    Dark_Level_LG_BSI = 200
    Dark_Level_HG_BSI = 500
    Dark_Level_LG_FSI = 1000 
    Dark_Level_HG_FSI = 1300

    def __init__(self, path: Path, imager_type:str="FSI", is_2x2:bool=False, origin=(1,0), R_loc=(0,1), G_loc=(1,0), B_loc=(0,0), SP_loc=(1,1)):
        logger.trace(f"Init mantisCam video file {path}.")
        self.path = path
        self.is_2x2 = is_2x2
        self.origin = origin
        self.R_loc = R_loc
        self.G_loc = G_loc
        self.B_loc = B_loc
        self.SP_loc = SP_loc
        if imager_type == "FSI":
            self.K_HG = self.K_HG_FSI
            self.K_LG = self.K_LG_FSI
            self.Threshold = self.Threshold_FSI
            self.Dark_Level_LG = self.Dark_Level_LG_FSI
            self.Dark_Level_HG = self.Dark_Level_HG_FSI
        elif imager_type == "BSI":
            self.K_HG = self.K_HG_BSI
            self.K_LG = self.K_LG_BSI
            self.Threshold = self.Threshold_BSI
            self.Dark_Level_LG = self.Dark_Level_LG_BSI
            self.Dark_Level_HG = self.Dark_Level_HG_BSI
        self.K_RATIO = self.K_HG/self.K_LG
        self.param_b = self.K_RATIO * self.Dark_Level_LG - self.Dark_Level_HG


    def __getitem__(self, i) -> np.ndarray:
        with h5py.File(self.path, 'r') as file:
            if self.is_2x2:
                return np.array(file['camera']['frames'][i][self.origin[0]::2, self.origin[1]::2, 0])
            else:
                return np.array(file['camera']['frames'][i][:,:,0])

    def __tone_map_compress(self, hdr_image, power:float=0.5):
        """
        Apply tone mapping to the HDR image to compress midrange while making lowlights and highlights more visible.
        """
        # Apply tone mapping: here using a simple sigmoid function
        return np.power(hdr_image, power)

    def __tone_map_enhance(self, hdr_image, mid_tone:float=0.5, contrast:float=10):
        """
        Apply tone mapping to the HDR image to compress midrange while making lowlights and highlights more visible.
        """
        # Apply tone mapping: here using a simple sigmoid function
        return  1 / (1 + np.exp(contrast * (mid_tone - hdr_image)))
        

            
    def __HDR_reconstruction(self, frame_HG, frame_LG, tone_maping:str="None", mid_tone:float=0.5, contrast:float=10, power:float=0.5) -> np.ndarray:
        frames_HDR = np.zeros(frame_HG.shape, dtype=np.float32)
        frames_HDR[frame_HG<=self.Threshold] = frame_HG[frame_HG<=self.Threshold]
        frames_HDR[frame_HG>self.Threshold]  = self.K_RATIO * frame_LG[frame_HG>self.Threshold] - self.param_b     
        frame_HDR = frames_HDR/(self.K_RATIO*65535 - self.param_b)
        if tone_maping.lower() == "compress":
            frame_HDR = self.__tone_map_compress(frame_HDR, power=power)
        elif tone_maping.lower() == "enhance":
            frame_HDR = self.__tone_map_enhance(frame_HDR, mid_tone=mid_tone, contrast=contrast)
        return np.clip(frame_HDR * 65535, 0, 65535).astype(np.uint16)

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
            return np.array(file['camera']['frames'][:,:,:,0])

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
            if self.is_2x2:
                frames_HG = self.frames[:, :, 0:self.n_cols//2]
                return frames_HG[:, self.origin[0]::2, self.origin[1]::2]
            else:
                return self.frames[:, :, 0:self.n_cols//2]

    @property
    def frames_GS_low_gain(self) -> np.ndarray:
        with h5py.File(self.path) as file:
            if self.is_2x2:
                frames_LG = self.frames[:, :, self.n_cols//2:]
                return frames_LG[:, self.origin[0]::2, self.origin[1]::2]
            else:
                return self.frames[:, :, self.n_cols//2:]

            
    @property
    def frames_GS_high_gain_RGB(self) -> np.ndarray:
        assert(self.is_2x2)
        R = self.frames_GS_high_gain[:,self.R_loc[0]::2,self.R_loc[1]::2]/65535.0
        G = self.frames_GS_high_gain[:,self.G_loc[0]::2,self.G_loc[1]::2]/65535.0
        B = self.frames_GS_high_gain[:,self.B_loc[0]::2,self.B_loc[1]::2]/65535.0
        bayer = np.zeros((self.n_frames, 1024, 1024), dtype=np.float32)
        RGB = np.zeros((self.n_frames, 1024, 1024, 3), dtype=np.uint16)
        bayer[:,0::2,0::2] = R
        bayer[:,1::2,0::2] = G
        bayer[:,0::2,1::2] = G
        bayer[:,1::2,1::2] = B
        for i in range(self.n_frames):
            RGB[i] = np.round(colour.cctf_encoding(demosaicing_CFA_Bayer_Menon2007(bayer[i], 'RGGB')) * 65535).astype(np.uint16)
        return RGB
            
    @property
    def frames_GS_low_gain_RGB(self) -> np.ndarray:
        assert(self.is_2x2)
        R = self.frames_GS_low_gain[:,self.R_loc[0]::2,self.R_loc[1]::2]/65535.0
        G = self.frames_GS_low_gain[:,self.G_loc[0]::2,self.G_loc[1]::2]/65535.0
        B = self.frames_GS_low_gain[:,self.B_loc[0]::2,self.B_loc[1]::2]/65535.0
        bayer = np.zeros((self.n_frames, 1024, 1024), dtype=np.float32)
        RGB = np.zeros((self.n_frames, 1024, 1024, 3), dtype=np.uint16)
        bayer[:,0::2,0::2] = R
        bayer[:,1::2,0::2] = G
        bayer[:,0::2,1::2] = G
        bayer[:,1::2,1::2] = B  
        for i in range(self.n_frames):
            RGB[i] = np.round(colour.cctf_encoding(demosaicing_CFA_Bayer_Menon2007(bayer[i], 'RGGB')) * 65535).astype(np.uint16)
        return RGB
    
    def __demoasic_SP(self, HDRraw) -> np.ndarray:
        assert(self.is_2x2)
        R = HDRraw[:,self.R_loc[0]::2,self.R_loc[1]::2]/65535.0
        G = HDRraw[:,self.G_loc[0]::2,self.G_loc[1]::2]/65535.0
        B = HDRraw[:,self.B_loc[0]::2,self.B_loc[1]::2]/65535.0
        bayer = np.zeros((self.n_frames, 1024, 1024), dtype=np.uint16)
        RGB = np.zeros((self.n_frames, 1024, 1024, 3), dtype=np.float32)
        bayer[:,0::2,0::2] = R
        bayer[:,1::2,0::2] = G
        bayer[:,0::2,1::2] = G
        bayer[:,1::2,1::2] = B  
        for i in range(self.n_frames):
            RGB[i] = np.round(colour.cctf_encoding(demosaicing_CFA_Bayer_Menon2007(bayer[i], 'RGGB')) * 65535).astype(np.uint16)
        return RGB
    
    @property
    def frames_GS_high_gain_SP(self) -> np.ndarray:
        assert(self.is_2x2)
        return self.frames_GS_high_gain[:,self.SP_loc[0]::2,self.SP_loc[1]::2]

    @property
    def frames_GS_low_gain_SP(self) -> np.ndarray:
        assert(self.is_2x2)
        return self.frames_GS_low_gain[:,self.SP_loc[0]::2,self.SP_loc[1]::2]
    
    def frames_GS_HDR(self, tone_mapping:str="None", mid_tone:float=0.5, contrast:float=10, power=0.5) -> np.ndarray:
        return self.__HDR_reconstruction(frame_HG=self.frames_GS_high_gain, frame_LG=self.frames_GS_low_gain, tone_maping=tone_mapping, mid_tone=mid_tone, contrast=contrast, power=power)
    
    def frames_GS_HDR_RGB(self, tone_mapping:str="None", mid_tone:float=0.5, contrast:float=10, power=0.5) -> np.ndarray:
        HDRraw = self.__HDR_reconstruction(frame_HG=self.frames_GS_high_gain, frame_LG=self.frames_GS_low_gain, tone_maping=tone_mapping, mid_tone=mid_tone, contrast=contrast, power=power)
        return self.__demoasic_SP(HDRraw)
    
    def frames_GS_HDR_SP(self, tone_mapping:str="None", mid_tone:float=0.5, contrast:float=10, power=0.5) -> np.ndarray:
        return self.__HDR_reconstruction(frame_HG=self.frames_GS_high_gain_SP, frame_LG=self.frames_GS_low_gain_SP, tone_maping=tone_mapping, mid_tone=mid_tone, contrast=contrast, power=power)
    
    
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
        if not self.is_2x2:
            return True
        return False

    @property
    def raw_data_shape(self) -> 'tuple([int,int,int,int])':
        '''
        Return the raw data shape of the file in following order:
        [#_frames, #_rows, #_cols, #_channels]
        '''
        return (self.n_frames, self.n_rows, self.n_cols)
    
    @property
    def frame_shape(self) -> 'tuple([int,int,int])':
        '''
        Return the raw data shape of the file in following order:
        [#_rows, #_cols, #_channels]
        '''
        return (self.n_rows, self.n_cols)
