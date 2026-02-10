"""
Core primitives shared across the bsl_universal package.

This module introduces a stable high-level namespace while preserving
compatibility with legacy instrument internals.
"""

from .exceptions import (
    CustomError,
    DeviceConnectionFailed,
    DeviceInconsistentError,
    DeviceOperationError,
    DeviceTimeOutError,
)
from .device_health import device_health_hub
from .device_monitor_gui import start_device_monitor_window
from .instrument_runtime import ManagedInstrument, RecoveryPolicy, SafeInstrumentProxy
from .logging import init_logger

__all__ = [
    "CustomError",
    "DeviceConnectionFailed",
    "DeviceInconsistentError",
    "DeviceOperationError",
    "DeviceTimeOutError",
    "device_health_hub",
    "start_device_monitor_window",
    "ManagedInstrument",
    "RecoveryPolicy",
    "SafeInstrumentProxy",
    "init_logger",
]
