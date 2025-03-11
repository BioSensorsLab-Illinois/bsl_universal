from pathlib import Path
import numpy as np
from .mantis_file_GS import mantis_file_GS
from numpy.typing import NDArray
from tqdm import tqdm
from loguru import logger
import re
import os

class mantis_folder_GS:
    def __init__(
        self, 
        path: Path, 
        sort_with_exp: bool = False, 
        imager_type: str = "FSI", 
        is_2x2: bool = False, 
        origin=(1,0), 
        R_loc=(0,1), 
        G_loc=(1,0), 
        B_loc=(0,0), 
        SP_loc=(1,1),
        dark_path=None,
        enable_dark_sub=None,    # If None, we decide automatically
        use_filename_exp=True,
        filename_exp_reg=None,
        force_dark_files=True
    ):
        """
        Load a folder of MantisCam .h5 files, optionally do dark subtraction.

        If dark_path is provided but enable_dark_sub is None,
        we force enable_dark_sub = True automatically.
        """
        if isinstance(path, str):
            path = Path(path)
        self.path = path
        self.__videos = dict()

        # If dark_path is provided but user didn't explicitly set enable_dark_sub
        if dark_path is not None and enable_dark_sub is None:
            enable_dark_sub = True

        self.dark_path = dark_path
        self.enable_dark_sub = enable_dark_sub or False  # final bool
        self.use_filename_exp = use_filename_exp
        self.filename_exp_reg = filename_exp_reg
        self.force_dark_files = force_dark_files

        # Attempt to load dark frames if requested
        if self.dark_path and self.enable_dark_sub:
            self._dark_frames = self._load_dark_frames(
                dark_path=self.dark_path, 
                use_filename_exp=self.use_filename_exp, 
                filename_exp_reg=self.filename_exp_reg,
                force_dark_files=self.force_dark_files
            )
        else:
            self._dark_frames = None

        self.__init_mantis_video_dict(
            sort_with_exp=sort_with_exp, 
            imager_type=imager_type, 
            is_2x2=is_2x2, 
            origin=origin, 
            R_loc=R_loc, 
            G_loc=G_loc, 
            B_loc=B_loc, 
            SP_loc=SP_loc
        )

    def init_HDR_for_all(self, tone_mapping="None", mid_tone=0.5, contrast=10, power=0.5):
        """
        Initialize HDR parameters for ALL mantis_file_GS objects in this folder.
        
        Parameters
        ----------
        tone_mapping : {"None", "compress", "enhance"}
            - "None": No tone mapping. 
            - "compress": Simple gamma-based midrange compression.
            - "enhance": Simple sigmoid-based midrange enhancement.
        mid_tone : float
            Mid-tone reference for the "enhance" option.
        contrast : float
            Contrast factor for the "enhance" option.
        power : float
            Gamma exponent if "compress" is selected.
        """
        from loguru import logger
        logger.info(f"Initializing HDR for all files in folder: tone_mapping={tone_mapping}, mid_tone={mid_tone}, contrast={contrast}, power={power}.")
        for video_obj in self.__videos.values():
            video_obj.init_HDR(tone_mapping, mid_tone, contrast, power)

    def __extract_time_key(self, file_name):
        """
        Legacy approach: look for <float>ms in filename for sorting. 
        If not found, fallback to something large so it sorts last.
        """
        match = re.search(r'\d+\.\d+(?=ms)', file_name)
        return float(match.group()) if match else 999999

    def __init_mantis_video_dict(
        self, 
        sort_with_exp: bool = True, 
        imager_type: str = "FSI", 
        is_2x2: bool = False, 
        origin=(1,0), 
        R_loc=(0,1), 
        G_loc=(1,0), 
        B_loc=(0,0), 
        SP_loc=(1,1)
    ):
        filepaths = [
            f for f in self.path.iterdir() 
            if f.is_file() and f.suffix == '.h5'
        ]
        for filepath in filepaths:
            self.__videos[filepath.name] = mantis_file_GS(
                path=filepath,
                imager_type=imager_type,
                is_2x2=is_2x2,
                origin=origin,
                R_loc=R_loc,
                G_loc=G_loc,
                B_loc=B_loc,
                SP_loc=SP_loc,
                dark_frames=self._dark_frames,       # pass the dark dictionary
                enable_dark_sub=self.enable_dark_sub,
                use_filename_exp=self.use_filename_exp,
                filename_exp_reg=self.filename_exp_reg
            )

        if sort_with_exp:
            self.__videos = dict(sorted(
                self.__videos.items(), 
                key=lambda item: self.__extract_time_key(item[0])
            ))

    def __getitem__(self, name: str) -> mantis_file_GS:
        return self.__videos[name]

    @property
    def n_videos(self):
        return len(self.__videos)

    @property
    def name_videos(self):
        filenames = [
            f.name for f in self.path.iterdir() 
            if f.is_file() and f.suffix == '.h5'
        ]
        sorted_filenames = sorted(
            filenames, 
            key=lambda f: os.stat(os.path.join(self.path, f)).st_mtime
        )
        return sorted_filenames
    
    @property
    def arr_files(self) -> list[mantis_file_GS]:
        """
        Return all the file objects in the mantisFolder object.
        """
        return np.array(list(self.__videos.values()))
    
    @property
    def arr_videos(self) -> NDArray[np.uint16]:
        """
        Return all frames in all of the files as a single numpy array.
        [n_files, n_frames, H, W, 1] or something similar.
        Warning: can be huge in memory.
        """
        file_shape = self.arr_files[0].raw_data_shape
        arr_size = (
            self.n_videos * file_shape[0] * file_shape[1] 
            * file_shape[2] * 2 / 1e9
        )
        logger.warning(
            f"Loading entire folder into memory. "
            f"Est. RAM usage = {arr_size:.2f} GB. "
            f"Proceed with caution!"
        )
        return np.array([
            file.frames for file in tqdm(
                self.__videos.values(), 
                desc="Loading Dataset"
            )
        ])
    
    def find_key(self, key: str) -> str:
        """
        Find the key of a file in the folder by substring match.
        """
        for file_name in self.name_videos:
            if key in file_name:
                return file_name
        raise ValueError(f"Key {key} not found in folder {self.path}")

    # --------------------------------------------------------------------------
    # LOAD DARK FRAMES
    # --------------------------------------------------------------------------
    def _load_dark_frames(self, dark_path, use_filename_exp, filename_exp_reg, force_dark_files):
        """
        Load dark frames from either a single .h5 file or all .h5 in a folder,
        returning {exposure_time: 2D mean dark frame}.
        """
        dp = Path(dark_path)
        dark_dict = {}

        if dp.is_file():
            logger.info(f"Loading single dark file: {dp}")
            new_dict = self._load_dark_file(
                dp, use_filename_exp, filename_exp_reg
            )
            dark_dict.update(new_dict)
        else:
            # It's a directory
            all_h5 = [f for f in dp.iterdir() if f.is_file() and f.suffix == '.h5']
            if not force_dark_files:
                all_h5 = [
                    f for f in all_h5 if re.search("dark", f.name, re.IGNORECASE)
                ]
            for f in all_h5:
                logger.info(f"Loading dark file: {f.name}")
                new_dict = self._load_dark_file(
                    f, use_filename_exp, filename_exp_reg
                )
                for expt, dframe in new_dict.items():
                    dark_dict.setdefault(expt, []).append(dframe)

        # Average any duplicates
        for expt in list(dark_dict.keys()):
            frames_list = dark_dict[expt]
            if isinstance(frames_list, list):
                stack = np.stack(frames_list, axis=0)
                dark_dict[expt] = np.mean(stack, axis=0)
        
        logger.info(f"Dark dictionary loaded with keys: {list(dark_dict.keys())}")
        return dark_dict

    def _load_dark_file(self, dark_file: Path, use_filename_exp, filename_exp_reg):
        """
        Return { exptime_float : 2D darkFrame } from this single file,
        using mean across frames[1:]. If only 1 frame, use frames[0:].
        """
        import h5py
        import numpy as np

        with h5py.File(dark_file, 'r') as f:
            frames_data = np.array(f['camera']['frames'][:])  # shape [N, H, W, 1]
            if frames_data.shape[0] <= 1:
                logger.warning(
                    f"Dark file {dark_file.name} has <2 frames. Using all frames for average."
                )
                to_avg = frames_data
            else:
                to_avg = frames_data[1:]
            dark_2d = np.mean(to_avg[..., 0], axis=0)  # [H, W]

            if use_filename_exp:
                exptime = self._parse_exposure_from_filename(dark_file.name, filename_exp_reg)
            else:
                expt_arr = np.array(f['camera']['integration-time-expected'])
                exptime = float(np.median(expt_arr)) if len(expt_arr) else 0.0

        return { exptime: dark_2d }

    def _parse_exposure_from_filename(self, filename: str, filename_exp_reg: str|None):
        """
        If user gave a custom regex, use it. Otherwise:
          1) look for float preceding 'ms'
          2) else last number
          3) else 0.0
        """
        if filename_exp_reg:
            match = re.search(filename_exp_reg, filename)
            if match:
                return float(match.group())
            else:
                logger.warning(
                    f"filename_exp_reg={filename_exp_reg} not found in {filename}, fallback=0.0"
                )
                return 0.0
        match_ms = re.search(r'(\d+\.\d+)(?=ms)', filename)
        if match_ms:
            return float(match_ms.group(1))
        match_num = re.findall(r'(\d+\.?\d*)', filename)
        if match_num:
            return float(match_num[-1])
        logger.warning(f"Unable to parse exptime from {filename}, fallback=0.0")
        return 0.0