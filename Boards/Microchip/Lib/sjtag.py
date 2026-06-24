#import pydevd
from com.arm.rddi import RDDI
from com.arm.rddi import RDDI_JTAGS_STATE
from com.arm.rddi import RDDI_JTAGS_IR_DR
from jarray import zeros, array
import struct
import binascii
from time import sleep

def to_s8(val):
    return val > 127 and val - 256 or val

def to_u8(val):
    return val < 0 and val + 256 or val

def to_s8_array(x):
    return map(to_s8, x)

def to_u8_array(x):
    return map(to_u8, x)

def unpack32(raw):
    return struct.unpack('<I', ''.join(map(chr, to_u8_array(raw))))[0]

def to_ircmd(cmd):
    b = zeros(4, 'b')
    w = struct.pack('<I', cmd)
    b[0] = to_s8(ord(w[0]))
    b[1] = to_s8(ord(w[1]))
    b[2] = to_s8(ord(w[2]))
    b[3] = to_s8(ord(w[3]))
    return b

STATE_RTI = RDDI_JTAGS_STATE.RDDI_JTAGS_RTI.ordinal()
STATE_PIR = RDDI_JTAGS_STATE.RDDI_JTAGS_PIR.ordinal()
STATE_PDR = RDDI_JTAGS_STATE.RDDI_JTAGS_PDR.ordinal()
CHAIN_IR = RDDI_JTAGS_IR_DR.RDDI_JTAGS_IR.ordinal()
CHAIN_DR = RDDI_JTAGS_IR_DR.RDDI_JTAGS_DR.ordinal()

class SJTag:
    IR_LEN = 28 # SJTag IRLEN
    CMD_CODE_READ_UUID  = 0xFF7F7FA
    CMD_CODE_READ_NONCE = 0xFF7F57A
    CMD_CODE_READ_MODE  = 0xFF7F47A
    CMD_CODE_DO_UNLOCK  = 0xFF7F4FA
    CMD_CODE_SET_RESP   = 0xFF7F67A
    MAX_UNLOCK_RETRY = 4
    def __init__(self, jtag, sjtag_id):
        #pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=False)
        self.jtag = jtag
        self.sjtag_id = sjtag_id
        jtag.connect(zeros(1, 'i'))
        self.softReset()

    def disconnect(self):
        # body of destructor
        self.jtag.disconnect()

    def softReset(self):
        self.jtag.TMS(8, to_s8_array([0x7f]))
        self.jtag.stateJump(STATE_RTI)

    def identify(self):
        self.softReset()
        DRout = zeros(4, 'b')
        self.jtag.scanIO(CHAIN_DR, 32, None, DRout, STATE_RTI, True)
        id = unpack32(DRout)
        #print("IDCODE = %08x" % (id))
        return id

    def dumpBin(self, a):
        print(binascii.hexlify(a))

    def sjtag_read_cmd(self, cmd, l):
        cmdbytes = to_ircmd(cmd)
        DRout = zeros(l, 'b')
        #print ("CMD %08x, data length %d" % (cmd, l))
        #print (cmdbytes)
        try:
            #print("scanIRDR, IR_LEN = %d" % (self.IR_LEN))
            self.jtag.scanIRDR(self.IR_LEN, cmdbytes, l * 8, None, DRout, STATE_RTI, True)
        finally:
            print("Executed read cmd = %08x" % (cmd))
        return DRout

    def sjtag_write_cmd(self, cmd, data):
        cmdbytes = to_ircmd(cmd)
        #print ("WRITE CMD %08x, data length %d" % (cmd, len(data)))
        #print (data)
        try:
            #print("scanIRDR, IR_LEN = %d" % (self.IR_LEN))
            self.jtag.scanIRDR(self.IR_LEN, cmdbytes, len(data) * 8, data, None, STATE_RTI, True)
        finally:
            print("Executed write cmd = %08x" % (cmd))

    def isLocked(self):
        id = self.identify()
        return id == self.sjtag_id

    def unLock(self, calc_response, key):
        print("Unlocking, key = ", key)
        #x = self.sjtag_read_cmd(self.CMD_CODE_READ_UUID, 10)
        for i in range(self.MAX_UNLOCK_RETRY):
            nonce = self.sjtag_read_cmd(self.CMD_CODE_READ_NONCE, 4 * 8)
            #self.dumpBin(nonce)
            resp = calc_response(key, binascii.hexlify(nonce))
            # Convert to Java Array to write response
            resp_jtag = array(to_s8_array(map(ord, resp)), 'b')
            self.sjtag_write_cmd(self.CMD_CODE_SET_RESP, resp_jtag)
            x = self.sjtag_read_cmd(self.CMD_CODE_DO_UNLOCK, 1)
            # self.dumpBin(x)
            # Give it a chance to unlock
            sleep(0.1)
            id = self.identify()
            if id != self.sjtag_id:
                print("Unlock succeeded at iteration %d, IDCODE = %08x" % (i, id))
                return
            else:
                print("Unlock(%d) failed, retrying" % (i))
        if self.isLocked():
            raise Exception("The Secure JTAG unlock failed, check the unlock key in the DTSL options")
