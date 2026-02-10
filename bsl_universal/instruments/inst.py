from __future__ import annotations

from functools import wraps
from typing import Any, TYPE_CHECKING, Callable, cast
import weakref

from loguru import logger

from ..core.device_health import device_health_hub
from ..core.device_monitor_gui import start_device_monitor_window
from ..core.instrument_runtime import InstrumentRecoveryManager, RecoveryPolicy, SafeInstrumentProxy
from ..core.logging import init_logger as _init_core_logger
from .factory import create_instrument

if TYPE_CHECKING:
    from ._inst_lib.instruments._BSC203 import BSC203_HDR50 as BSC203_HDR50Driver
    from ._inst_lib.instruments._CS260B import CS260B as CS260BDriver
    from ._inst_lib.instruments._DC2200 import DC2200 as DC2200Driver
    from ._inst_lib.instruments._Futek_USB_520 import USB_520 as USB520Driver
    from ._inst_lib.instruments._HR4000CG import HR4000CG as HR4000CGDriver
    from ._inst_lib.instruments._M69920 import M69920 as M69920Driver
    from ._inst_lib.instruments._PM100D import PM100D as PM100DDriver
    from ._inst_lib.instruments._PM400 import PM400 as PM400Driver
    from ._inst_lib.instruments._RS_7_1 import RS_7_1 as RS_7_1Driver
    from ._inst_lib.instruments._SP_2150 import SP_2150 as SP_2150Driver
    from ._inst_lib.instruments._mantisCam import MantisCamCtrl


__is_logger_ready = False
__GLOBAL_LOG_LEVEL = "DEBUG"
__is_monitor_started = False
_DEL_HOOKED_CLASSES: set[type] = set()


def init_logger(LOG_LEVEL: str = "DEBUG") -> None:
    """
    Initialize shared logging for instrument operations.

    Parameters
    ----------
    LOG_LEVEL : str, optional
        Log level string accepted by Loguru, by default ``"DEBUG"``.

    Returns
    -------
    None
    """
    global __is_logger_ready
    global __GLOBAL_LOG_LEVEL
    __GLOBAL_LOG_LEVEL = LOG_LEVEL
    _init_core_logger(log_level=LOG_LEVEL)
    __is_logger_ready = True


def _ensure_logger_ready() -> None:
    """
    Ensure logger initialization has occurred.

    Returns
    -------
    None
    """
    if not __is_logger_ready:
        init_logger()


def _ensure_monitor_window() -> None:
    """
    Launch the optional device monitor window once per process.

    Returns
    -------
    None
    """
    global __is_monitor_started
    if __is_monitor_started:
        return
    try:
        __is_monitor_started = start_device_monitor_window()
    except Exception as exc:
        logger.warning("Device monitor window startup failed: {}", exc)
        __is_monitor_started = False


def _extract_device_info(instrument_name: str, device: Any) -> tuple[str, str, str]:
    """
    Extract display metadata for monitoring.

    Parameters
    ----------
    instrument_name : str
        Requested logical instrument key.
    device : Any
        Constructed instrument object.

    Returns
    -------
    tuple[str, str, str]
        ``(model, device_type, serial_number)``.
    """
    inst_meta = getattr(device, "inst", None)
    model = str(getattr(inst_meta, "MODEL", instrument_name))
    device_type = str(getattr(inst_meta, "TYPE", "Unknown"))

    serial_number = (
        getattr(device, "device_id", "")
        or getattr(device, "device_sn", "")
        or getattr(device, "target_device_sn", "")
    )

    if instrument_name == "mantisCam":
        try:
            identity_cb = getattr(device, "get_camera_identity", None)
            identity = identity_cb(refresh=True) if callable(identity_cb) else {}
            if isinstance(identity, dict):
                nickname = str(identity.get("nickname") or identity.get("display_name") or "").strip()
                camera_model = str(identity.get("model") or identity.get("model-name") or "").strip()
                if nickname:
                    model = nickname
                elif camera_model:
                    model = camera_model

                serial_candidate = str(
                    identity.get("serial") or identity.get("serial-number") or serial_number or ""
                ).strip()
                if serial_candidate:
                    serial_number = serial_candidate
                    try:
                        device.device_id = serial_candidate
                    except Exception:
                        pass

                camera_type = str(
                    identity.get("camera_type") or identity.get("camera_type_str") or ""
                ).strip()
                device_type = f"MantisCam/{camera_type}" if camera_type else "MantisCam"
            else:
                device_type = "MantisCam"
        except Exception:
            device_type = "MantisCam"

    if serial_number is None or str(serial_number).strip() == "":
        serial_number = "Unknown"
    return str(model), str(device_type), str(serial_number)


