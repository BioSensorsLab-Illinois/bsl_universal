from __future__ import annotations

"""
Compatibility-safe instrument factory.

This sits above legacy drivers and does not alter underlying command/transport
flows, enabling architecture refactoring with minimal hardware risk.
"""

from importlib import import_module
import time
from typing import Any

from .registry import INSTRUMENT_SPECS, list_instrument_keys, resolve_instrument_key


class InstrumentFactory:
    """
    Lazy-loading instrument factory with retry safety.

    Notes
    -----
    The factory retries constructor calls to reduce transient initialization
    failures on hardware buses and converts ``SystemExit`` into typed exceptions.
    """

    def __init__(self):
        """
        Initialize an empty instrument class cache.
        """
        self._class_cache: dict[str, type] = {}

    def _get_class(self, name: str) -> type:
        """
        Resolve and cache the instrument class for ``name``.

        Parameters
        ----------
        name : str
            Logical instrument key.

        Returns
        -------
        type
            Instrument class object.
        """
        key = resolve_instrument_key(name)
        if key in self._class_cache:
            return self._class_cache[key]
        spec = INSTRUMENT_SPECS[key]
        module = import_module(spec.module_path)
        cls = getattr(module, spec.class_name)
        self._class_cache[key] = cls
        return cls

    def create(
        self,
        name: str,
        *args: Any,
        retries: int = 2,
        retry_delay_sec: float = 0.5,
        **kwargs: Any,
    ) -> Any:
        """
        Construct an instrument instance with retry protection.

        Parameters
        ----------
        name : str
            Logical instrument key.
        *args : Any
            Positional args for the instrument constructor.
        retries : int, optional
            Number of constructor retries after the first attempt, by default 2.
        retry_delay_sec : float, optional
            Delay between retries in seconds, by default 0.5.
        **kwargs : Any
            Keyword args for the instrument constructor.

        Returns
        -------
        Any
            Constructed instrument object.

        Raises
        ------
        RuntimeError
            If construction fails after retries.
        Exception
            Re-raises the last constructor exception when available.
        """
        cls = self._get_class(name)
        attempts = max(1, int(retries) + 1)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return cls(*args, **kwargs)
            except SystemExit as exc:
                last_exc = RuntimeError(
                    f'Instrument "{name}" initialization attempted to terminate process '
                    f"(SystemExit: {exc})."
                )
            except Exception as exc:
                last_exc = exc

            if attempt < attempts:
                time.sleep(max(0.0, float(retry_delay_sec)))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f'Failed to initialize instrument "{name}".')

    def available(self) -> tuple[str, ...]:
        """
        List available logical instrument keys.

        Returns
        -------
        tuple[str, ...]
            Sorted available keys.
        """
        return list_instrument_keys()


factory = InstrumentFactory()


def create_instrument(name: str, *args: Any, **kwargs: Any) -> Any:
    """
    Convenience wrapper for ``InstrumentFactory.create``.

    Parameters
    ----------
    name : str
        Logical instrument key.
    *args : Any
        Positional constructor args.
    **kwargs : Any
        Keyword constructor args.

    Returns
    -------
    Any
        Constructed instrument object.
    """
    return factory.create(name, *args, **kwargs)


def available_instruments() -> tuple[str, ...]:
    """
    Convenience wrapper for ``InstrumentFactory.available``.

    Returns
    -------
    tuple[str, ...]
        Sorted available keys.
    """
    return factory.available()
