#%%
import numpy as np
from analysis import mantis_file_GS

file_path = "/Users/zz4/Downloads/subject_0_sample_0_view_0_2024-08-06_15-32-57_308_10000.h5"
pfile = mantis_file_GS(file_path)

frame_hg = pfile.frames_GS_high_gain[3,:]
frame_lg = pfile.frames_GS_low_gain[3,:]
# %%
I0 =   np.array(frame_hg[0::2,0::2], dtype=np.float32)
I90 =  np.array(frame_hg[1::2,1::2], dtype=np.float32)
I45 =  np.array(frame_hg[0::2,1::2], dtype=np.float32)
I135 = np.array(frame_hg[1::2,0::2], dtype=np.float32)

S1 = (I0 + I90 + I45 + I135)/2
S2 = I0 - I90
S3 = I45 - I135

DoLP = np.sqrt(S2**2 + S3**2)/S1
AoP = 0.5 * np.arctan2(S2,S3) / np.pi * 180 + 90
# %%
AoP_hist = np.histogram(AoP[275:700,180:880], 64)
# %%
pfile.frames_GS_high_gain
pfile.frames_AoP_high_gain