def _set_attr_safely(device: Any, name: str, value: Any) -> bool:
    """
    Attempt to set an attribute on an instrument instance.

    Parameters
    ----------
    device : Any
        Target instrument instance.
    name : str
        Attribute name.
    value : Any
        Attribute value.

    Returns
    -------
    bool
        True when assignment succeeds.
    """
    try:
        setattr(device, name, value)
        return True
    except Exception:
        return False


def _ensure_class_del_hook(device: Any) -> bool:
    """
    Install a class-level ``__del__`` hook that auto-releases managed instances.

    Parameters
    ----------
    device : Any
        Instrument instance whose class may need hook installation.

    Returns
    -------
    bool
        True when hook is installed or already available.
    """
    cls = type(device)
    if cls in _DEL_HOOKED_CLASSES:
        return True

    original_del = getattr(cls, "__del__", None)
    if getattr(original_del, "__bsl_del_wrapped__", False):
        _DEL_HOOKED_CLASSES.add(cls)
        return True

    def _del_with_release(self: Any) -> None:
        release_error = ""
        runtime = getattr(self, "_bsl_runtime", None)
        if isinstance(runtime, dict):
            close_cb = getattr(self, "close", None)
            close_is_monitored = bool(callable(close_cb) and getattr(close_cb, "__bsl_close_wrapped__", False))
            try:
                if callable(close_cb):
                    close_cb()
                else:
                    raise RuntimeError("Close callback is not callable")
            except Exception as exc:
                release_error = str(exc)
                if not close_is_monitored:
                    try:
                        device_health_hub.register_disconnection(
                            instrument_key=str(runtime.get("instrument_name", "Unknown")),
                            model=str(runtime.get("model", "Unknown")),
                            device_type=str(runtime.get("device_type", "Unknown")),
                            serial_number=str(runtime.get("serial_number", "Unknown")),
                            error_message=release_error,
                        )
                    except Exception:
                        pass

        if callable(original_del):
            try:
                original_del(self)
            except Exception:
                pass

    _set_attr_safely(_del_with_release, "__bsl_del_wrapped__", True)
    try:
        setattr(cls, "__del__", _del_with_release)
        _DEL_HOOKED_CLASSES.add(cls)
        return True
    except Exception:
        return False


def _finalize_instrument_release(
    instrument_name: str,
    model: str,
    device_type: str,
    serial_number: str,
    close_state: dict[str, bool],
    device_ref: "weakref.ReferenceType[Any]",
) -> None:
    """
    Finalizer callback that closes an instrument when it is garbage-collected.

    Parameters
    ----------
    instrument_name : str
        Logical instrument key.
    model : str
        Device model at registration time.
    device_type : str
        Device type at registration time.
    serial_number : str
        Device serial at registration time.
    close_state : dict[str, bool]
        Mutable close state shared with close wrapper.
    device_ref : weakref.ReferenceType[Any]
        Weak reference to the instrument object.

    Returns
    -------
    None
    """
    if bool(close_state.get("closed", False)):
        return

    error_message = ""
    latest_model = model
    latest_type = device_type
    latest_serial = serial_number

    try:
        device = device_ref()
        if device is not None:
            try:
                latest_model, latest_type, latest_serial = _extract_device_info(instrument_name, device)
            except Exception:
                pass

            close_cb = getattr(device, "close", None)
            if callable(close_cb):
                close_is_monitored = bool(getattr(close_cb, "__bsl_close_wrapped__", False))
                try:
                    close_cb()
                except Exception as exc:
                    error_message = str(exc)
                # Monitored close already updates monitor state.
                if close_is_monitored:
                    return

    except Exception as exc:
        error_message = str(exc)

    try:
        device_health_hub.register_disconnection(
            instrument_key=instrument_name,
            model=latest_model or model,
            device_type=latest_type or device_type,
            serial_number=latest_serial or serial_number,
            error_message=error_message,
        )
    except Exception:
        pass


