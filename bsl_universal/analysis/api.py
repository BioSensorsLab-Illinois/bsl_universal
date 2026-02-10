"""
High-level analysis constructors.

These helpers provide a clearer hierarchy while still delegating to the
existing analysis implementations.
"""

from pathlib import Path

from ._mantisCam.mantis_file import mantis_file
from ._mantisCam.mantis_file_GS import mantis_file_GS
from ._mantisCam.mantis_folder import mantis_folder
from ._mantisCam.mantis_folder_GS import mantis_folder_GS


def open_mantis_file(path: Path, **kwargs) -> mantis_file:
    """
    Open a standard MantisCam recording file.

    Parameters
    ----------
    path : Path
        Path to a `.h5` recording file.
    **kwargs
        Additional keyword arguments forwarded to ``mantis_file``.

    Returns
    -------
    mantis_file
        Loaded MantisCam file wrapper.
    """
    return mantis_file(path, **kwargs)


def open_mantis_folder(path: Path, **kwargs) -> mantis_folder:
    """
    Open a folder containing standard MantisCam files.

    Parameters
    ----------
    path : Path
        Folder path containing `.h5` recordings.
    **kwargs
        Additional keyword arguments forwarded to ``mantis_folder``.

    Returns
    -------
    mantis_folder
        Loaded folder wrapper.
    """
    return mantis_folder(path, **kwargs)


def open_mantis_gs_file(path: Path, **kwargs) -> mantis_file_GS:
    """
    Open a GSense-format MantisCam recording file.

    Parameters
    ----------
    path : Path
        Path to a GSense `.h5` recording file.
    **kwargs
        Additional keyword arguments forwarded to ``mantis_file_GS``.

    Returns
    -------
    mantis_file_GS
        Loaded GSense file wrapper.
    """
    return mantis_file_GS(path, **kwargs)


def open_mantis_gs_folder(path: Path, **kwargs) -> mantis_folder_GS:
    """
    Open a folder containing GSense-format MantisCam files.

    Parameters
    ----------
    path : Path
        Folder path containing GSense `.h5` recordings.
    **kwargs
        Additional keyword arguments forwarded to ``mantis_folder_GS``.

    Returns
    -------
    mantis_folder_GS
        Loaded GSense folder wrapper.
    """
    return mantis_folder_GS(path, **kwargs)


__all__ = [
    "open_mantis_file",
    "open_mantis_folder",
    "open_mantis_gs_file",
    "open_mantis_gs_folder",
]
