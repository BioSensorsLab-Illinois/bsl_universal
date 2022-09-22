class _bsl_type:
    class CustomError(Exception):
        pass
    class DeviceConnectionFailed(CustomError):
        pass
    class DeviceOperationError(CustomError):
        pass
    class DeviceTimeOutError(CustomError):
        pass
    class DeviceInconsistentError(CustomError):
        pass