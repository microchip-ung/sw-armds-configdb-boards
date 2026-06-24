#import pydevd
from com.arm.debug.dtsl.configurations import ConfigurationBaseSDF
from com.arm.debug.dtsl.configurations import DTSLv1
from com.arm.debug.dtsl.components import APBAP
from com.arm.debug.dtsl.components import Device
from com.arm.debug.dtsl.components import DeviceInfo
from com.arm.debug.dtsl.components import CSCTI
import hashlib
import sys
sys.path.insert(0, '../Lib')
from sjtag import SJTag

coreNames_cortexA53 = ["Cortex-A53"]


# Import core specific functions
import a53_rams

def calc_response(kdf_key, kdf_context):
    m = hashlib.sha256()
    m.update(kdf_context.decode('hex'))
    m.update(kdf_key.decode('hex'))
    return m.digest()

class DtslScript(ConfigurationBaseSDF):
    @staticmethod
    def getOptionList():
        return [
            DTSLv1.tabSet("options", "Options", childOptions=
                [DTSLv1.tabPage("sjtag", "Secure JTAG Config", childOptions=[
                    DTSLv1.stringOption('key', 'Secure JTAG Unlock Key',
                                        description='32 bytes hex SJTAG unlock key',
                                        defaultValue="0000000000000000000000000000000000000000000000000000000000000000"),
                ])]
                +[DTSLv1.tabPage("rams", "Cache RAMs", childOptions=[
                    # Turn cache debug mode on/off
                    DTSLv1.booleanOption('cacheDebug', 'Cache debug mode',
                                         description='Turning cache debug mode on enables reading the cache RAMs. Enabling it may adversely impact debug performance.',
                                         defaultValue=False, isDynamic=True),
                    DTSLv1.booleanOption('cachePreserve', 'Preserve cache contents in debug state',
                                         description='Preserve the contents of caches while the core is stopped.',
                                         defaultValue=False, isDynamic=True),
                ])]
            )
        ]
    
    
    def __init__(self, root):
        #pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=False)
        ConfigurationBaseSDF.__init__(self, root)
        self.discoverDevices()
    
    # +----------------------------+
    # | Target dependent functions |
    # +----------------------------+
    
    def discoverDevices(self):
        '''Find and create devices'''
        
        # MEMAP devices
        APBAP(self, self.findDevice("CSMEMAP"), "CSMEMAP")
        
        self.cortexA53cores = []
        for coreName in (coreNames_cortexA53):
            # Create core
            coreDevice = a53_rams.A53CoreDevice(self, self.findDevice(coreName), coreName)
            deviceInfo = DeviceInfo("core", "Cortex-A53")
            coreDevice.setDeviceInfo(deviceInfo)
            self.cortexA53cores.append(coreDevice)
            self.addDeviceInterface(coreDevice)
            a53_rams.registerInternalRAMs(coreDevice)
            
            # Create CTI (if a CTI exists for this core)
            ctiName = self.getCTINameForCore(coreName)
            if not ctiName is None:
                CSCTI(self, self.findDevice(ctiName), ctiName)
            
    # +--------------------------------+
    # | Callback functions for options |
    # +--------------------------------+
    
    def optionValuesChanged(self):
        '''Callback to update the configuration state after options are changed'''
        if not self.isConnected():
            self.setInitialOptions()
        
        self.updateDynamicOptions()
        
    def setInitialOptions(self):
        '''Set the initial options'''
        key = self.getOptionValue("options.sjtag.key")
        if key == None or len(key) == 0:
            # Default if empty
            key = "0" * 64
        if len(key) != 64:
            raise Exception("SJTAG key must have 64 hex characters")
        try:
            bin_key = key.decode('hex', 'strict')
        except:
            raise Exception("SJTAG incorrectly formatted, must be hexdecimal")
        if len(bin_key) != 32:
            raise Exception("SJTAG binary key must 32 bytes")
        self.sjtag_key = key

    def updateDynamicOptions(self):
        '''Update the dynamic options'''
        
        for core in range(len(self.cortexA53cores)):
            a53_rams.applyCacheDebug(configuration = self,
                                     optionName = "options.rams.cacheDebug",
                                     device = self.cortexA53cores[core])
            a53_rams.applyCachePreservation(configuration = self,
                                            optionName = "options.rams.cachePreserve",
                                            device = self.cortexA53cores[core])
        
    def postRDDIConnect(self):
        ConfigurationBaseSDF.postRDDIConnect(self)
        sjtag = SJTag(self.getJTAG(), 0x00431445)
        if sjtag.isLocked():
            sjtag.unLock(calc_response, self.sjtag_key)
        else:
            print("JTAG is configured open it seems")
        sjtag.disconnect()
