import h5py
import numpy as np
from pathlib import Path
from loguru import logger

class mantis_file_GS:
    """
    A class to handle MantisCam .h5 recordings, optionally with 2x2 filter arrays,
    high-gain and low-gain readouts, HDR reconstruction, and dark-frame subtraction.
    """

    K_HG_BSI = 1.813 * 16
    K_LG_BSI = 0.274 * 16
    K_HG_FSI = 2.931 * 16
    K_LG_FSI = 0.119 * 16
    Threshold_BSI  = 3300 * 16
    Threshold_FSI  = 3500 * 16
    Dark_Level_LG_BSI = 200
    Dark_Level_HG_BSI = 500
    Dark_Level_LG_FSI = 1000 
    Dark_Level_HG_FSI = 1300

    def __init__(
        self, 
        path: Path, 
        imager_type: str = "FSI", 
        is_2x2: bool = False, 
        origin=(0,0), 
        R_loc=(0,1), 
        G_loc=(1,0), 
        B_loc=(0,0), 
        SP_loc=(1,1),
        dark_frames=None,
        enable_dark_sub=False,
        use_filename_exp=True,
        filename_exp_reg=None
    ):
        """
        Parameters
        ----------
        path : Path
            Filepath to the .h5 file.
        imager_type : {"FSI", "BSI"}
            Determines certain calibration constants like threshold, dark levels, etc.
        is_2x2 : bool
            True if there's a 2×2 filter array physically over the sensor. 
            In that case, we skip every other pixel to extract color planes or the special plane.
        origin : (int,int)
            The top-left offset for the 2×2 pattern sub-sampling.
        R_loc, G_loc, B_loc, SP_loc : (int,int)
            The row,col offsets for each filter (R, G, B, or special plane) 
            if `is_2x2=True`. 
        dark_frames : dict or None
            A dictionary of {exposure_time: 2D darkFrame} for optional subtraction.
        enable_dark_sub : bool
            If True, apply dark subtraction on the entire raw frames. 
        use_filename_exp : bool
            If True, parse exposure times from the filename. Otherwise use file data.
        filename_exp_reg : str or None
            Custom regex for extracting exposure time from filename.

        Notes
        -----
        - The sensor shape is typically 2048×4096 for each frame: 
          left half is high-gain (HG), right half is low-gain (LG). 
        - If is_2x2=True, we do *not* automatically sub-sample in `frames`; 
          you still get Nx2048×4096. Instead you can use the sub-sampled properties.
        - By default, if dark subtraction is enabled, we set `param_b=0` 
          because we assume any black offset is handled by the dark frames.
        """
        if not isinstance(path, Path):
            path = Path(path)
        self.path = path

        self.is_2x2   = is_2x2
        self.origin   = origin
        self.R_loc    = R_loc
        self.G_loc    = G_loc
        self.B_loc    = B_loc
        self.SP_loc   = SP_loc

        self.dark_frames       = dark_frames if dark_frames else {}
        self.enable_dark_sub   = enable_dark_sub
        self.use_filename_exp  = use_filename_exp
        self.filename_exp_reg  = filename_exp_reg

        # Logging
        logger.trace(f"Init mantisCam video file {path}, is_2x2={is_2x2}.")

        # Set sensor constants
        if imager_type.upper() == "FSI":
            self.K_HG = self.K_HG_FSI
            self.K_LG = self.K_LG_FSI
            self.Threshold = self.Threshold_FSI
            self.Dark_Level_LG = self.Dark_Level_LG_FSI
            self.Dark_Level_HG = self.Dark_Level_HG_FSI
        else:  # BSI
            self.K_HG = self.K_HG_BSI
            self.K_LG = self.K_LG_BSI
            self.Threshold = self.Threshold_BSI
            self.Dark_Level_LG = self.Dark_Level_LG_BSI
            self.Dark_Level_HG = self.Dark_Level_HG_BSI

        self.K_RATIO = self.K_HG / self.K_LG

        # If dark subtraction is turned on, assume black offsets are handled by the dark frame => param_b=0
        if self.enable_dark_sub:
            self.param_b = 0
        else:
            self.param_b = self.K_RATIO * self.Dark_Level_LG - self.Dark_Level_HG

        # Cache the raw frames after dark-sub
        self._cached_dark_subbed_frames = None

        # HDR initialization placeholders
        self._hdr_inited   = False
        self._tone_mapping = None
        self._mid_tone     = None
        self._contrast     = None
        self._power        = None

    # -------------------------------------------------------------------------
    #   HDR Setup
    # -------------------------------------------------------------------------
    def init_HDR(self, tone_mapping="None", mid_tone=0.5, contrast=10, power=0.5):
        """
        Initialize HDR parameters. 
        After calling this, any property that returns HDR frames will use these settings.

        Parameters
        ----------
        tone_mapping : {"None", "compress", "enhance"}
            - "None": No tone map, purely linear HDR combination.
            - "compress": Simple gamma-based midrange compression.
            - "enhance": Simple sigmoid-based midrange enhancement.
        mid_tone : float
            Mid-tone reference for the "enhance" option.
        contrast : float
            Contrast factor for the "enhance" option.
        power : float
            Gamma exponent if "compress" is selected.
        """
        self._hdr_inited   = True
        self._tone_mapping = tone_mapping
        self._mid_tone     = mid_tone
        self._contrast     = contrast
        self._power        = power
        logger.info(f"HDR initialized with tone_mapping={tone_mapping}, mid_tone={mid_tone}, contrast={contrast}, power={power}.")

    def _ensure_hdr_inited(self):
        """
        If HDR not inited by user, use default parameters and log a warning.
        """
        if not self._hdr_inited:
            logger.warning("HDR was not initialized. Using default HDR parameters.")
            self.init_HDR("None", 0.5, 10, 0.5)

    # -------------------------------------------------------------------------
    #   MAIN GETTER FOR RAW FRAMES (with or without dark-sub)
    # -------------------------------------------------------------------------
    def _get_dark_subbed_frames(self) -> np.ndarray:
        """
        Loads the entire [N,H,W] from disk (channel=0).
        If enable_dark_sub is True, subtract the appropriate dark frame 
        per each frame's exposure time. Then clip negative to 0.
        Caches the result so repeated calls do not re-read from disk.

        Returns
        -------
        np.ndarray
            Array of shape [N, H, W], dtype=uint16
        """
        if self._cached_dark_subbed_frames is not None:
            return self._cached_dark_subbed_frames

        # 1) Load raw from disk
        with h5py.File(self.path, 'r') as file:
            raw = file['camera']['frames'][:,:,:,0]  # shape = [N,H,W], dtype=uint16

        # 2) If no dark sub, done
        if not self.enable_dark_sub or not self.dark_frames:
            self._cached_dark_subbed_frames = raw
            return raw

        # 3) Subtract per-frame
        out = []
        for i in range(raw.shape[0]):
            exptime = self._resolve_exposure(i)
            dark2D = self._get_dark_frame(exptime)  # shape [H,W] or 0
            frm = raw[i].astype(np.float32) - dark2D
            frm = np.clip(frm, 0, None)
            out.append(frm.astype(np.uint16))
        out = np.stack(out, axis=0)  # [N,H,W]

        self._cached_dark_subbed_frames = out
        return out

    # -------------------------------------------------------------------------
    #   EXPOSURE & DARK-FRAME LOGIC
    # -------------------------------------------------------------------------
    def _resolve_exposure(self, frame_idx=0) -> float:
        """
        Decide how to read exposure time: from filename or from the file data.
        If from data, pick the i-th frame’s exposure time (or median if out-of-range).

        Parameters
        ----------
        frame_idx : int
            The frame index for which we want the exposure time.

        Returns
        -------
        float
            The exposure time in microseconds (or an approximate).
        """
        if self.use_filename_exp:
            return self._parse_exposure_from_filename(self.path.name)
        else:
            with h5py.File(self.path, 'r') as f:
                expt_arr = f['camera']['integration-time-expected']
                if frame_idx < len(expt_arr):
                    return float(expt_arr[frame_idx])
                logger.warning(f"Frame {frame_idx} out of exptime array range, use median.")
                return float(np.median(expt_arr))

    def _parse_exposure_from_filename(self, filename: str) -> float:
        """
        Parse the exposure from the filename using either the custom regex
        or fallback heuristics.

        Returns
        -------
        float
            The exposure time or 0.0 if not found.
        """
        import re
        if self.filename_exp_reg:
            match = re.search(self.filename_exp_reg, filename)
            if match:
                return float(match.group())

        # fallback: look for <float> preceding ms
        match_ms = re.search(r'(\d+\.\d+)(?=ms)', filename)
        if match_ms:
            return float(match_ms.group(1))

        # else take the last number in the filename
        match_num = re.findall(r'(\d+\.?\d*)', filename)
        if match_num:
            return float(match_num[-1])

        logger.warning(f"Cannot parse exposure from filename={filename}, default=0.0")
        return 0.0

    def _get_dark_frame(self, exptime: float) -> np.ndarray:
        """
        Return the best dark frame for this exptime by picking the nearest key.

        Parameters
        ----------
        exptime : float
            The exposure time we want to match.

        Returns
        -------
        np.ndarray or int
            The 2D dark frame (shape [H,W]) or 0 if no dictionary.
        """
        if not self.dark_frames:
            return 0
        keys = list(self.dark_frames.keys())
        arr_keys = np.array(keys, dtype=float)
        idx_min = np.argmin(np.abs(arr_keys - exptime))
        chosen = arr_keys[idx_min]
        if abs(chosen - exptime) > 1e-6:
            logger.warning(f"No exact dark for exptime={exptime}, using closest dark={chosen}.")
        return self.dark_frames[chosen]

    # -------------------------------------------------------------------------
    #   PROPERTIES: RAW, HG, LG, 2x2, ETC.
    # -------------------------------------------------------------------------
    @property
    def file_name(self) -> str:
        """Return the filename of the .h5 file."""
        return str(self.path.name)

    @property
    def system_infos(self) -> dict:
        """
        Return a dict of system-level attributes stored in the file.
        """
        sys_info = {}
        with h5py.File(self.path, 'r') as file:
            for attr in file.attrs:
                sys_info[attr] = file.attrs[attr]
        return sys_info
    
    @property
    def frames(self) -> np.ndarray:
        """
        Return the entire dataset [N, 2048, 4096, 1] from disk, possibly dark-subtracted.
        If is_2x2 == True, we do NOT sub-sample here. 
        Dark sub is done on the entire NxHxW if enabled.

        Returns
        -------
        np.ndarray
            Shape [N, 2048, 4096, 1], dtype=uint16
        """
        subbed = self._get_dark_subbed_frames()  # [N, 2048, 4096]
        return subbed[..., np.newaxis]           # add channel dim

    @property
    def exposure_times(self) -> np.ndarray:
        """
        Return the integration times for all frames inside the HDF5.

        Returns
        -------
        np.ndarray
            The per-frame exposure times from the file dataset.
        """
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['integration-time-expected'])
    
    @property
    def timestamps(self) -> np.ndarray:
        """
        Return the timestamp for all frames inside the HDF5.

        Returns
        -------
        np.ndarray
            The per-frame timestamps from the file dataset.
        """
        with h5py.File(self.path, 'r') as file:
            return np.array(file['camera']['timestamp'])

    @property
    def frames_GS_high_gain(self) -> np.ndarray:
        """
        Return the high-gain portion (left half) of each frame, shape [N, 2048, 2048].

        Returns
        -------
        np.ndarray
            The left half of the sensor, possibly dark-subtracted if enabled.
        """
        full = self._get_dark_subbed_frames()  # Nx2048x4096
        return full[:, :, : (self.n_cols // 2)]

    @property
    def frames_GS_low_gain(self) -> np.ndarray:
        """
        Return the low-gain portion (right half) of each frame, shape [N, 2048, 2048].

        Returns
        -------
        np.ndarray
            The right half of the sensor, possibly dark-subtracted if enabled.
        """
        full = self._get_dark_subbed_frames()  # Nx2048x4096
        return full[:, :, (self.n_cols // 2) :]

    # -------------------------------------------------------------------------
    #   2×2 SUB-SAMPLING LOGIC
    # -------------------------------------------------------------------------
    def __get_2x2_subsample(self, frame_3d: np.ndarray, origin) -> np.ndarray:
        """
        Generic helper: sub-sample from shape [N,H,W] => [N,H/2,W/2],
        picking rows=origin[0]::2, cols=origin[1]::2.

        Parameters
        ----------
        frame_3d : np.ndarray
            The raw frames [N,H,W].
        origin : (int, int)
            The origin offset.

        Returns
        -------
        np.ndarray
            Sub-sampled array [N, H/2, W/2].
        """
        return frame_3d[:, origin[0]::2, origin[1]::2]

    @property
    def frames_2x2_subsample(self) -> np.ndarray:
        """
        If is_2x2=True, sub-sample the entire 2048×4096 by skipping every other row & col,
        shape => [N, 1024, 2048]. This is *not* splitted into HG or LG yet.

        Returns
        -------
        np.ndarray
            If is_2x2=True, shape [N, 1024, 2048].
            If is_2x2=False, returns the full sensor shape but logs a warning.
        """
        full = self._get_dark_subbed_frames()
        if not self.is_2x2:
            logger.warning("frames_2x2_subsample called but is_2x2=False. Returning the full frames.")
            return full
        return self.__get_2x2_subsample(full, self.origin)

    @property
    def frames_GS_high_gain_2x2(self) -> np.ndarray:
        """
        Sub-sample the high-gain portion if is_2x2=True.
        This yields shape [N, 1024, 1024].

        Returns
        -------
        np.ndarray
            The 2×2 sub-sampled high-gain frames.
        """
        hg = self.frames_GS_high_gain  # Nx2048x2048
        if not self.is_2x2:
            return hg
        return self.__get_2x2_subsample(hg, self.origin)
    
    @property
    def frames_GS_low_gain_2x2(self) -> np.ndarray:
        """
        Sub-sample the low-gain portion if is_2x2=True.
        This yields shape [N, 1024, 1024].

        Returns
        -------
        np.ndarray
            The 2×2 sub-sampled low-gain frames.
        """
        lg = self.frames_GS_low_gain  # Nx2048x2048
        if not self.is_2x2:
            return lg
        return self.__get_2x2_subsample(lg, self.origin)

    # -------------------------------------------------------------------------
    #   HDR (Property + Internal Reconstruction)
    # -------------------------------------------------------------------------
    @property
    def frames_GS_HDR(self) -> np.ndarray:
        """
        Return the HDR combination of high-gain and low-gain portions, shape [N,2048,2048].

        If init_HDR(...) wasn't called, defaults are used and a warning is logged.

        Returns
        -------
        np.ndarray
            HDR frames, shape [N,2048,2048], dtype=uint16.
        """
        self._ensure_hdr_inited()
        frame_HG = self.frames_GS_high_gain
        frame_LG = self.frames_GS_low_gain
        return self._HDR_reconstruction(
            frame_HG, 
            frame_LG,
            self._tone_mapping,
            self._mid_tone,
            self._contrast,
            self._power
        )

    def _HDR_reconstruction(
        self, frame_HG, frame_LG, tone_maping, mid_tone, contrast, power
    ) -> np.ndarray:
        """
        Internal function that blends high-gain & low-gain frames into a single HDR output.

        Returns
        -------
        np.ndarray
            The HDR frames, shape [N, H, W], dtype=uint16.
        """
        # same shape
        frames_HDR = np.zeros_like(frame_HG, dtype=np.float32)
        mask = (frame_HG <= self.Threshold)

        # If dark is subtracted, param_b=0. 
        frames_HDR[mask] = frame_HG[mask]
        frames_HDR[~mask] = self.K_RATIO * frame_LG[~mask] - self.param_b

        # Now scale from [0..K_RATIO*65535 - param_b] => [0..1]
        denom = (self.K_RATIO * 65535 - self.param_b)
        frames_HDR = frames_HDR / denom

        # Tone mapping
        tm = tone_maping.lower()
        if tm == "compress":
            frames_HDR = self.__tone_map_compress(frames_HDR, power=power)
        elif tm == "enhance":
            frames_HDR = self.__tone_map_enhance(frames_HDR, mid_tone=mid_tone, contrast=contrast)
        # else "none": pass

        return np.clip(frames_HDR * 65535, 0, 65535).astype(np.uint16)

    def __tone_map_compress(self, hdr_image, power=0.5):
        """
        Simple gamma-based tone mapping to compress midrange.

        Parameters
        ----------
        hdr_image : np.ndarray
            Float HDR in [0..1]
        power : float
            The gamma exponent

        Returns
        -------
        np.ndarray
            The tone-mapped HDR in [0..1]
        """
        return hdr_image ** power

    def __tone_map_enhance(self, hdr_image, mid_tone=0.5, contrast=10):
        """
        Simple sigmoid-based tone mapping to enhance midrange.

        Parameters
        ----------
        hdr_image : np.ndarray
            Float HDR in [0..1]
        mid_tone : float
            The midtone reference
        contrast : float
            The sigmoid contrast factor

        Returns
        -------
        np.ndarray
            The tone-mapped HDR in [0..1]
        """
        return 1.0 / (1.0 + np.exp(contrast * (mid_tone - hdr_image)))


    # -------------------------------------------------------------------------
    #   DEMOSAIC & UPSCALE FOR R/G/B & SPECIAL PIXELS
    # -------------------------------------------------------------------------
    def _extract_3_filters_2x2(self, frame_3d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        From a 2x2 sub-sampled frame [N, H, W], extract R, G, B planes by 
        taking pixels at (R_loc), (G_loc), (B_loc) in a repeated 2×2 pattern.

        Returns
        -------
        (R, G, B) : tuple of np.ndarray
            Each shape [N, H/2, W/2], dtype=uint16
        """
        R = frame_3d[:, self.R_loc[0]::2, self.R_loc[1]::2]
        G = frame_3d[:, self.G_loc[0]::2, self.G_loc[1]::2]
        B = frame_3d[:, self.B_loc[0]::2, self.B_loc[1]::2]
        return (R, G, B)

    def _demosaic_and_upscale(self, R: np.ndarray, G: np.ndarray, B: np.ndarray) -> np.ndarray:
        """
        Combine R, G, B planes (each [N, h, w]) into a single upscaled [N, 2h, 2w, 3] result.
        This is a placeholder for a 'state-of-the-art demosaicing' approach.

        Returns
        -------
        np.ndarray
            The demosaiced color result [N, 2h, 2w, 3], dtype=uint16
        """

        # Example approach: naive "repeat each pixel 2×2" to produce 2H×2W
        # In practice, you'd do an actual demosaicing or interpolation scheme.
        N, h, w = R.shape
        out_shape = (N, 2*h, 2*w, 3)
        out = np.zeros(out_shape, dtype=np.uint16)

        # Upsample R
        up_R = np.kron(R, np.ones((2,2))).astype(np.uint16)
        up_G = np.kron(G, np.ones((2,2))).astype(np.uint16)
        up_B = np.kron(B, np.ones((2,2))).astype(np.uint16)

        # Stack
        out[..., 0] = up_R
        out[..., 1] = up_G
        out[..., 2] = up_B
        return out
    
    def _upsample_special(self, SP: np.ndarray) -> np.ndarray:
        """
        Upsample the special filter plane [N, h, w] to [N, 2h, 2w].

        Returns
        -------
        np.ndarray
            Nx2h×2w special plane.
        """
        N, h, w = SP.shape
        out = np.kron(SP, np.ones((2,2))).astype(np.uint16)
        return out.reshape(N, 2*h, 2*w)

    @property
    def frames_GS_high_gain_RGB(self) -> np.ndarray:
        """
        Extract R, G, B planes from high-gain 2×2 sub-sampled data, then demosaic
        to produce [N,2×(H/2),2×(W/2),3] => [N,1024×2,1024×2,3] => [N,2048,2048,3].

        Returns
        -------
        np.ndarray
            The demosaiced and upsampled color frames from high-gain.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_high_gain_RGB called but is_2x2=False. Returning empty.")
            return np.array([])

        hg_2x2 = self.frames_GS_high_gain_2x2  # [N,1024,1024]
        R, G, B = self._extract_3_filters_2x2(hg_2x2)
        rgb = self._demosaic_and_upscale(R, G, B)
        return rgb

    @property
    def frames_GS_low_gain_RGB(self) -> np.ndarray:
        """
        Similar to frames_GS_high_gain_RGB but for the low-gain channel.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_low_gain_RGB called but is_2x2=False. Returning empty.")
            return np.array([])

        lg_2x2 = self.frames_GS_low_gain_2x2
        R, G, B = self._extract_3_filters_2x2(lg_2x2)
        return self._demosaic_and_upscale(R, G, B)

    @property
    def frames_GS_HDR_RGB(self) -> np.ndarray:
        """
        Similar to frames_GS_high_gain_RGB but for HDR frames. 
        If init_HDR(...) wasn't called, defaults are used.

        Returns
        -------
        np.ndarray
            Nx2048×2048×3 color frames in naive upsample from Nx1024×1024×3.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_HDR_RGB called but is_2x2=False. Returning empty.")
            return np.array([])

        self._ensure_hdr_inited()
        hdr_2d = self.frames_GS_HDR  # Nx2048x2048
        # sub-sample to Nx1024x1024
        hdr_2x2 = self.__get_2x2_subsample(hdr_2d, self.origin)
        R, G, B = self._extract_3_filters_2x2(hdr_2x2)
        return self._demosaic_and_upscale(R, G, B)

    @property
    def frames_GS_high_gain_SP(self) -> np.ndarray:
        """
        Extract the 'special' plane from high-gain 2×2 data, then upsample to 2× resolution 
        -> Nx1024×1024 becomes Nx512×512 for the special plane, then upsample to Nx1024×1024.

        Returns
        -------
        np.ndarray
            Nx1024×1024 special-plane frames in high-gain.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_high_gain_SP called but is_2x2=False. Returning empty.")
            return np.array([])

        hg_2x2 = self.frames_GS_high_gain_2x2  # Nx1024x1024
        SP = hg_2x2[:, self.SP_loc[0]::2, self.SP_loc[1]::2]  # Nx512x512
        return self._upsample_special(SP)

    @property
    def frames_GS_low_gain_SP(self) -> np.ndarray:
        """
        Special-plane from the low-gain 2×2 data, upsample to Nx1024×1024.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_low_gain_SP called but is_2x2=False. Returning empty.")
            return np.array([])

        lg_2x2 = self.frames_GS_low_gain_2x2  # Nx1024x1024
        SP = lg_2x2[:, self.SP_loc[0]::2, self.SP_loc[1]::2]  # Nx512x512
        return self._upsample_special(SP)

    @property
    def frames_GS_HDR_SP(self) -> np.ndarray:
        """
        Special-plane extracted from the HDR frames if is_2x2=True, 
        then upsample to Nx1024×1024.

        Returns
        -------
        np.ndarray
            Nx1024×1024 special-plane frames in HDR mode.
        """
        if not self.is_2x2:
            logger.warning("frames_GS_HDR_SP called but is_2x2=False. Returning empty.")
            return np.array([])

        self._ensure_hdr_inited()
        hdr_2d = self.frames_GS_HDR  # Nx2048x2048
        hdr_2x2 = self.__get_2x2_subsample(hdr_2d, self.origin)  # Nx1024x1024
        SP = hdr_2x2[:, self.SP_loc[0]::2, self.SP_loc[1]::2]    # Nx512x512
        return self._upsample_special(SP)

    # -------------------------------------------------------------------------
    #   SHAPES & MISC
    # -------------------------------------------------------------------------
    @property
    def n_frames(self) -> int:
        """Number of frames in this .h5 file."""
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[0]
    
    @property
    def n_rows(self) -> int:
        """Number of rows in each frame, typically 2048."""
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[1]

    @property
    def n_cols(self) -> int:
        """Number of columns in each frame, typically 4096."""
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[2]

    @property
    def n_chans(self) -> int:
        """Number of channels in each pixel, usually 1 for monochrome or 2×2 raw."""
        with h5py.File(self.path, 'r') as file:
            return file['camera']['frames'].shape[3]
    
    @property
    def is_monochrome(self) -> bool:
        """
        Return True if the camera is standard (no 2×2 color filter).
        """
        return not self.is_2x2

    @property
    def raw_data_shape(self):
        """
        Return (N, H, W, Channels) for the stored frames.
        """
        return (self.n_frames, self.n_rows, self.n_cols, self.n_chans)
    
    @property
    def frame_shape(self):
        """
        Return (H, W, Channels) for a single frame.
        """
        return (self.n_rows, self.n_cols, self.n_chans)