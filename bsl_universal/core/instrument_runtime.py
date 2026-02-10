from __future__ import annotations

"""
Managed runtime wrapper and recovery utilities for hardware instruments.
"""

from dataclasses import dataclass
import time
from typing import Any, Callable, Optional

from loguru import logger

from .device_health import device_health_hub


@dataclass(frozen=True)
class RecoveryPolicy:
    """
    Recovery policy used by ``InstrumentRecoveryManager``.

    Parameters
    ----------
    operation_retries : int
        Number of retries after the first failed call.
    reconnect_on_error : bool
        Attempt reconnect on operation failure.
    reset_on_error : bool
        Attempt reset before reconnect on operation failure.
    recovery_delay_sec : float
        Delay between recovery attempts.
    """

    operation_retries: int = 2
    reconnect_on_error: bool = True
    reset_on_error: bool = True
    recovery_delay_sec: float = 0.2


class InstrumentRecoveryManager:
    """
    Runtime recovery controller for one instrument instance.
    """

    _RESET_METHOD_CANDIDATES = (
        "reset_controller",
        "reset_meter",
        "reset_system",
        "reset_connection",
        "reset_stage",
        "reset_supply",
        "reset_tear_calibration",
    )

    def __init__(
        self,
        *,
        device: Any,
        instrument_name: str,
        policy: RecoveryPolicy = RecoveryPolicy(),
    ) -> None:
        """
        Initialize the recovery manager.

        Parameters
        ----------
        device : Any
            Underlying instrument object.
        instrument_name : str
            Logical instrument key.
        policy : RecoveryPolicy, optional
            Retry/recovery policy, by default ``RecoveryPolicy()``.
        """
        self._device = device
        self._instrument_name = instrument_name
        self.policy = policy

    def _resolve_method(self, names: tuple[str, ...]) -> Optional[Callable[..., Any]]:
        for name in names:
            callback = getattr(self._device, name, None)
            if callable(callback):
                return callback
        return None

    def reconnect(self) -> bool:
        """
        Attempt reconnect using the instrument reconnect method.

        Returns
        -------
        bool
            True when reconnect succeeded.
        """
        callback = self._resolve_method(("reconnect",))
        if callback is None:
            return False
        try:
            result = callback()
            return True if result is None else bool(result)
        except Exception as exc:
            logger.warning("Reconnect failed for {}: {}", self._instrument_name, exc)
            return False

    def reset(self) -> bool:
        """
        Attempt reset using known instrument reset method names.

        Returns
        -------
        bool
            True when reset succeeded.
        """
        callback = self._resolve_method(self._RESET_METHOD_CANDIDATES)
        if callback is None:
            return False
        try:
            result = callback()
            return True if result is None else bool(result)
        except Exception as exc:
            logger.warning("Reset failed for {}: {}", self._instrument_name, exc)
            return False

    def recover(self) -> bool:
        """
        Run the configured recovery flow.

        Returns
        -------
        bool
            True when any recovery action succeeded.
        """
        if self.policy.reset_on_error and self.reset():
            return True
        if self.policy.reconnect_on_error and self.reconnect():
            return True
        return False

    def invoke(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Invoke a device method with bounded retry and recovery.

        Parameters
        ----------
        method_name : str
            Name of method on underlying instrument.
        *args : Any
            Positional arguments for method call.
        **kwargs : Any
            Keyword arguments for method call.

        Returns
        -------
        Any
            Method return value.

        Raises
        ------
        AttributeError
            Raised when method does not exist.
        Exception
            Re-raises final operation exception after retries.
        """
        callback = getattr(self._device, method_name, None)
        if not callable(callback):
            raise AttributeError(
                f'Instrument "{self._instrument_name}" has no callable method "{method_name}".'
            )

        attempts = max(1, int(self.policy.operation_retries) + 1)
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return callback(*args, **kwargs)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Operation {}.{} failed (attempt {}/{}): {}",
                    self._instrument_name,
                    method_name,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt >= attempts:
                    break
                recovered = self.recover()
                if not recovered:
                    logger.warning(
                        "No recovery path succeeded for {} before retry.",
                        self._instrument_name,
                    )
                time.sleep(max(0.0, float(self.policy.recovery_delay_sec)))

        raise last_error if last_error is not None else RuntimeError(
            f"Operation {self._instrument_name}.{method_name} failed."
        )


class SafeInstrumentProxy:
    """
    Proxy object that routes calls through recovery-managed invokes.
    """

    def __init__(self, manager: InstrumentRecoveryManager) -> None:
        """
        Initialize safe proxy.

        Parameters
        ----------
        manager : InstrumentRecoveryManager
            Recovery manager used to invoke methods.
        """
        self._manager = manager

    def __getattr__(self, method_name: str) -> Callable[..., Any]:
        """
        Resolve a method name into a recovery-managed callable.

        Parameters
        ----------
        method_name : str
            Method name on wrapped instrument.

        Returns
        -------
        Callable[..., Any]
            Callable that executes through recovery flow.
        """

        def _safe_call(*args: Any, **kwargs: Any) -> Any:
            return self._manager.invoke(method_name, *args, **kwargs)

        return _safe_call


class ManagedInstrument:
    """
    Stable runtime wrapper around an instrument driver instance.
    """

    def __init__(
        self,
        *,
        instrument_name: str,
        device: Any,
        model: str,
        device_type: str,
        serial_number: str,
        policy: RecoveryPolicy = RecoveryPolicy(),
    ) -> None:
        """
        Initialize managed wrapper.

        Parameters
        ----------
        instrument_name : str
            Logical instrument key.
        device : Any
            Underlying instrument object.
        model : str
            Device model string.
        device_type : str
            Device type string.
        serial_number : str
            Device serial identifier.
        policy : RecoveryPolicy, optional
            Recovery policy for managed invokes, by default ``RecoveryPolicy()``.
        """
        self.instrument_name = instrument_name
        self.model = model
        self.device_type = device_type
        self.serial_number = serial_number
        self._device = device
        self._closed = False
        self.recovery = InstrumentRecoveryManager(
            device=device,
            instrument_name=instrument_name,
            policy=policy,
        )
        self.safe = SafeInstrumentProxy(self.recovery)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._device, name)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(self._device)))

    def __enter__(self) -> "ManagedInstrument":
        """
        Enter context manager.

        Returns
        -------
        ManagedInstrument
            Current managed wrapper.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Exit context manager and close wrapped instrument.

        Returns
        -------
        bool
            Always ``False`` to keep exception propagation.
        """
        self.close()
        return False

    @property
    def raw(self) -> Any:
        """
        Return wrapped instrument object.

        Returns
        -------
        Any
            Underlying instrument driver.
        """
        return self._device

    def invoke(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Invoke wrapped method with recovery policy.

        Parameters
        ----------
        method_name : str
            Name of method on wrapped device.
        *args : Any
            Positional arguments.
        **kwargs : Any
            Keyword arguments.

        Returns
        -------
        Any
            Method return value.
        """
        return self.recovery.invoke(method_name, *args, **kwargs)

    def reconnect(self) -> bool:
        """
        Reconnect wrapped instrument and refresh monitor state.

        Returns
        -------
        bool
            True when reconnect succeeded.
        """
        ok = self.recovery.reconnect()
        if ok:
            try:
                self.serial_number = str(
                    getattr(self._device, "device_id", "")
                    or getattr(self._device, "device_sn", "")
                    or getattr(self._device, "target_device_sn", "")
                    or self.serial_number
                )
                device_health_hub.register_connection(
                    instrument_key=self.instrument_name,
                    model=self.model,
                    device_type=self.device_type,
                    serial_number=self.serial_number or "Unknown",
                )
            except Exception:
                pass
        return ok

    def reset(self) -> bool:
        """
        Reset wrapped instrument.

        Returns
        -------
        bool
            True when reset succeeded.
        """
        return self.recovery.reset()

    def close(self) -> None:
        """
        Close wrapped instrument and publish disconnected state.
        """
        if self._closed:
            return
        self._closed = True

        error_message = ""
        try:
            callback = getattr(self._device, "close", None)
            if callable(callback):
                callback()
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            try:
                device_health_hub.register_disconnection(
                    instrument_key=self.instrument_name,
                    model=self.model,
                    device_type=self.device_type,
                    serial_number=self.serial_number or "Unknown",
                    error_message=error_message,
                )
            except Exception:
                pass