def _attach_runtime_hooks(
    *,
    instrument_name: str,
    device: Any,
    model: str,
    device_type: str,
    serial_number: str,
) -> None:
    """
    Attach additive runtime recovery helpers to a concrete instrument object.

    Parameters
    ----------
    instrument_name : str
        Logical instrument key.
    device : Any
        Instrument object returned by the driver constructor.
    model : str
        Display model name.
    device_type : str
        Display device type.
    serial_number : str
        Device serial number.

    Returns
    -------
    None

    Notes
    -----
    These hooks are additive and never replace normal driver methods except for
    an instance-level close wrapper used to publish monitor state transitions.
    """
    recovery = InstrumentRecoveryManager(
        device=device,
        instrument_name=instrument_name,
        policy=RecoveryPolicy(),
    )

    safe_name = "safe" if not hasattr(device, "safe") else "bsl_safe"
    _set_attr_safely(device, safe_name, SafeInstrumentProxy(recovery))

    invoke_target: Callable[..., Any] = recovery.invoke
    if not callable(getattr(device, "invoke", None)):
        _set_attr_safely(device, "invoke", invoke_target)
    else:
        _set_attr_safely(device, "invoke_safe", invoke_target)

    def _reconnect_safe() -> bool:
        ok = recovery.reconnect()
        if not ok:
            return False
        try:
            next_model, next_type, next_sn = _extract_device_info(instrument_name, device)
            device_health_hub.register_connection(
                instrument_key=instrument_name,
                model=next_model,
                device_type=next_type,
                serial_number=next_sn,
            )
        except Exception:
            pass
        return True

    _set_attr_safely(device, "reconnect_safe", _reconnect_safe)
    _set_attr_safely(device, "reset_safe", recovery.reset)
    _set_attr_safely(
        device,
        "_bsl_runtime",
        {
            "instrument_name": instrument_name,
            "model": model,
            "device_type": device_type,
            "serial_number": serial_number,
        },
    )

    if instrument_name == "mantisCam":
        monitor_setter = getattr(device, "set_monitor_callbacks", None)
        if callable(monitor_setter):
            def _on_mantis_connected(next_model: str, next_type: str, next_sn: str, _detail: str) -> None:
                try:
                    device_health_hub.register_connection(
                        instrument_key=instrument_name,
                        model=next_model or model,
                        device_type=next_type or device_type,
                        serial_number=next_sn or serial_number,
                    )
                except Exception:
                    pass

            def _on_mantis_warning(next_model: str, next_type: str, next_sn: str, detail: str) -> None:
                try:
                    device_health_hub.register_failure(
                        instrument_key=instrument_name,
                        model=next_model or model,
                        device_type=next_type or device_type,
                        serial_number=next_sn or serial_number,
                        error_message=detail or "MantisCam runtime warning.",
                        unrecoverable=False,
                    )
                except Exception:
                    pass

            def _on_mantis_disconnected(next_model: str, next_type: str, next_sn: str, detail: str) -> None:
                try:
                    device_health_hub.register_disconnection(
                        instrument_key=instrument_name,
                        model=next_model or model,
                        device_type=next_type or device_type,
                        serial_number=next_sn or serial_number,
                        error_message=detail or "MantisCam backend disconnected.",
                    )
                except Exception:
                    pass

            try:
                monitor_setter(
                    on_connected=_on_mantis_connected,
                    on_warning=_on_mantis_warning,
                    on_disconnected=_on_mantis_disconnected,
                )
            except Exception:
                pass

    del_hook_ready = _ensure_class_del_hook(device)

    close_cb = getattr(device, "close", None)
    close_state = {"closed": False}

    if callable(close_cb) and not getattr(close_cb, "__bsl_close_wrapped__", False):
        @wraps(close_cb)
        def _close_with_monitor(*args: Any, **kwargs: Any) -> Any:
            if close_state["closed"]:
                return None
            close_state["closed"] = True

            error_message = ""
            try:
                return close_cb(*args, **kwargs)
            except Exception as exc:
                error_message = str(exc)
                raise
            finally:
                try:
                    close_model, close_type, close_sn = _extract_device_info(instrument_name, device)
                    if close_model in {"", "Unknown", instrument_name}:
                        close_model = model
                    if close_type in {"", "Unknown"}:
                        close_type = device_type
                    if close_sn in {"", "Unknown"}:
                        close_sn = serial_number
                    device_health_hub.register_disconnection(
                        instrument_key=instrument_name,
                        model=close_model or model,
                        device_type=close_type or device_type,
                        serial_number=close_sn or serial_number,
                        error_message=error_message,
                    )
                except Exception:
                    pass

        _set_attr_safely(_close_with_monitor, "__bsl_close_wrapped__", True)
        _set_attr_safely(device, "close", _close_with_monitor)

    # If class-level __del__ hook is unavailable, keep a weakref finalizer fallback
    # so monitor state still transitions to disconnected.
    if not del_hook_ready:
        try:
            device_ref = weakref.ref(device)
            gc_finalizer = weakref.finalize(
                device,
                _finalize_instrument_release,
                instrument_name,
                model,
                device_type,
                serial_number,
                close_state,
                device_ref,
            )
            _set_attr_safely(device, "_bsl_gc_finalizer", gc_finalizer)
        except Exception:
            pass


