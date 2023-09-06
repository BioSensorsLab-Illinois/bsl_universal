class _bsl_inst_info_class:
    def __init__(self, *, MANUFACTURE:str="N/A", MODEL:str="N/A", TYPE:str="N/A", INTERFACE:str="Serial", BAUDRATE:int=0, SERIAL_NAME:str="N/A", SERIAL_SN:str="N/A", USB_PID:str="0x9999", USB_VID:str="0x9999", QUERY_CMD:str="N/A", QUERY_E_RESP:str="N/A", SN_REG=".*", QUERY_SN_CMD=""):
        self.MANUFACTURE            =   MANUFACTURE
        self.MODEL                  =   MODEL              
        self.TYPE                   =   TYPE               
        self.BAUDRATE               =   BAUDRATE           
        self.SERIAL_NAME            =   SERIAL_NAME         
        self.SERIAL_SN              =   SERIAL_SN      
        self.USB_PID                =   USB_PID  
        self.USB_VID                =   USB_VID     
        self.QUERY_CMD              =   QUERY_CMD   
        self.QUERY_E_RESP           =   QUERY_E_RESP
        self.QUERY_SN_CMD           =   QUERY_SN_CMD
        self.INTERFACE              =   INTERFACE
        self.SN_REG                 =   SN_REG
