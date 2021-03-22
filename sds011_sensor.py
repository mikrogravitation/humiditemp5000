def _check_checksum(data):
    checksum = sum(data[2:8]) & 0xff
    return (checksum == data[8])

def _check_reply(data):
    if len(data) < 10:
        return False
    if data[-1] != 0xab or data[-10] != 0xaa or data[-9] != 0xc0:
        return False
    return True

class SDS011Sensor:

    provides = ["pm2_5_ug_m3", "pm10_ug_m3"]

    def __init__(self, uart):

        uart.init(baudrate=9600, bits=8, parity=None, stop=1)
        self._uart = uart

    def readout(self):

        reply = bytes()
        i = 0
        while not _check_reply(reply):
            new_bytes = self._uart.read()
            if new_bytes:
                reply += new_bytes
            i += 1
            if i >= 20:
                raise RuntimeError("too many iterations")

        reply = reply[-10:]

        assert _check_checksum(reply)
        assert reply[0] == 0xaa
        assert reply[1] == 0xc0
        assert reply[9] == 0xab
        
        pm25 = (reply[3] * 256 + reply[2]) / 10.
        pm10 = (reply[5] * 256 + reply[4]) / 10.

        return {"pm2_5_ug_m3": pm25, "pm10_ug_m3": pm10}