def _build_instrument(instrument_name: str, *args: Any, **kwargs: Any) -> Any:
    """
    Build an instrument object with monitoring hooks.

    Parameters
    ----------
    instrument_name : str
        Logical instrument key.
    *args : Any
        Positional constructor arguments.
    **kwargs : Any
        Keyword constructor arguments.

    Returns
    -------
    Any
        Concrete instrument object from the requested driver.
    """
    _ensure_logger_ready()
    _ensure_monitor_window()

    serial_hint = str(kwargs.get("device_sn", "")).strip()
    if not serial_hint and args and isinstance(args[0], str):
        serial_hint = args[0].strip()

    connecting_type = "MantisCam" if instrument_name == "mantisCam" else instrument_name
    try:
        device_health_hub.register_connecting(
            instrument_key=instrument_name,
            model=instrument_name,
            device_type=connecting_type,
            serial_number=serial_hint or "Unknown",
            note="Connection in progress.",
        )
    except Exception:
        pass

    try:
        device = create_instrument(instrument_name, *args, **kwargs)
    except Exception as exc:
        device_health_hub.register_failure(
            instrument_key=instrument_name,
            model=instrument_name,
            device_type="Unknown",
            serial_number=serial_hint or "Unknown",
            error_message=str(exc),
            unrecoverable=True,
        )
        raise

    model, device_type, serial_number = _extract_device_info(instrument_name, device)
    device_health_hub.register_connection(
        instrument_key=instrument_name,
        model=model,
        device_type=device_type,
        serial_number=serial_number,
    )
    _attach_runtime_hooks(
        instrument_name=instrument_name,
        device=device,
        model=model,
        device_type=device_type,
        serial_number=serial_number,
    )
    return device


def PM100D(device_sn: str = "") -> PM100DDriver:
    """
    Create a Thorlabs PM100D power meter controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    PM100DDriver
        PM100D instrument object.
    """
    return cast("PM100DDriver", _build_instrument("PM100D", device_sn))


def BSC203_HDR50() -> BSC203_HDR50Driver:
    """
    Create a Thorlabs BSC203 + HDR50 rotation stage controller.

    Returns
    -------
    BSC203_HDR50Driver
        BSC203_HDR50 instrument object.
    """
    return cast("BSC203_HDR50Driver", _build_instrument("BSC203_HDR50"))


