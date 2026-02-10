"""
Stable exception aliases for the public API.

These map to the legacy instrument exceptions so existing behavior remains
unchanged while enabling cleaner imports from `bsl_universal.core`.
"""

from ..instruments._inst_lib.headers._bsl_type import _bsl_type as _legacy_type

CustomError = _legacy_type.CustomError
DeviceConnectionFailed = _legacy_type.DeviceConnectionFailed
DeviceOperationError = _legacy_type.DeviceOperationError
DeviceTimeOutError = _legacy_type.DeviceTimeOutError
DeviceInconsistentError = _legacy_type.DeviceInconsistentError

__all__ = [
    "CustomError",
    "DeviceConnectionFailed",
    "DeviceOperationError",
    "DeviceTimeOutError",
    "DeviceInconsistentError",
]
