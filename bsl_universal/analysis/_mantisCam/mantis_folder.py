from pathlib import Path
import numpy as np
from .mantis_file import mantis_file

class mantis_folder:
    def __init__(self, path:Path):
        if type(path) is str:
            path = Path(path)
        self.path = path
        self.__videos = dict()
        self.__init_mantis_video_dict()

    def __init_mantis_video_dict(self):
        filepaths = list(self.path.iterdir())
        for filepath in filepaths:
            if filepath.suffix == ".h5":
                self.__videos[filepath.name] = mantis_file(filepath)

    def __getitem__(self,name:str) -> mantis_file:
        return self.__videos[name]

    @property
    def n_videos(self):
        return len(self.__videos)

    @property
    def name_videos(self):
        return list(self.__videos.keys())
    
    @property
    def arr_videos(self):
        return np.array(list(self.__videos.values()))