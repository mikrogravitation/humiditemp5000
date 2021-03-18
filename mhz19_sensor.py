def _check_checksum(data):
    if (sum(data[1:]) & 0xff) == 0: # ignore first byte
        return True
    else:
        return False

def _compute_checksum(data):
    checksum = (-sum(data[1:])) & 0xff
    return checksum

class MHZ19Sensor:

    provides = ["co2_concentration"]

    def __init__(self, uart):

        uart.init(baudrate=9600, bits=8, parity=None, stop=1)
        self._uart = uart

        # push bytes to clear the uart
        self._send_command(0)

    def _send_command(self, command_id, args=bytes(0)):
        command = bytearray(9)
        command[0] = 0xff # start byte
        command[1] = 0x01 # sensor number
        command[2] = command_id
        assert len(args) <= 5
        command[3:3 + len(args)] = args
        command[8] = _compute_checksum(command)

        self._uart.write(command)

    def _get_concentration(self):
        # clear read buffer
        self._uart.read()
        self._send_command(0x86)
        reply = bytes()
        while len(reply) < 9:
            new_bytes = self._uart.read(9 - len(reply))
            if new_bytes:
                reply += new_bytes

        assert _check_checksum(reply)
        assert reply[0] == 0xff
        assert reply[1] == 0x86
        
        concentration = reply[2] * 256 + reply[3]

        return concentration

    def readout(self):
        return {"co2_concentration": self._get_concentration()}
