from pathlib import Path
import numpy as np
from .mantis_file import mantis_file
from numpy.typing import NDArray
from tqdm import tqdm
from loguru import logger
import re, os, sys

logger.configure(
    handlers=[
        {
            "sink": sys.stderr,
            "format": "<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {function}:{line} - <level>{message}</level>"
        }
    ]
)

class mantis_folder:
    def __init__(self, path:Path, sort_with_exp:bool=False, x3_conv:bool=False, x3_conv_param=0.8):
        # ...
        pass

    # (same code as your original snippet)

    def apply_dark_sub_to_all(self, dark_data: np.ndarray):
        """
        Apply the same dark_data to every mantis_file in this folder.
        Each file will subtract it upon reading frames.
        
        Parameters
        ----------
        dark_data : np.ndarray
            The array of shape [H,W], [H,W,C], or even [N,H,W,C] 
            if you want different frames of dark for each file’s frames.
        """
        logger.info(f"Applying dark-sub to all files in folder {self.path}, shape={dark_data.shape}")
        for fkey, file_obj in self.__videos.items():
            file_obj.apply_dark_subtraction(dark_data)

    def disable_dark_sub_in_all(self):
        """
        Disable dark-sub in all files. 
        """
        logger.info(f"Disabling dark-sub in all files in folder {self.path}.")
        for file_obj in self.__videos.values():
            file_obj.disable_dark_subtraction()

    # rest of your code remains...