def PM400(device_sn: str = "") -> PM400Driver:
    """
    Create a Thorlabs PM400 power meter controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    PM400Driver
        PM400 instrument object.
    """
    return cast("PM400Driver", _build_instrument("PM400", device_sn))


def DC2200(device_sn: str = "") -> DC2200Driver:
    """
    Create a Thorlabs DC2200 LED controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    DC2200Driver
        DC2200 instrument object.
    """
    return cast("DC2200Driver", _build_instrument("DC2200", device_sn))


def M69920(device_sn: str = "") -> M69920Driver:
    """
    Create a Newport M69920 arc lamp power supply controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    M69920Driver
        M69920 instrument object.
    """
    return cast("M69920Driver", _build_instrument("M69920", device_sn))


def CS260B(device_sn: str = "") -> CS260BDriver:
    """
    Create a Newport CS260B monochromator controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    CS260BDriver
        CS260B instrument object.
    """
    return cast("CS260BDriver", _build_instrument("CS260B", device_sn))


def HR4000CG(device_sn: str = "") -> HR4000CGDriver:
    """
    Create an OceanOptics HR4000CG spectrometer controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    HR4000CGDriver
        HR4000CG instrument object.
    """
    return cast("HR4000CGDriver", _build_instrument("HR4000CG", device_sn))


def RS_7_1(device_sn: str = "", power_on_test: bool = True) -> RS_7_1Driver:
    """
    Create a Gamma Scientific RS-7-1 tunable light source controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.
    power_on_test : bool, optional
        Whether to run power-on integrity tests, by default True.

    Returns
    -------
    RS_7_1Driver
        RS_7_1 instrument object.
    """
    return cast("RS_7_1Driver", _build_instrument("RS_7_1", device_sn, power_on_test))


def SP_2150(device_sn: str = "") -> SP_2150Driver:
    """
    Create a Princeton Instruments SP-2150 monochromator controller.

    Parameters
    ----------
    device_sn : str, optional
        Optional serial selector, by default ``""``.

    Returns
    -------
    SP_2150Driver
        SP_2150 instrument object.
    """
    return cast("SP_2150Driver", _build_instrument("SP_2150", device_sn))


def USB_520(
    device_sn: str = "",
    tear_on_startup: bool = True,
    reverse_negative: bool = True,
) -> USB520Driver:
    """
    Create a Futek USB-520 load-cell ADC controller.

    Parameters
    ----------
    device_sn : str, optional
        Device serial selector or channel alias, by default ``""``.
    tear_on_startup : bool, optional
        Run tare calibration at startup, by default True.
    reverse_negative : bool, optional
        Flip sign for negative-force orientation, by default True.

    Returns
    -------
    USB520Driver
        USB_520 instrument object.
    """
    return cast(
        "USB520Driver",
        _build_instrument(
            "USB_520",
            device_sn,
            tear_on_startup=tear_on_startup,
            reverse_negative=reverse_negative,
        ),
    )


def mantisCam(device_sn: str = "") -> MantisCamCtrl:
    """
    Create a MantisCam ZMQ control client.

    Parameters
    ----------
    device_sn : str, optional
        Optional logical camera identifier, by default ``""``.

    Returns
    -------
    MantisCamCtrl
        MantisCam control instrument object.

    Notes
    -----
    Camera family detection (GSense/F13/etc.) is derived from live metadata
    published by MantisCamUnified; no manual type flag is required.
    """
    return cast(
        "MantisCamCtrl",
        _build_instrument(
            "mantisCam",
            device_sn,
            log_level=__GLOBAL_LOG_LEVEL,
        ),
    )


__all__ = [
    "init_logger",
    "PM100D",
    "BSC203_HDR50",
    "PM400",
    "DC2200",
    "M69920",
    "CS260B",
    "HR4000CG",
    "RS_7_1",
    "SP_2150",
    "USB_520",
    "mantisCam",
]
