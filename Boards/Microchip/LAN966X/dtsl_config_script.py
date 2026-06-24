#import pydevd
from com.arm.debug.dtsl.configurations import ConfigurationBaseSDF
from com.arm.debug.dtsl.configurations import DTSLv1
from com.arm.debug.dtsl.components import FormatterMode
from com.arm.debug.dtsl.components import APBAP
from com.arm.debug.dtsl.components import AXIAP
from com.arm.debug.dtsl.components import Device
from com.arm.debug.dtsl.components import DeviceInfo
from com.arm.debug.dtsl.configurations.options import IIntegerOption
from com.arm.debug.dtsl.components import ETBTraceCapture
from com.arm.debug.dtsl.components import CSCTI
from com.arm.debug.dtsl.components import ETMv3_5TraceSource
from com.arm.debug.dtsl.configurations import TimestampInfo
import hashlib
import sys
sys.path.insert(0, '../Lib')
from sjtag import SJTag

coreNames_cortexA7 = ["Cortex-A7"]


# Import core specific functions
import a7_rams

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
                +[DTSLv1.tabPage("trace", "Trace Capture", childOptions=[
                    DTSLv1.integerOption('timestampFrequency', 'Timestamp frequency', defaultValue=25000000, isDynamic=False, description="This value will be used to set the Counter Base Frequency ID Register of the Timestamp generator.\nIt represents the number of ticks per second and is used to translate the timestamp value reported into a number of seconds.\nNote that changing this value may not result in a change in the observed frequency."),
                    DTSLv1.enumOption('traceCapture', 'Trace capture method', defaultValue="none",
                        values = [("none", "None"), ("CSETB", "On Chip Trace Buffer (CSETB)")]),
                ])]
                +[DTSLv1.tabPage("cortexA7", "Cortex-A7", childOptions=[
                    DTSLv1.booleanOption('coreTrace', 'Enable Cortex-A7 core trace', defaultValue=False,
                        childOptions = [
                            DTSLv1.booleanOption('Cortex-A7', 'Enable Cortex-A7 trace', defaultValue=True),
                            DTSLv1.booleanOption('triggerhalt', "ETM Triggers halt execution", description="Enable the ETM triggers to halt execution", defaultValue=False),
                            DTSLv1.booleanOption('timestamp', "Enable ETM Timestamps", description="Controls the output of timestamps into the ETM output streams", defaultValue=True),
                            DTSLv1.booleanOption('contextIDs', "Enable ETM Context IDs", description="Controls the output of context ID values into the ETM output streams", defaultValue=True,
                                childOptions = [
                                    DTSLv1.enumOption('contextIDsSize', 'Context ID Size', defaultValue="32",
                                        values = [("8", "8 bit"), ("16", "16 bit"), ("32", "32 bit")])
                                    ]),
                            ETMv3_5TraceSource.cycleAccurateOption(DtslScript.getSourcesForCoreType("Cortex-A7")),
                            ETMv3_5TraceSource.dataOption(DtslScript.getSourcesForCoreType("Cortex-A7")),
                            DtslScript.getTraceRangeOption()
                        ]
                    )
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
    
    @staticmethod
    def getTraceRangeOption():
        # Trace range selection (e.g. for linux kernel)
        TRACE_RANGE_DESCRIPTION = '''Limit trace capture to the specified range. This is useful for restricting trace capture to an OS (e.g. Linux kernel)'''
        return DTSLv1.booleanOption('traceRange', 'Trace capture range',  description=TRACE_RANGE_DESCRIPTION, defaultValue = False, childOptions = [
                   DTSLv1.integerOption('start', 'Start address',
                       description='Start address for trace capture',
                       defaultValue=0,
                       display=IIntegerOption.DisplayFormat.HEX),
                   DTSLv1.integerOption('end', 'End address',
                       description='End address for trace capture',
                       defaultValue=0xFFFFFFFF,
                       display=IIntegerOption.DisplayFormat.HEX)])
    
    
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
        APBAP(self, self.findDevice("CSMEMAP_0"), "CSMEMAP_0")
        AXIAP(self, self.findDevice("CSMEMAP_1"), "CSMEMAP_1")
        
        # Trace start/stop CTIs
        ctiDevices = ["CSCTI_1"]
        for ctiName in ctiDevices:
            CSCTI(self, self.findDevice(ctiName), ctiName)
        
        self.cortexA7cores = []
        for coreName in (coreNames_cortexA7):
            # Create core
            coreDevice = a7_rams.A7CoreDevice(self, self.findDevice(coreName), coreName)
            deviceInfo = DeviceInfo("core", "Cortex-A7")
            coreDevice.setDeviceInfo(deviceInfo)
            self.cortexA7cores.append(coreDevice)
            self.addDeviceInterface(coreDevice)
            a7_rams.registerInternalRAMs(coreDevice)
            
            # Create CTI (if a CTI exists for this core)
            ctiName = self.getCTINameForCore(coreName)
            if not ctiName is None:
                CSCTI(self, self.findDevice(ctiName), ctiName)
            
            # Create Trace Macrocell (if a macrocell exists for this core - disabled by default - will enable with option)
            tmName = self.getTraceSourceNameForCore(coreName)
            if not tmName == None:
                tm = ETMv3_5TraceSource(self, self.findDevice(tmName), tmName)
                tm.setEnabled(False)
            
    def createETBTraceCapture(self, deviceName):
        etbTrace = ETBTraceCapture(self, self.findDevice(deviceName), deviceName)
        self.addTraceCaptureInterface(etbTrace)
    
    def postConnect(self):
        ConfigurationBaseSDF.postConnect(self)
        
        if self.getOptions().getOption("options.trace.timestampFrequency"):
            freq = self.getOptionValue("options.trace.timestampFrequency")
            # Update the value so the trace decoder can access it
            tsInfo = TimestampInfo(freq)
            self.setTimestampInfo(tsInfo)
        
    
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
        
        coreTraceEnabled = self.getOptionValue("options.cortexA7.coreTrace")
        for coreName in coreNames_cortexA7:
            tmName = self.getTraceSourceNameForCore(coreName)
            if tmName:
                coreTM = self.getDeviceInterface(tmName)
                thisCoreTraceEnabled = self.getOptionValue("options.cortexA7.coreTrace.{}".format(coreName))
                enableSource = coreTraceEnabled and thisCoreTraceEnabled
                self.setTraceSourceEnabled(tmName, enableSource)
                if(self.getOptionValue("options.cortexA7.coreTrace.traceRange")):
                    coreTM.clearAllTraceRanges()
                    coreTM.addTraceRange(self.getOptionValue("options.cortexA7.coreTrace.traceRange.start"),
                                         self.getOptionValue("options.cortexA7.coreTrace.traceRange.end"))
                coreTM.setTriggerGeneratesDBGRQ(self.getOptionValue("options.cortexA7.coreTrace.triggerhalt"))
                coreTM.setTimestampingEnabled(self.getOptionValue("options.cortexA7.coreTrace.timestamp"))
                self.setContextIDEnabled(coreTM, self.getOptionValue("options.cortexA7.coreTrace.contextIDs"),
                                         self.getOptionValue("options.cortexA7.coreTrace.contextIDs.contextIDsSize"))
        
        traceMode = self.getOptionValue("options.trace.traceCapture")
        if traceMode != "none":
            # ETB Devices
            if traceMode == "CSETB":
                self.createETBTraceCapture("CSETB")
            self.enableTraceCapture(traceMode)
            self.setStreamIDs(traceMode)
            self.configureTraceCapture(traceMode)
            
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
        
        for core in range(len(self.cortexA7cores)):
            a7_rams.applyCacheDebug(configuration = self,
                                     optionName = "options.rams.cacheDebug",
                                     device = self.cortexA7cores[core])
            a7_rams.applyCachePreservation(configuration = self,
                                            optionName = "options.rams.cachePreserve",
                                            device = self.cortexA7cores[core])

    def postRDDIConnect(self):
        ConfigurationBaseSDF.postRDDIConnect(self)
        sjtag = SJTag(self.getJTAG(), 0x10321445)
        if sjtag.isLocked():
            sjtag.unLock(calc_response, self.sjtag_key)
        else:
            print("JTAG is configured open it seems")
        sjtag.disconnect()

    @staticmethod
    def getSourcesForCoreType(coreType):
        '''Get the Trace Sources for a given coreType
           Use parameter-binding to ensure that the correct Sources
           are returned for the core type passed only'''
        def getSources(self):
            return self.getTraceSourcesForCoreType(coreType)
        return getSources
    
