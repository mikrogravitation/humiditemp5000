import dht

class DHT22Sensor:

    provides = ["temperature", "humidity"]

    def __init__(self, port):
        self._sensor = dht.DHT22(port)

    def readout(self):
        self._sensor.measure()
        return {"temperature": self._sensor.temperature(), "humidity": self._sensor.humidity()}
