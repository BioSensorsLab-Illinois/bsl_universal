#%%
import numpy as np
import matplotlib.pyplot as plt
from bsl_universal.analysis import mantis_file_GS

Red = mantis_file_GS("/Users/zz4/Downloads/FIlter position recordings/GS-0011F/GS_RGB_NIR_FSI_RED.h5")
Blue = mantis_file_GS("/Users/zz4/Downloads/FIlter position recordings/GS-0011F/GS_RGB_NIR_FSI_BLUE.h5")
Green = mantis_file_GS("/Users/zz4/Downloads/FIlter position recordings/GS-0011F/GS_RGB_NIR_FSI_GREEN.h5")
NIR = mantis_file_GS("/Users/zz4/Downloads/FIlter position recordings/GS-0011F/GS_RGB_NIR_FSI_NIR.h5")

#%%
visible = (Red.frames_GS_low_gain[1]*1).astype(np.uint16) + Blue.frames_GS_low_gain[0] + Green.frames_GS_low_gain[0]

plt.imshow(visible[0:10,0:10])
# %%
