import h5py, cv2, concurrent.futures
import numpy as np
from pathlib import Path
from loguru import logger

class mantis_file:
    def __init__(self, path: Path, x3_conv: bool = False, conv_param: float = 0.8, origin=(0,0)):
        if not isinstance(path, Path):
            path = Path(path)

        logger.trace(f"Init mantisCam video file {path}.")
        self.path = path
        self.x3_conv = x3_conv
        self.conv_param = conv_param

        # ------------------
        # Dark-sub parameters
        # ------------------
        self._dark_sub_enabled = False
        self._dark_frame = None  # Will store a single dark frame or 4D volume if needed

    # -----------------------------------------------------------
    # NEW: Provide a method to supply and enable dark subtraction
    # -----------------------------------------------------------
    def apply_dark_subtraction(self, dark_data: np.ndarray):
        """
        Enable dark subtraction by providing a dark frame (or frames).
        
        Parameters
        ----------
        dark_data : np.ndarray
            Shape can be:
              - [H, W] for single-channel
              - [H, W, C] if channels=3
              - [N, H, W, C] if you want per-frame dark volumes (less common).
            
            If your file has shape [N,H,W,C], then either:
              - Provide [H,W,C], which we broadcast over all frames
              - Or [N,H,W,C] for exact frame-by-frame matching.
            
            Negative results are clamped to 0.
        """
        self._dark_frame = dark_data.astype(np.float32)
        self._dark_sub_enabled = True
        logger.info(f"Dark subtraction enabled with shape={self._dark_frame.shape}.")

    def disable_dark_subtraction(self):
        """Disable dark subtraction."""
        self._dark_sub_enabled = False
        self._dark_frame = None
        logger.info("Dark subtraction disabled.")

    # ---------------------------------------------------------
    # Overwrite how frames are retrieved if dark_sub is enabled
    # ---------------------------------------------------------
    def __getitem__(self, i) -> np.ndarray:
        if self.x3_conv:
            with h5py.File(self.path, 'r') as file:
                raw_frame = np.array(file['camera']['frames'][i])
                frame = self.__conv_opencv(raw_frame)
        else:
            with h5py.File(self.path, 'r') as file:
                frame = np.array(file['camera']['frames'][i])
        return self._maybe_sub_dark(frame, frame_idx=i)

    @property
    def frames(self) -> np.ndarray:
        '''
        Return all frames in shape [N, H, W, C].
        If dark subtraction is enabled, subtract the stored dark_data and clamp negative.
        '''
        with h5py.File(self.path, 'r') as file:
            raw = np.array(file['camera']['frames'])  # shape [N,H,W,C]
        if self.x3_conv:
            raw = self.__conv_opencv(raw)
        return self._maybe_sub_dark(raw)

    def _maybe_sub_dark(self, frames: np.ndarray, frame_idx: int = None) -> np.ndarray:
        """
        Internal helper: if dark-sub is enabled, subtract self._dark_frame.
        - If frames => shape [N,H,W,C], we check if dark_frame matches that shape or
          can be broadcast. 
        - If frames => shape [H,W,C], we check if dark_frame matches as well.
        """
        if not self._dark_sub_enabled or self._dark_frame is None:
            return frames

        # Convert input to float for subtraction
        frames_f32 = frames.astype(np.float32)

        # If dark_frame has shape [N,H,W,C] but frames shape is [N,H,W,C], do direct subtract
        if (frames_f32.ndim == 4) and (self._dark_frame.ndim == 4) \
           and (frames_f32.shape == self._dark_frame.shape):
            frames_f32 -= self._dark_frame
        # If dark_frame has shape [H,W,C] (or [H,W], [H,W,1]) we broadcast
        elif (self._dark_frame.ndim <= 3) and (frames_f32.ndim == 4):
            # e.g. frames_f32 = [N,H,W,C], dark_frame=[H,W,C]
            frames_f32 -= self._dark_frame
        # If single frame => shape [H,W,C] or [H,W], we do the same logic
        elif (frames_f32.ndim == self._dark_frame.ndim):
            frames_f32 -= self._dark_frame
        else:
            logger.warning(f"Dark-sub shape mismatch: frames {frames_f32.shape}, dark {self._dark_frame.shape}. Attempting broadcast subtraction.")
            frames_f32 -= self._dark_frame

        # clamp negative
        np.clip(frames_f32, 0, None, out=frames_f32)
        return frames_f32.astype(np.uint16)

    # ---------------------------------------------------------
    # Rest of your original code below...
    # ---------------------------------------------------------
    def __conv_opencv(self, frames: np.ndarray) -> np.ndarray:
        filter = np.array([[1 +  self.conv_param, - self.conv_param]])
        if len(frames.shape) == 4:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {executor.submit(self.__process_frame_cv2, frame, filter): i for i, frame in enumerate(frames)}
            
                results = [None] * len(frames)
                for future in concurrent.futures.as_completed(futures):
                    index = futures[future]
                    results[index] = future.result()
                return np.array(results)
        else:
            return self.__process_frame_cv2(frames, filter)

    def __process_frame_cv2(self, frame: np.ndarray, filter: np.ndarray) -> np.ndarray:
        frame_float = np.flip(frame).astype(np.float32)
        result = cv2.filter2D(frame_float, -1, filter)
        return np.roll(np.flip(result), 1, axis=1).astype(np.uint16)

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
    def exposure_times(self) -> np.ndarray:
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['integration-time-expected'])

    @property
    def timestamps(self) -> np.ndarray:
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['timestamp'])

    @property
    def frames_GS_high_gain(self) -> np.ndarray:
        return self.frames[:,:,0:self.n_cols//2,:]

    @property
    def frames_GS_low_gain(self) -> np.ndarray:
        return self.frames[:,:,self.n_cols//2:,:]

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
        return (self.n_chans == 1)

    @property
    def raw_data_shape(self) -> 'tuple([int,int,int,int])':
        return (self.n_frames, self.n_rows, self.n_cols, self.n_chans)
    
    @property
    def frame_shape(self) -> 'tuple([int,int,int])':
        return (self.n_rows, self.n_cols, self.n_chans)