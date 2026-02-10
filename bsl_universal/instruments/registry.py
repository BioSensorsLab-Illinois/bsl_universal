from __future__ import annotations

"""
Instrument metadata registry for compatibility-safe object construction.

This layer intentionally stores import paths only. Driver modules are loaded
on demand to avoid changing low-level hardware behavior until construction.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentSpec:
    """
    Static class import metadata for an instrument driver.

    Parameters
    ----------
    key : str
        Logical instrument key.
    module_path : str
        Absolute module import path.
    class_name : str
        Class symbol name inside ``module_path``.
    """

    key: str
    module_path: str
    class_name: str


INSTRUMENT_SPECS = {
    "PM100D": InstrumentSpec(
        key="PM100D",
        module_path="bsl_universal.instruments._inst_lib.instruments._PM100D",
        class_name="PM100D",
    ),
    "BSC203_HDR50": InstrumentSpec(
        key="BSC203_HDR50",
        module_path="bsl_universal.instruments._inst_lib.instruments._BSC203",
        class_name="BSC203_HDR50",
    ),
    "PM400": InstrumentSpec(
        key="PM400",
        module_path="bsl_universal.instruments._inst_lib.instruments._PM400",
        class_name="PM400",
    ),
    "DC2200": InstrumentSpec(
        key="DC2200",
        module_path="bsl_universal.instruments._inst_lib.instruments._DC2200",
        class_name="DC2200",
    ),
    "M69920": InstrumentSpec(
        key="M69920",
        module_path="bsl_universal.instruments._inst_lib.instruments._M69920",
        class_name="M69920",
    ),
    "CS260B": InstrumentSpec(
        key="CS260B",
        module_path="bsl_universal.instruments._inst_lib.instruments._CS260B",
        class_name="CS260B",
    ),
    "HR4000CG": InstrumentSpec(
        key="HR4000CG",
        module_path="bsl_universal.instruments._inst_lib.instruments._HR4000CG",
        class_name="HR4000CG",
    ),
    "RS_7_1": InstrumentSpec(
        key="RS_7_1",
        module_path="bsl_universal.instruments._inst_lib.instruments._RS_7_1",
        class_name="RS_7_1",
    ),
    "SP_2150": InstrumentSpec(
        key="SP_2150",
        module_path="bsl_universal.instruments._inst_lib.instruments._SP_2150",
        class_name="SP_2150",
    ),
    "USB_520": InstrumentSpec(
        key="USB_520",
        module_path="bsl_universal.instruments._inst_lib.instruments._Futek_USB_520",
        class_name="USB_520",
    ),
    "mantisCam": InstrumentSpec(
        key="mantisCam",
        module_path="bsl_universal.instruments._inst_lib.instruments._mantisCam",
        class_name="MantisCamCtrl",
    ),
}

INSTRUMENT_ALIASES = {
    "USB520": "USB_520",
    "MantisCam": "mantisCam",
}


def resolve_instrument_key(name: str) -> str:
    """
    Resolve aliases and validate an instrument key.

    Parameters
    ----------
    name : str
        User-provided key or alias.

    Returns
    -------
    str
        Canonical instrument key.

    Raises
    ------
    KeyError
        If the key is unknown.
    """
    key = INSTRUMENT_ALIASES.get(name, name)
    if key in INSTRUMENT_SPECS:
        return key
    available = ", ".join(sorted(INSTRUMENT_SPECS))
    raise KeyError(f'Unknown instrument "{name}". Available: {available}')


def list_instrument_keys() -> tuple[str, ...]:
    """
    Return all supported canonical instrument keys.

    Returns
    -------
    tuple[str, ...]
        Sorted tuple of supported instrument keys.
    """
    return tuple(sorted(INSTRUMENT_SPECS))
