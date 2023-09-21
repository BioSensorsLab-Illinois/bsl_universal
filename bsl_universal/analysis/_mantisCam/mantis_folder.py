from pathlib import Path
import numpy as np
from .mantis_file import mantis_file
from numpy.typing import NDArray
from tqdm import tqdm
from loguru import logger
import re, os

class mantis_folder:
    def __init__(self, path:Path, sort_with_exp:bool=False, x3_conv:bool=False, x3_conv_param=0.48):
        """
        Load objects points for a folder of mantisCam recording files.

        Parameters
        ----------
        sort_with_exp : `bool`
            Sort all video files with the exposure time encoded in its file name.
            File name MUST contains exp time info in the format of "x.xms"

        Returns
        -------
        mantis_folder : `mantis_folder`
            A object with all information and data of mantisCam recoridings in the folder.
        """
        if type(path) is str:
            path = Path(path)
        self.path = path
        self.x3_conv = x3_conv
        self.x3_conv_param = x3_conv_param
        self.__videos = dict()
        self.__init_mantis_video_dict(sort_with_exp)
        
    def __extract_time_key(self, file_name):
        match = re.search(r'\d+\.\d+(?=ms)', file_name)
        return float(match.group())  # Extract the float value from the time string without the 'ms' unit

    def __init_mantis_video_dict(self, sort_with_exp:bool=True):
        filepaths = [f for f in self.path.iterdir() if f.is_file() and f.suffix == '.h5']
        for filepath in filepaths:
            self.__videos[filepath.name] = mantis_file(filepath, x3_conv=self.x3_conv, conv_param=self.x3_conv_param)
        if(sort_with_exp):
            self.__videos = dict(sorted(self.__videos.items(), key=lambda item: self.__extract_time_key(item[0])))

    def __getitem__(self,name:str) -> mantis_file:
        return self.__videos[name]

    @property
    def n_videos(self):
        return len(self.__videos)

    @property
    def name_videos(self):
        filenames = [f.name for f in self.path.iterdir() if f.is_file() and f.suffix == '.h5']
        sorted_filenames = sorted(filenames, key=lambda f: os.stat(os.path.join(self.path, f)).st_mtime)
        return sorted_filenames
    
    @property
    def arr_files(self) -> list[mantis_file]:
        """
        Return all the files in the mantisFolder object.

        Returns
        -------
        arr_videos : `numpy.ndarray`
            An array of all the video frames in all the mantisFiles.
            in the shape of [num_files]
        """
        return np.array(list(self.__videos.values()))
    
    @property
    def arr_videos(self) -> NDArray[np.uint16]:
        """
        Return all the frames in all of the files in the mantisFolder object.

        Returns
        -------
        arr_videos : `numpy.ndarray`
            An array of all the video frames in all the mantisFiles.
            in the shape of [num_files, n_row, n_col, n_channels]
        """
        file_shape = self.arr_files[0].raw_data_shape
        arr_size = self.n_videos *file_shape[0]*file_shape[1]*file_shape[2]*file_shape[3]*2/1000/1000/1000
        logger.warning(f"Your are trying to load the entire folder into a single dataset, this may crush your python kernel if your RAM is not enough! \nEstimate RAM Requirement: {arr_size:.2f}GB")
        return np.array([file.frames for file in tqdm(self.__videos.values(), desc="Loading Dataset")])
    

    def find_key(self, key:str) -> str:
        """
        Find the key of a file in the folder.

        Parameters
        ----------
        key : `str`
            The key to search for.

        Returns
        -------
        key : `str`
            The key of the file.
        """
        for file_name in self.name_videos:
            if key in file_name:
                return file_name
        raise ValueError(f"Key {key} not found in folder {self.path}")