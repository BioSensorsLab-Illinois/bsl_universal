from ._bsl_inst_info_class import _bsl_inst_info_class

class _bsl_inst_info_list:
    PM100D = _bsl_inst_info_class(
        MANUFACTURE="THORLAB",
        MODEL="PM100D",
        TYPE="Power Meter",
        INTERFACE="VISA",
        USB_PID="0x8078",
        USB_VID="0x1313",
        QUERY_CMD="*IDN?",
        QUERY_SN_CMD="*IDN?",
        QUERY_E_RESP="PM100D",
        SN_REG="(?<=,)P[0-9]+(?=,)"
    )

    DC2200 = _bsl_inst_info_class(
        MANUFACTURE="THORLAB",
        MODEL="DC2200",
        TYPE="LED Controller",
        INTERFACE="VISA",
        USB_PID="0x80C8",
        USB_VID="0x1313",
        QUERY_CMD="*IDN?",
        QUERY_SN_CMD="*IDN?",
        QUERY_E_RESP="DC2200",
        SN_REG="M\d{8}"
    )

    M69920 = _bsl_inst_info_class(
        MANUFACTURE="Newport Corp.",
        MODEL="M69920",
        TYPE="Power Supply",
        INTERFACE="Serial",
        BAUDRATE=9600,
        SERIAL_NAME="69920",
        QUERY_CMD="IDN?\r",
        QUERY_E_RESP="69920"
    )

    USB_520 = _bsl_inst_info_class(
        MANUFACTURE="Futek",
        MODEL="USB_520",
        TYPE="USB ADC for Load Cells",
        INTERFACE="Serial",
        BAUDRATE=9600,
        SERIAL_SN="N/A",
        QUERY_SN_CMD = "N/A",
        QUERY_E_RESP="g"
    )
    

    CS260B = _bsl_inst_info_class(
        MANUFACTURE="Newport Corp.",
        MODEL="CS260B-Q-MC-D",
        TYPE="Monochromator",
        SERIAL_NAME="???",
        INTERFACE="VISA",
        USB_PID="0x0014",
        USB_VID="0x1FDE",
        QUERY_CMD="*IDN?",
        QUERY_SN_CMD="*IDN?",
        QUERY_E_RESP="CS260B",
        SN_REG="^Newport Corp,CS260B,([^,]+)"
    )

    HR4000CG = _bsl_inst_info_class(
        MANUFACTURE="Ocean Optics",
        MODEL="HR4000CG",
        TYPE="Spectrometer",
        SERIAL_NAME="???",
        INTERFACE="USB-SDK",
        USB_PID="???",
        USB_VID="???"
    )

    TEST_DEVICE_NO_BAUD = _bsl_inst_info_class(
        MANUFACTURE="BSL",
        MODEL="TEST_DEVICE_BAUD",
        TYPE="TEST_DEVICE_BAUD",
        SERIAL_NAME="Incoming",
        INTERFACE="Serial",
        USB_PID="0x8078",
        USB_VID="0x1313",
        QUERY_CMD="*IDN?",
        QUERY_SN_CMD="*IDN?",
        QUERY_E_RESP="PM100D",
        SN_REG="(?<=,)P[0-9]+(?=,)"
    )

    TEST_DEVICE_BAUD = _bsl_inst_info_class(
        MANUFACTURE="BSL",
        MODEL="TEST_DEVICE_NO_BAUD",
        TYPE="TEST_DEVICE_BAUD",
        BAUDRATE=115200,
        SERIAL_NAME="Incoming",
        INTERFACE="Serial",
        USB_PID="0x8078",
        USB_VID="0x1313",
        QUERY_CMD="*IDN?",
        QUERY_SN_CMD="*IDN?",
        QUERY_E_RESP="PM100D",
        SN_REG="(?<=,)P[0-9]+(?=,)"
    )

    RS_7_1 = _bsl_inst_info_class(
        MANUFACTURE="Gamma Scientific",
        MODEL="RS_7_1",
        TYPE="Tunable Light Source - LED",
        BAUDRATE=460800,
        SERIAL_NAME="FT232R USB UART",
        INTERFACE="Serial",
        USB_PID="0x0403",
        USB_VID="0x6001",
        QUERY_CMD="USN\r\n",
        QUERY_E_RESP="HX0650",
        QUERY_SN_CMD="USN\r\n",
        SN_REG=".*"
    )

    SP_2150 = _bsl_inst_info_class(
        MANUFACTURE="Princeton Instruments",
        MODEL="SP_2150",
        TYPE="Monochromator",
        BAUDRATE=9600,
        SERIAL_NAME="ACTON RESEARCH CONTROLLER",
        INTERFACE="Serial",
        USB_PID="0x6001",
        USB_VID="0x0403",
        QUERY_CMD="model\r",
        QUERY_E_RESP="SP-2-150i",
        QUERY_SN_CMD="SERIAL\r",
        SN_REG="[0-9]+"
    )

    mantisCam = _bsl_inst_info_class(
        MANUFACTURE="BioSensors Lab",
        MODEL="mantisCam_Generic",
        TYPE="Camera",
        INTERFACE="ZMQ"
    )
